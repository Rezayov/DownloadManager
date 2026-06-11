#!/usr/bin/env python3
"""
Self-configurable Download Manager with CLI Control (Index-Based)

Highlights:
- Add, remove, move, restart, list, export, search links, retry failures
- One-shot `dm run`: downloads selected pending/failed tasks, then exits
- Atomic state persistence with file locking
- Resumable downloads, checksum verification, retries, timeout, stall detection
- Optional segmented downloads with strict Range validation
- Filename collision avoidance and basic Content-Disposition filename support
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import logging
import os
import re
import signal
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from queue import Empty, PriorityQueue
from typing import Any, Callable, Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import yaml
except ImportError:  # optional dependency
    yaml = None

try:
    import fcntl
except ImportError:  # non-POSIX fallback; macOS has fcntl
    fcntl = None

try:
    from rich.console import Console
    from rich.live import Live
    from rich.panel import Panel
    from rich.progress import (
        BarColumn,
        Progress,
        TaskID,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
    )
    from rich.table import Table

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None  # type: ignore
    TaskID = int  # type: ignore


VERSION = "2.1.0"


DEFAULT_CONFIG = {
    "download_dir": "~/Downloads/Manager",
    "log_dir": "~/Downloads/Manager/logs",
    "state_file": "~/Downloads/Manager/state.json",
    "failed_log": "~/Downloads/Manager/failed_links.txt",
    "max_concurrent": 4,
    "chunk_size": 1024 * 1024,
    "retries": 3,
    "retry_backoff": 2,
    "timeout": 30,
    "stall_timeout": 60,
    "speed_limit": 0,
    "user_agent": f"DM/{VERSION}",
    "proxy": None,
    "checksum_verify": True,
    "segments": 1,
    "plugin_dir": "~/Downloads/Manager/plugins",
    "update_check": False,
    "update_url": "https://api.github.com/repos/yourname/dm/releases/latest",
    "tui": True,
}


# ----------------------------------------------------------------------
# Configuration
# ----------------------------------------------------------------------
class Config:
    def __init__(self, config_path: Optional[str] = None):
        self.data = DEFAULT_CONFIG.copy()
        self.config_path = os.path.expanduser(config_path) if config_path else None
        self._load_from_file()
        self._apply_env_overrides()
        self._expand_paths()

    def _load_from_file(self) -> None:
        if not self.config_path or not os.path.exists(self.config_path):
            return
        with open(self.config_path, "r", encoding="utf-8") as f:
            if self.config_path.endswith((".yaml", ".yml")):
                if yaml is None:
                    raise ImportError("PyYAML is required for YAML config files")
                loaded = yaml.safe_load(f) or {}
            else:
                loaded = json.load(f)
        if not isinstance(loaded, dict):
            raise ValueError("Config file must contain an object/dictionary")
        self.data.update(loaded)

    def _apply_env_overrides(self) -> None:
        mapping = {
            "DM_DOWNLOAD_DIR": "download_dir",
            "DM_LOG_DIR": "log_dir",
            "DM_STATE_FILE": "state_file",
            "DM_FAILED_LOG": "failed_log",
            "DM_MAX_CONCURRENT": "max_concurrent",
            "DM_CHUNK_SIZE": "chunk_size",
            "DM_RETRIES": "retries",
            "DM_SPEED_LIMIT": "speed_limit",
            "DM_USER_AGENT": "user_agent",
            "DM_PROXY": "proxy",
            "DM_SEGMENTS": "segments",
            "DM_TIMEOUT": "timeout",
            "DM_STALL_TIMEOUT": "stall_timeout",
        }
        int_keys = {
            "max_concurrent",
            "chunk_size",
            "retries",
            "speed_limit",
            "segments",
            "timeout",
            "stall_timeout",
        }
        for env, key in mapping.items():
            if env not in os.environ:
                continue
            value: Any = os.environ[env]
            if key in int_keys:
                value = int(value)
            self.data[key] = value

    def _expand_paths(self) -> None:
        for key in ("download_dir", "log_dir", "state_file", "plugin_dir", "failed_log"):
            if self.data.get(key):
                self.data[key] = os.path.expanduser(str(self.data[key]))

    def update_from_args(self, args: argparse.Namespace) -> None:
        download_dir = getattr(args, "download_dir", None) or getattr(args, "output", None)
        if download_dir:
            self.data["download_dir"] = download_dir
        if getattr(args, "max_concurrent", None):
            self.data["max_concurrent"] = args.max_concurrent
        if getattr(args, "speed_limit", None) is not None:
            self.data["speed_limit"] = args.speed_limit
        if getattr(args, "segments", None):
            self.data["segments"] = args.segments
        if getattr(args, "no_tui", False):
            self.data["tui"] = False
        self._expand_paths()

    def __getattr__(self, name: str) -> Any:
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"Config has no attribute '{name}'")


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def setup_logging(config: Config) -> logging.Logger:
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "dm.log"

    logger = logging.getLogger("dm")
    logger.setLevel(logging.DEBUG)
    logger.propagate = False

    # Avoid duplicate handlers when tests instantiate several managers.
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)
    return logger


# ----------------------------------------------------------------------
# File locking and atomic state
# ----------------------------------------------------------------------
class FileLock:
    """Small advisory lock for state-file operations. macOS supports fcntl.flock."""

    def __init__(self, lock_path: Path):
        self.lock_path = lock_path
        self._fh = None
        self._thread_lock = threading.RLock()

    def __enter__(self):
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        self._thread_lock.acquire()
        self._fh = open(self.lock_path, "a+")
        if fcntl is not None:
            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._fh and fcntl is not None:
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            if self._fh:
                self._fh.close()
            self._fh = None
            self._thread_lock.release()


# ----------------------------------------------------------------------
# Task model
# ----------------------------------------------------------------------
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass
class DownloadTask:
    url: str
    dest_path: str
    priority: int = 5
    sequence: int = 0
    expected_checksum: Optional[str] = None
    checksum_algo: str = "sha256"
    headers: Dict[str, str] = field(default_factory=dict)
    auto_filename: bool = False
    bytes_downloaded: int = 0
    total_size: int = 0
    status: TaskStatus = TaskStatus.PENDING
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    completed_at: Optional[float] = None
    last_progress_time: float = field(default_factory=time.time)
    _cancel_event: threading.Event = field(default_factory=threading.Event, init=False, repr=False)

    def cancel(self) -> None:
        self._cancel_event.set()
        if self.status != TaskStatus.COMPLETED:
            self.status = TaskStatus.CANCELLED

    def reset_for_run(self) -> None:
        self._cancel_event.clear()
        self.status = TaskStatus.PENDING
        self.error = None
        self.completed_at = None
        self.last_progress_time = time.time()

    @property
    def is_cancelled(self) -> bool:
        return self._cancel_event.is_set()

    @property
    def progress_percent(self) -> float:
        if self.total_size > 0:
            return min(100.0, (self.bytes_downloaded / self.total_size) * 100)
        return 0.0

    def update_progress_time(self) -> None:
        self.last_progress_time = time.time()

    def is_stalled(self, stall_timeout: int) -> bool:
        return (time.time() - self.last_progress_time) > stall_timeout

    def to_dict(self) -> Dict[str, Any]:
        return {
            "url": self.url,
            "dest_path": self.dest_path,
            "priority": self.priority,
            "sequence": self.sequence,
            "expected_checksum": self.expected_checksum,
            "checksum_algo": self.checksum_algo,
            "headers": self.headers,
            "auto_filename": self.auto_filename,
            "bytes_downloaded": self.bytes_downloaded,
            "total_size": self.total_size,
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }

    @classmethod
    def from_dict(cls, item: Dict[str, Any], default_status: TaskStatus = TaskStatus.PENDING) -> "DownloadTask":
        status_value = item.get("status", default_status.value)
        try:
            status = TaskStatus(status_value)
        except ValueError:
            status = default_status
        task = cls(
            url=item["url"],
            dest_path=item["dest_path"],
            priority=int(item.get("priority", 5)),
            sequence=int(item.get("sequence", 0)),
            expected_checksum=item.get("expected_checksum"),
            checksum_algo=item.get("checksum_algo", "sha256"),
            headers=dict(item.get("headers") or {}),
            auto_filename=bool(item.get("auto_filename", False)),
        )
        task.bytes_downloaded = int(item.get("bytes_downloaded", 0) or 0)
        task.total_size = int(item.get("total_size", 0) or 0)
        task.status = status
        task.error = item.get("error")
        task.created_at = float(item.get("created_at", time.time()))
        task.completed_at = item.get("completed_at")
        task.last_progress_time = time.time()
        return task


# ----------------------------------------------------------------------
# Throttling
# ----------------------------------------------------------------------
class Throttle:
    def __init__(self, rate_bps: int):
        self.rate = rate_bps
        self.tokens = 0.0
        self.last_time = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, bytes_count: int) -> float:
        if self.rate <= 0:
            return 0.0
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_time
            self.tokens += elapsed * self.rate
            self.tokens = min(self.tokens, float(self.rate))
            self.last_time = now
            if bytes_count <= self.tokens:
                self.tokens -= bytes_count
                return 0.0
            deficit = bytes_count - self.tokens
            self.tokens = 0.0
            return deficit / self.rate


# ----------------------------------------------------------------------
# Utility helpers
# ----------------------------------------------------------------------
def validate_url(url: str) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")


def safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("\x00", "")
    name = os.path.basename(name)
    name = re.sub(r"[/:]+", "_", name)
    return name or "download"


def filename_from_content_disposition(header_value: Optional[str]) -> Optional[str]:
    if not header_value:
        return None
    # RFC 5987 form: filename*=UTF-8''file%20name.txt
    m = re.search(r"filename\*\s*=\s*(?:[\w-]+'')?([^;]+)", header_value, re.I)
    if m:
        return safe_filename(m.group(1).strip().strip('"'))
    # Plain form: filename="file name.txt"
    m = re.search(r"filename\s*=\s*\"([^\"]+)\"", header_value, re.I)
    if m:
        return safe_filename(m.group(1))
    m = re.search(r"filename\s*=\s*([^;]+)", header_value, re.I)
    if m:
        return safe_filename(m.group(1).strip().strip('"'))
    return None


def parse_content_range(value: Optional[str]) -> Optional[Tuple[int, int, int]]:
    if not value:
        return None
    m = re.match(r"bytes\s+(\d+)-(\d+)/(\d+|\*)", value.strip(), re.I)
    if not m or m.group(3) == "*":
        return None
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def confirm(prompt: str, default: str = "n") -> bool:
    suffix = "[Y/n]" if default.lower() == "y" else "[y/N]"
    ans = input(f"{prompt} {suffix}: ").strip().lower()
    if not ans:
        ans = default.lower()
    return ans in {"y", "yes"}


# ----------------------------------------------------------------------
# Download manager core
# ----------------------------------------------------------------------
class DownloadManager:
    def __init__(self, config: Config, logger: logging.Logger, install_signal_handlers: bool = True):
        self.config = config
        self.logger = logger
        self.queue: PriorityQueue[Tuple[int, int, str]] = PriorityQueue()
        self.pending_tasks: Dict[str, DownloadTask] = {}
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.failed_tasks: Dict[str, DownloadTask] = {}
        self.completed_tasks: Dict[str, DownloadTask] = {}
        self.task_lock = threading.RLock()
        self.running = True
        self.in_flight = 0
        self.throttle = Throttle(config.speed_limit) if config.speed_limit > 0 else None
        self.state_file = Path(config.state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_lock = FileLock(self.state_file.with_suffix(self.state_file.suffix + ".lock"))
        self._sequence_counter = 0

        self.session = self._create_session()  # for non-threaded metadata/search operations only
        self.console = Console() if RICH_AVAILABLE and config.tui else None
        self.progress: Optional[Progress] = None
        self.task_ids: Dict[str, TaskID] = {}

        self.hooks: Dict[str, List[Callable]] = {
            "on_start": [],
            "on_progress": [],
            "on_complete": [],
            "on_error": [],
        }
        self._load_plugins()
        if install_signal_handlers:
            self._install_signal_handlers()
        self._load_state()

    def _install_signal_handlers(self) -> None:
        def handler(signum, frame):
            self.logger.info("Shutdown signal received. Saving state...")
            self.running = False
            with self.task_lock:
                for task in self.active_tasks.values():
                    task.status = TaskStatus.PENDING
                self.pending_tasks.update(self.active_tasks)
                self.active_tasks.clear()
            self._save_state()
            raise SystemExit(130)

        signal.signal(signal.SIGINT, handler)
        signal.signal(signal.SIGTERM, handler)

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry = Retry(
            total=self.config.retries,
            backoff_factor=self.config.retry_backoff,
            status_forcelist=[500, 502, 503, 504],
            allowed_methods=frozenset(["HEAD", "GET"]),
            raise_on_status=False,
        )
        adapter = HTTPAdapter(max_retries=retry, pool_connections=64, pool_maxsize=64)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": self.config.user_agent})
        if self.config.proxy:
            session.proxies = {"http": self.config.proxy, "https": self.config.proxy}
        return session

    def _load_plugins(self) -> None:
        plugin_dir = Path(self.config.plugin_dir)
        if not plugin_dir.exists():
            return
        sys.path.insert(0, str(plugin_dir))
        for py_file in plugin_dir.glob("*.py"):
            try:
                module = __import__(py_file.stem)
                if hasattr(module, "register_hooks"):
                    module.register_hooks(self)
            except Exception as e:
                self.logger.error(f"Failed to load plugin {py_file}: {e}")

    def register_hook(self, event: str, callback: Callable) -> None:
        if event in self.hooks:
            self.hooks[event].append(callback)

    def _trigger_hook(self, event: str, task: DownloadTask, **kwargs) -> None:
        for cb in self.hooks.get(event, []):
            try:
                cb(task, **kwargs)
            except Exception as e:
                self.logger.error(f"Hook error ({event}): {e}")

    # ------------------------------------------------------------------
    # State persistence
    # ------------------------------------------------------------------
    def _next_sequence(self) -> int:
        self._sequence_counter += 1
        return self._sequence_counter

    def _all_tasks_unlocked(self) -> List[DownloadTask]:
        return (
            list(self.pending_tasks.values())
            + list(self.active_tasks.values())
            + list(self.failed_tasks.values())
            + list(self.completed_tasks.values())
        )

    def _index_tasks(self) -> List[DownloadTask]:
        with self.task_lock:
            tasks = self._all_tasks_unlocked()
            tasks.sort(key=lambda t: (t.created_at, t.sequence, t.url))
            return tasks

    def _save_state(self) -> None:
        with self.task_lock:
            state = {
                "version": VERSION,
                "saved_at": time.time(),
                "tasks": [task.to_dict() for task in self._all_tasks_unlocked()],
            }
        with self.state_lock:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp_name = tempfile.mkstemp(prefix=self.state_file.name, suffix=".tmp", dir=str(self.state_file.parent))
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as f:
                    json.dump(state, f, indent=2)
                    f.write("\n")
                    f.flush()
                    os.fsync(f.fileno())
                os.replace(tmp_name, self.state_file)
            finally:
                if os.path.exists(tmp_name):
                    os.unlink(tmp_name)

    def _load_state(self) -> None:
        if not self.state_file.exists():
            return
        try:
            with self.state_lock:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    state = json.load(f)

            loaded: List[DownloadTask] = []
            if isinstance(state, dict) and "tasks" in state:
                for item in state.get("tasks", []):
                    task = DownloadTask.from_dict(item)
                    # A previous crash leaves running tasks active in state; restart them as pending.
                    if task.status == TaskStatus.RUNNING:
                        task.status = TaskStatus.PENDING
                    loaded.append(task)
            else:
                # Backward compatibility with the older pending/active/failed shape.
                for item in state.get("pending", []):
                    loaded.append(DownloadTask.from_dict(item, TaskStatus.PENDING))
                for item in state.get("active", []):
                    task = DownloadTask.from_dict(item, TaskStatus.PENDING)
                    task.status = TaskStatus.PENDING
                    loaded.append(task)
                for item in state.get("failed", []):
                    loaded.append(DownloadTask.from_dict(item, TaskStatus.FAILED))

            with self.task_lock:
                self.pending_tasks.clear()
                self.active_tasks.clear()
                self.failed_tasks.clear()
                self.completed_tasks.clear()
                max_seq = 0
                for task in loaded:
                    if task.sequence <= 0:
                        task.sequence = int(task.created_at * 1000)
                    max_seq = max(max_seq, task.sequence)
                    if task.status == TaskStatus.COMPLETED:
                        self.completed_tasks[task.url] = task
                    elif task.status == TaskStatus.FAILED:
                        self.failed_tasks[task.url] = task
                    else:
                        task.status = TaskStatus.PENDING
                        self.pending_tasks[task.url] = task
                self._sequence_counter = max_seq
                self._rebuild_queue_unlocked()
            self.logger.info(f"Loaded {len(loaded)} task(s) from state")
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")

    def _rebuild_queue_unlocked(self, selected_urls: Optional[Set[str]] = None) -> None:
        self.queue = PriorityQueue()
        for task in self.pending_tasks.values():
            if selected_urls is not None and task.url not in selected_urls:
                continue
            if not task.is_cancelled:
                self.queue.put((task.priority, task.sequence, task.url))

    # ------------------------------------------------------------------
    # Index helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _parse_simple_pattern(pattern: str, max_idx: int) -> Set[int]:
        indices: Set[int] = set()
        for part in pattern.split(","):
            part = part.strip()
            if not part:
                continue
            if "-" in part:
                try:
                    s, e = map(int, part.split("-", 1))
                    if s <= e:
                        indices.update(range(s, e + 1))
                except ValueError:
                    continue
            else:
                try:
                    indices.add(int(part))
                except ValueError:
                    continue
        return {i for i in indices if 1 <= i <= max_idx}

    @classmethod
    def _parse_pattern(cls, pattern: str, max_idx: int) -> Set[int]:
        if "~" in pattern:
            include, exclude = pattern.split("~", 1)
            return cls._parse_simple_pattern(include, max_idx) - cls._parse_simple_pattern(exclude, max_idx)
        return cls._parse_simple_pattern(pattern, max_idx)

    def _resolve_indices(self, patterns: Iterable[str], allowed_statuses: Optional[Set[TaskStatus]] = None) -> Set[int]:
        tasks = self._index_tasks()
        if allowed_statuses:
            eligible = {i + 1 for i, t in enumerate(tasks) if t.status in allowed_statuses}
        else:
            eligible = set(range(1, len(tasks) + 1))
        result: Set[int] = set()
        for pattern in patterns:
            result.update(self._parse_pattern(pattern, len(tasks)))
        return result & eligible

    # ------------------------------------------------------------------
    # Add/remove/move/restart
    # ------------------------------------------------------------------
    def _used_dest_paths_unlocked(self, exclude_url: Optional[str] = None) -> Set[str]:
        return {
            t.dest_path
            for t in self._all_tasks_unlocked()
            if exclude_url is None or t.url != exclude_url
        }

    def _unique_dest_path(self, desired: str, exclude_url: Optional[str] = None) -> str:
        desired = os.path.abspath(os.path.expanduser(desired))
        base, ext = os.path.splitext(desired)
        candidate = desired
        counter = 1
        with self.task_lock:
            used = self._used_dest_paths_unlocked(exclude_url=exclude_url)
        while os.path.exists(candidate) or candidate in used:
            candidate = f"{base}_{counter}{ext}"
            counter += 1
        return candidate

    def add_download(
        self,
        url: str,
        dest_path: Optional[str] = None,
        priority: int = 5,
        expected_checksum: Optional[str] = None,
        checksum_algo: str = "sha256",
        headers: Optional[Dict[str, str]] = None,
    ) -> DownloadTask:
        validate_url(url)
        auto_filename = dest_path is None
        if dest_path is None:
            parsed = urlparse(url)
            filename = safe_filename(os.path.basename(parsed.path)) if parsed.path else "download"
            dest_path = os.path.join(self.config.download_dir, filename or "download")
        else:
            dest_path = os.path.expanduser(dest_path)
            if os.path.isdir(dest_path):
                parsed = urlparse(url)
                filename = safe_filename(os.path.basename(parsed.path)) if parsed.path else "download"
                dest_path = os.path.join(dest_path, filename or "download")

        dest_path = self._unique_dest_path(dest_path)
        Path(dest_path).parent.mkdir(parents=True, exist_ok=True)

        with self.task_lock:
            existing = (
                self.pending_tasks.get(url)
                or self.active_tasks.get(url)
                or self.failed_tasks.get(url)
                or self.completed_tasks.get(url)
            )
            if existing:
                self.logger.warning(f"URL already exists: {url}")
                return existing
            task = DownloadTask(
                url=url,
                dest_path=dest_path,
                priority=priority,
                sequence=self._next_sequence(),
                expected_checksum=expected_checksum,
                checksum_algo=checksum_algo,
                headers=headers or {},
                auto_filename=auto_filename,
            )
            self.pending_tasks[url] = task
            self.queue.put((task.priority, task.sequence, task.url))
        self.logger.info(f"Queued: {url}")
        self._save_state()
        return task

    def remove_download(self, url: str, delete_file: bool = False) -> bool:
        task: Optional[DownloadTask] = None
        with self.task_lock:
            task = self.pending_tasks.pop(url, None)
            task = task or self.active_tasks.pop(url, None)
            task = task or self.failed_tasks.pop(url, None)
            task = task or self.completed_tasks.pop(url, None)
            if task:
                task.cancel()
                self._rebuild_queue_unlocked()
        if not task:
            return False
        if delete_file:
            self._cleanup_files(task)
        self.logger.info(f"Removed: {url}")
        self._save_state()
        return True

    def remove_by_indices(self, patterns: List[str], delete_file: bool = False) -> Tuple[int, List[str]]:
        tasks = self._index_tasks()
        if not patterns:
            indices = set(range(1, len(tasks) + 1))
        else:
            indices = self._resolve_indices(patterns)
        success, errors = 0, []
        for idx in sorted(indices, reverse=True):
            if idx > len(tasks):
                errors.append(f"Index {idx} out of range")
                continue
            if self.remove_download(tasks[idx - 1].url, delete_file=delete_file):
                success += 1
            else:
                errors.append(f"Failed to remove index {idx}")
        return success, errors

    def move_by_indices(self, pattern: str, target_index: int) -> Tuple[int, List[str]]:
        with self.task_lock:
            pending_list = sorted(self.pending_tasks.values(), key=lambda t: (t.priority, t.sequence, t.created_at))
            max_idx = len(pending_list)
            if max_idx == 0:
                return 0, ["No pending tasks to move."]
            indices = self._parse_pattern(pattern, max_idx)
            if not indices:
                return 0, ["No matching pending tasks."]
            selected: List[DownloadTask] = []
            for idx in sorted(indices, reverse=True):
                selected.insert(0, pending_list.pop(idx - 1))
            insert_pos = max(0, min(target_index - 1, len(pending_list)))
            new_order = pending_list[:insert_pos] + selected + pending_list[insert_pos:]
            base_time = time.time()
            for i, task in enumerate(new_order):
                task.priority = i + 1
                task.sequence = self._next_sequence()
                task.created_at = base_time + i * 0.001
            self._rebuild_queue_unlocked()
        self._save_state()
        return len(selected), []

    def restart_by_indices(self, patterns: List[str]) -> Tuple[int, List[str]]:
        tasks = self._index_tasks()
        if not tasks:
            return 0, ["No tasks to restart."]
        indices = {len(tasks)} if not patterns else self._resolve_indices(patterns)
        if not indices:
            return 0, ["No valid indices."]

        success, errors = 0, []
        for idx in sorted(indices, reverse=True):
            task = tasks[idx - 1]
            url = task.url
            dest = task.dest_path
            self._cleanup_files(task)
            with self.task_lock:
                self.pending_tasks.pop(url, None)
                self.active_tasks.pop(url, None)
                self.failed_tasks.pop(url, None)
                self.completed_tasks.pop(url, None)
                task.reset_for_run()
                task.bytes_downloaded = 0
                task.total_size = 0
                task.sequence = self._next_sequence()
                self.pending_tasks[url] = task
                self._rebuild_queue_unlocked()
            success += 1
            self.logger.info(f"Restarted: {url} -> {dest}")
        self._save_state()
        return success, errors

    def _cleanup_files(self, task: DownloadTask) -> None:
        paths = [task.dest_path, task.dest_path + ".part"]
        paths.extend(f"{task.dest_path}.part{i}" for i in range(max(1, int(self.config.segments or 1))))
        # Also remove any stale segment files, even if segments was changed since the failed run.
        paths.extend(str(p) for p in Path(task.dest_path).parent.glob(Path(task.dest_path).name + ".part*"))
        for path in dict.fromkeys(paths):
            try:
                if os.path.exists(path):
                    os.remove(path)
            except Exception as e:
                self.logger.error(f"Cleanup error for {path}: {e}")

    # ------------------------------------------------------------------
    # Running selected tasks
    # ------------------------------------------------------------------
    def run_only_patterns(self, patterns: List[str]) -> int:
        tasks = self._index_tasks()
        if not tasks:
            self.logger.info("No tasks to run.")
            return 0

        if patterns:
            selected_indices: Set[int] = set()
            for pattern in patterns:
                selected_indices.update(self._parse_pattern(pattern, len(tasks)))
        else:
            selected_indices = set(range(1, len(tasks) + 1))

        selected_urls = {tasks[i - 1].url for i in selected_indices if 1 <= i <= len(tasks)}
        activated = 0
        with self.task_lock:
            for task in tasks:
                if task.url not in selected_urls:
                    continue
                if task.status not in {TaskStatus.PENDING, TaskStatus.FAILED, TaskStatus.CANCELLED}:
                    continue
                self.failed_tasks.pop(task.url, None)
                self.completed_tasks.pop(task.url, None)
                task.reset_for_run()
                self.pending_tasks[task.url] = task
                activated += 1
            self._rebuild_queue_unlocked(selected_urls=selected_urls)
        self._save_state()
        self.logger.info(f"Queued {activated} task(s) for this run.")
        return activated

    def start(self) -> None:
        if self.console:
            self._start_tui()
        else:
            self._start_simple()

    def _start_workers(self) -> List[threading.Thread]:
        workers: List[threading.Thread] = []
        count = max(1, int(self.config.max_concurrent))
        for _ in range(count):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            workers.append(t)
        return workers

    def _is_done_for_this_run(self) -> bool:
        with self.task_lock:
            return self.queue.empty() and not self.active_tasks and self.in_flight == 0

    def _start_simple(self) -> None:
        workers = self._start_workers()
        try:
            while self.running:
                line = self.get_status_line()
                sys.stdout.write(f"\r\033[K{line}")
                sys.stdout.flush()
                if self._is_done_for_this_run():
                    break
                time.sleep(0.5)
        finally:
            self.running = False
            for t in workers:
                t.join(timeout=1)
            self._save_state()
            print()

    def _start_tui(self) -> None:
        if not RICH_AVAILABLE:
            self._start_simple()
            return
        self.progress = Progress(
            TextColumn("[bold blue]{task.fields[filename]}", justify="right"),
            BarColumn(bar_width=None),
            "[progress.percentage]{task.percentage:>3.1f}%",
            "•",
            TransferSpeedColumn(),
            "•",
            TimeRemainingColumn(),
            console=self.console,
        )
        layout = Table.grid(expand=True)
        layout.add_row(Panel(self.progress, title="Downloads", border_style="green"))
        workers = self._start_workers()
        try:
            with Live(layout, console=self.console, refresh_per_second=10):
                while self.running:
                    self._update_tui()
                    if self._is_done_for_this_run():
                        break
                    time.sleep(0.1)
        finally:
            self.running = False
            for t in workers:
                t.join(timeout=1)
            self._save_state()

    def _update_tui(self) -> None:
        if not self.progress:
            return
        with self.task_lock:
            for url in list(self.task_ids.keys()):
                if url not in self.active_tasks:
                    try:
                        self.progress.remove_task(self.task_ids.pop(url))
                    except Exception:
                        self.task_ids.pop(url, None)
            for task in self.active_tasks.values():
                fn = os.path.basename(task.dest_path)
                total = task.total_size if task.total_size > 0 else None
                if task.url not in self.task_ids:
                    self.task_ids[task.url] = self.progress.add_task(
                        f"[cyan]{fn}", filename=fn, total=total, completed=task.bytes_downloaded
                    )
                else:
                    self.progress.update(self.task_ids[task.url], completed=task.bytes_downloaded, total=total)

    def _worker(self) -> None:
        while self.running:
            try:
                _, _, url = self.queue.get(timeout=0.5)
            except Empty:
                if self._is_done_for_this_run():
                    return
                continue

            with self.task_lock:
                self.in_flight += 1
                task = self.pending_tasks.pop(url, None)
                if task is None or task.is_cancelled:
                    self.in_flight -= 1
                    self.queue.task_done()
                    continue
                task.status = TaskStatus.RUNNING
                task.update_progress_time()
                self.active_tasks[url] = task

            try:
                self._download_task(task)
            except Exception as e:
                task.status = TaskStatus.FAILED
                task.error = str(e)
                self.logger.error(f"Download failed: {task.url} - {e}")
            finally:
                with self.task_lock:
                    self.active_tasks.pop(url, None)
                    if task.status == TaskStatus.COMPLETED:
                        task.completed_at = time.time()
                        self.completed_tasks[url] = task
                    elif task.status == TaskStatus.FAILED:
                        self.failed_tasks[url] = task
                        self._log_failed_link(task)
                    elif task.status == TaskStatus.CANCELLED:
                        self.pending_tasks[url] = task
                    else:
                        task.status = TaskStatus.PENDING
                        self.pending_tasks[url] = task
                    if self.progress and url in self.task_ids:
                        try:
                            self.progress.remove_task(self.task_ids.pop(url))
                        except Exception:
                            self.task_ids.pop(url, None)
                    self.in_flight -= 1
                self.queue.task_done()
                self._save_state()

    # ------------------------------------------------------------------
    # Download logic
    # ------------------------------------------------------------------
    def _download_task(self, task: DownloadTask) -> None:
        self._trigger_hook("on_start", task)
        try:
            if self.config.segments > 1 and self._supports_range(task.url):
                self._segmented_download(task)
            else:
                self._single_download(task)
            if task.status == TaskStatus.CANCELLED:
                return
            if task.status != TaskStatus.COMPLETED:
                raise RuntimeError(task.error or "Download did not complete")
            if self.config.checksum_verify and task.expected_checksum:
                if not self._verify_checksum(task.dest_path, task.expected_checksum, task.checksum_algo):
                    raise RuntimeError("Checksum mismatch")
            self._trigger_hook("on_complete", task)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            self._trigger_hook("on_error", task, error=e)
            raise

    def _maybe_apply_response_filename(self, task: DownloadTask, headers: Dict[str, str], part_exists: bool = False) -> None:
        if not task.auto_filename or part_exists or os.path.exists(task.dest_path):
            return
        filename = filename_from_content_disposition(headers.get("Content-Disposition"))
        if not filename:
            return
        new_path = os.path.join(os.path.dirname(task.dest_path), filename)
        new_path = self._unique_dest_path(new_path, exclude_url=task.url)
        if new_path != task.dest_path:
            self.logger.info(f"Using filename from Content-Disposition: {new_path}")
            task.dest_path = new_path

    def _supports_range(self, url: str) -> bool:
        session = self._create_session()
        try:
            headers = {"Range": "bytes=0-0"}
            with session.get(url, headers=headers, stream=True, timeout=self.config.timeout) as r:
                if r.status_code != 206:
                    return False
                cr = parse_content_range(r.headers.get("Content-Range"))
                return cr is not None and cr[2] > 0
        except Exception:
            return False
        finally:
            session.close()

    def _single_download(self, task: DownloadTask) -> None:
        session = self._create_session()
        try:
            file_path = task.dest_path
            part_path = file_path + ".part"
            downloaded = os.path.getsize(part_path) if os.path.exists(part_path) else 0
            part_exists = downloaded > 0
            headers = task.headers.copy()
            if downloaded > 0:
                headers["Range"] = f"bytes={downloaded}-"
            task.bytes_downloaded = downloaded
            task.update_progress_time()

            for attempt in range(self.config.retries + 1):
                mode = "ab" if downloaded > 0 else "wb"
                try:
                    with session.get(task.url, stream=True, headers=headers, timeout=self.config.timeout) as r:
                        if r.status_code == 416 and downloaded > 0:
                            # Local part may already equal the remote file. Verify via Content-Range */size if present.
                            cr_total = None
                            m = re.search(r"\*/(\d+)", r.headers.get("Content-Range", ""))
                            if m:
                                cr_total = int(m.group(1))
                            if cr_total is not None and downloaded == cr_total:
                                os.replace(part_path, file_path)
                                task.total_size = cr_total
                                task.bytes_downloaded = cr_total
                                task.status = TaskStatus.COMPLETED
                                return
                        if r.status_code not in (200, 206):
                            r.raise_for_status()

                        if downloaded > 0 and r.status_code == 200:
                            # Server ignored Range. Restart cleanly and reset accounting.
                            downloaded = 0
                            task.bytes_downloaded = 0
                            headers.pop("Range", None)
                            mode = "wb"

                        self._maybe_apply_response_filename(task, r.headers, part_exists=part_exists)
                        file_path = task.dest_path
                        part_path = file_path + ".part"

                        if r.status_code == 206:
                            cr = parse_content_range(r.headers.get("Content-Range"))
                            if cr:
                                task.total_size = cr[2]
                            else:
                                task.total_size = downloaded + int(r.headers.get("Content-Length", 0) or 0)
                        else:
                            task.total_size = int(r.headers.get("Content-Length", 0) or 0)

                        with open(part_path, mode) as f:
                            for chunk in r.iter_content(chunk_size=self.config.chunk_size):
                                if task.is_cancelled:
                                    task.status = TaskStatus.CANCELLED
                                    return
                                if not chunk:
                                    continue
                                if self.throttle:
                                    wait = self.throttle.consume(len(chunk))
                                    if wait > 0:
                                        time.sleep(wait)
                                f.write(chunk)
                                task.bytes_downloaded += len(chunk)
                                task.update_progress_time()
                                self._trigger_hook("on_progress", task)
                                if task.is_stalled(self.config.stall_timeout):
                                    raise RuntimeError(f"Download stalled for {self.config.stall_timeout}s")
                    break
                except (requests.RequestException, OSError, RuntimeError) as e:
                    if attempt == self.config.retries:
                        raise
                    wait = self.config.retry_backoff ** attempt
                    self.logger.warning(f"Retry {attempt + 1}/{self.config.retries} for {task.url} in {wait}s: {e}")
                    time.sleep(wait)
                    downloaded = os.path.getsize(part_path) if os.path.exists(part_path) else 0
                    task.bytes_downloaded = downloaded
                    headers = task.headers.copy()
                    if downloaded > 0:
                        headers["Range"] = f"bytes={downloaded}-"
                    task.update_progress_time()

            os.replace(part_path, file_path)
            if task.total_size and task.bytes_downloaded > task.total_size:
                # This should no longer happen, but keep the state sane if a server reports badly.
                task.bytes_downloaded = os.path.getsize(file_path)
            task.status = TaskStatus.COMPLETED
        finally:
            session.close()

    def _remote_size_for_range_download(self, url: str) -> int:
        session = self._create_session()
        try:
            with session.get(url, headers={"Range": "bytes=0-0"}, stream=True, timeout=self.config.timeout) as r:
                if r.status_code != 206:
                    return 0
                cr = parse_content_range(r.headers.get("Content-Range"))
                return cr[2] if cr else 0
        finally:
            session.close()

    def _segmented_download(self, task: DownloadTask) -> None:
        total_size = self._remote_size_for_range_download(task.url)
        if total_size <= 0:
            self._single_download(task)
            return

        task.total_size = total_size
        num = max(1, min(int(self.config.segments), total_size))
        seg_size = total_size // num
        ranges: List[Tuple[int, int]] = []
        for i in range(num):
            start = i * seg_size
            end = (start + seg_size - 1) if i < num - 1 else total_size - 1
            ranges.append((start, end))

        part_files = [f"{task.dest_path}.part{i}" for i in range(num)]
        jobs: List[Tuple[int, int, int, str, int]] = []
        initial_total = 0
        for idx, (start, end) in enumerate(ranges):
            expected_len = end - start + 1
            path = part_files[idx]
            existing = os.path.getsize(path) if os.path.exists(path) else 0
            if existing > expected_len:
                os.remove(path)
                existing = 0
            if existing == expected_len:
                initial_total += existing
                continue
            if existing > 0:
                initial_total += existing
            jobs.append((idx, start + existing, end, path, existing))
        task.bytes_downloaded = initial_total
        task.update_progress_time()

        with ThreadPoolExecutor(max_workers=num) as ex:
            futures = [
                ex.submit(self._download_segment, task, idx, start, end, path, existing)
                for idx, start, end, path, existing in jobs
            ]
            for fut in as_completed(futures):
                exc = fut.exception()
                if exc:
                    task.status = TaskStatus.FAILED
                    task.error = str(exc)
                    raise exc

        for (start, end), path in zip(ranges, part_files):
            expected_len = end - start + 1
            actual = os.path.getsize(path) if os.path.exists(path) else 0
            if actual != expected_len:
                raise RuntimeError(f"Segment size mismatch for {path}: expected {expected_len}, got {actual}")

        tmp_dest = task.dest_path + ".part"
        with open(tmp_dest, "wb") as out:
            for path in part_files:
                with open(path, "rb") as inf:
                    for chunk in iter(lambda: inf.read(self.config.chunk_size), b""):
                        out.write(chunk)
        os.replace(tmp_dest, task.dest_path)
        for path in part_files:
            try:
                os.remove(path)
            except FileNotFoundError:
                pass
        task.bytes_downloaded = os.path.getsize(task.dest_path)
        task.status = TaskStatus.COMPLETED

    def _download_segment(self, task: DownloadTask, idx: int, start: int, end: int, part_path: str, initial_bytes: int = 0) -> None:
        if start > end:
            return
        session = self._create_session()
        try:
            headers = task.headers.copy()
            headers["Range"] = f"bytes={start}-{end}"
            expected_start = start
            for attempt in range(self.config.retries + 1):
                mode = "ab" if initial_bytes > 0 and os.path.exists(part_path) else "wb"
                try:
                    with session.get(task.url, stream=True, headers=headers, timeout=self.config.timeout) as r:
                        if r.status_code != 206:
                            raise RuntimeError(f"Server did not honor Range request for segment {idx} (status {r.status_code})")
                        cr = parse_content_range(r.headers.get("Content-Range"))
                        if not cr:
                            raise RuntimeError(f"Missing/invalid Content-Range for segment {idx}")
                        cr_start, cr_end, cr_total = cr
                        if cr_start != expected_start or cr_end != end or cr_total != task.total_size:
                            raise RuntimeError(
                                f"Unexpected Content-Range for segment {idx}: {r.headers.get('Content-Range')}"
                            )
                        with open(part_path, mode) as f:
                            for chunk in r.iter_content(chunk_size=self.config.chunk_size):
                                if task.is_cancelled:
                                    task.status = TaskStatus.CANCELLED
                                    return
                                if not chunk:
                                    continue
                                if self.throttle:
                                    wait = self.throttle.consume(len(chunk))
                                    if wait > 0:
                                        time.sleep(wait)
                                f.write(chunk)
                                with self.task_lock:
                                    task.bytes_downloaded += len(chunk)
                                task.update_progress_time()
                                self._trigger_hook("on_progress", task)
                    return
                except Exception as e:
                    if attempt == self.config.retries:
                        raise
                    wait = self.config.retry_backoff ** attempt
                    self.logger.warning(f"Retry {attempt + 1}/{self.config.retries} for segment {idx} in {wait}s: {e}")
                    time.sleep(wait)
                    existing = os.path.getsize(part_path) if os.path.exists(part_path) else 0
                    original_segment_start = int(headers["Range"].split("=")[1].split("-")[0]) - initial_bytes
                    expected_start = original_segment_start + existing
                    if expected_start > end:
                        return
                    initial_bytes = existing
                    headers["Range"] = f"bytes={expected_start}-{end}"
        finally:
            session.close()

    def _verify_checksum(self, path: str, expected: str, algo: str) -> bool:
        try:
            h = hashlib.new(algo)
        except ValueError as e:
            raise ValueError(f"Unsupported checksum algorithm: {algo}") from e
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1024 * 1024), b""):
                h.update(chunk)
        return h.hexdigest().lower() == expected.lower()

    # ------------------------------------------------------------------
    # Failure log, status, export, search
    # ------------------------------------------------------------------
    def _log_failed_link(self, task: DownloadTask) -> None:
        path = Path(self.config.failed_log).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        line = f"{task.url} | {task.dest_path} | {task.error or 'unknown error'}\n"
        try:
            existing = set()
            if path.exists():
                with open(path, "r", encoding="utf-8") as f:
                    existing = set(f.readlines())
            if line not in existing:
                with open(path, "a", encoding="utf-8") as f:
                    f.write(line)
        except Exception as e:
            self.logger.error(f"Could not write failed log: {e}")

    def retry_failed_from_state(self) -> int:
        with self.task_lock:
            failed = list(self.failed_tasks.values())
            for task in failed:
                self.failed_tasks.pop(task.url, None)
                task.reset_for_run()
                task.sequence = self._next_sequence()
                self.pending_tasks[task.url] = task
            self._rebuild_queue_unlocked()
        self._save_state()
        return len(failed)

    def retry_failed_from_log(self) -> int:
        path = Path(self.config.failed_log).expanduser()
        if not path.exists():
            return 0
        added = 0
        with open(path, "r", encoding="utf-8") as f:
            lines = [line.strip() for line in f if line.strip()]
        for line in lines:
            parts = line.split(" | ")
            url = parts[0]
            dest = parts[1] if len(parts) > 1 else None
            try:
                validate_url(url)
                with self.task_lock:
                    task = self.failed_tasks.pop(url, None)
                    if task:
                        task.reset_for_run()
                        task.sequence = self._next_sequence()
                        self.pending_tasks[url] = task
                    else:
                        existing = self.pending_tasks.get(url) or self.active_tasks.get(url) or self.completed_tasks.get(url)
                        if existing:
                            continue
                        task = DownloadTask(
                            url=url,
                            dest_path=self._unique_dest_path(dest or os.path.join(self.config.download_dir, safe_filename(os.path.basename(urlparse(url).path)) or "download")),
                            priority=5,
                            sequence=self._next_sequence(),
                        )
                        self.pending_tasks[url] = task
                    added += 1
                    self._rebuild_queue_unlocked()
            except Exception as e:
                print(f"Failed to re-add {url}: {e}")
        self._save_state()
        return added

    def clear_failure_log(self) -> int:
        path = Path(self.config.failed_log).expanduser()
        if not path.exists():
            return 0
        with open(path, "r", encoding="utf-8") as f:
            count = sum(1 for line in f if line.strip())
        path.unlink()
        return count

    def get_status(self) -> Dict[str, Any]:
        with self.task_lock:
            tasks = self._all_tasks_unlocked()
            return {
                "pending": len(self.pending_tasks),
                "active": len(self.active_tasks),
                "failed": len(self.failed_tasks),
                "completed": len(self.completed_tasks),
                "tasks": [task.to_dict() for task in sorted(tasks, key=lambda t: (t.created_at, t.sequence, t.url))],
            }

    def get_status_line(self) -> str:
        with self.task_lock:
            if self.active_tasks:
                parts = []
                for task in self.active_tasks.values():
                    fn = os.path.basename(task.dest_path)
                    progress = f"{task.bytes_downloaded}/{task.total_size} ({task.progress_percent:.1f}%)" if task.total_size else f"{task.bytes_downloaded} bytes"
                    prefix = "[STALLED] " if task.is_stalled(self.config.stall_timeout) else ""
                    parts.append(f"{prefix}{fn}: {progress}")
                return " | ".join(parts)
            if self.queue.empty():
                return "Done."
            return f"Queued: {self.queue.qsize()} task(s)."

    def export_tasks(self, filepath: str, as_csv: bool = False) -> None:
        tasks = [t for t in self._index_tasks() if t.status != TaskStatus.COMPLETED]
        if not tasks:
            print("No non-completed tasks to export.")
            return
        with open(filepath, "w", encoding="utf-8", newline="") as f:
            if as_csv:
                writer = csv.writer(f)
                writer.writerow(["index", "status", "url", "destination", "bytes_downloaded", "total_size", "priority"])
                for idx, t in enumerate(tasks, 1):
                    writer.writerow([idx, t.status.value, t.url, t.dest_path, t.bytes_downloaded, t.total_size, t.priority])
            else:
                for t in tasks:
                    f.write(t.url + "\n")
        print(f"Exported {len(tasks)} task(s) to {filepath}")

    def search_and_add_links(self, source: str, output_dir: Optional[str] = None, priority: int = 5) -> Tuple[int, List[str]]:
        if source.startswith(("http://", "https://")):
            try:
                resp = self.session.get(source, timeout=15)
                resp.raise_for_status()
                content = resp.text
                base_url = source
            except Exception as e:
                return 0, [f"Failed to fetch URL: {e}"]
        else:
            if not os.path.exists(source):
                return 0, [f"File not found: {source}"]
            try:
                with open(source, "r", encoding="utf-8") as f:
                    content = f.read()
                base_url = None
            except Exception as e:
                return 0, [f"Failed to read file: {e}"]

        raw_links: Set[str] = set()
        try:
            from bs4 import BeautifulSoup  # optional, better than regex when installed

            soup = BeautifulSoup(content, "html.parser")
            for tag, attr in [("a", "href"), ("video", "src"), ("audio", "src"), ("source", "src"), ("img", "src")]:
                for element in soup.find_all(tag):
                    value = element.get(attr)
                    if value:
                        raw_links.add(value)
        except ImportError:
            patterns = [
                r'<a\s+(?:[^>]*?\s)?href=(["\'])(.*?)\1',
                r'<video\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
                r'<audio\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
                r'<source\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
                r'<img\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
            ]
            for pat in patterns:
                for match in re.finditer(pat, content, re.IGNORECASE):
                    raw_links.add(match.group(2))

        absolute_links: Set[str] = set()
        for link in raw_links:
            link = link.strip()
            if not link:
                continue
            if base_url and not link.startswith(("http://", "https://")):
                link = urljoin(base_url, link)
            if link.startswith(("http://", "https://")):
                absolute_links.add(link)

        added, errors = 0, []
        for url in sorted(absolute_links):
            try:
                dest = None
                if output_dir:
                    filename = safe_filename(os.path.basename(urlparse(url).path)) or "download"
                    dest = os.path.join(output_dir, filename)
                task = self.add_download(url, dest_path=dest, priority=priority)
                print(f"Added: {task.url} -> {task.dest_path}")
                added += 1
            except Exception as e:
                errors.append(f"Failed to add {url}: {e}")
        return added, errors

    def check_for_updates(self) -> None:
        if not self.config.update_check:
            return
        try:
            resp = requests.get(self.config.update_url, timeout=5)
            resp.raise_for_status()
            latest = resp.json().get("tag_name")
            if latest and latest != VERSION:
                self.logger.info(f"Update available: {latest} (you have {VERSION})")
        except Exception as e:
            self.logger.debug(f"Update check failed: {e}")


# ----------------------------------------------------------------------
# CLI output helpers
# ----------------------------------------------------------------------
def print_list(manager: DownloadManager, active_only=False, pending_only=False, completed_only=False, failed_only=False, sort_by=None) -> None:
    tasks = manager.get_status()["tasks"]
    if active_only:
        tasks = [t for t in tasks if t["status"] == "running"]
    elif pending_only:
        tasks = [t for t in tasks if t["status"] == "pending"]
    elif completed_only:
        tasks = [t for t in tasks if t["status"] == "completed"]
    elif failed_only:
        tasks = [t for t in tasks if t["status"] == "failed"]

    if sort_by == "name":
        tasks.sort(key=lambda t: os.path.basename(t["dest_path"]).lower())
    elif sort_by == "size":
        tasks.sort(key=lambda t: int(t.get("total_size", 0) or 0))
    elif sort_by == "url":
        tasks.sort(key=lambda t: t["url"])
    else:
        tasks.sort(key=lambda t: (t.get("created_at", 0), t.get("sequence", 0), t["url"]))

    if not tasks:
        print("No downloads found.")
        return

    if RICH_AVAILABLE and manager.console:
        table = Table(title="Downloads", show_lines=True)
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")
        table.add_column("URL", style="white")
        table.add_column("Destination", style="dim")
        table.add_column("Progress", style="yellow")
        for idx, t in enumerate(tasks, 1):
            progress = f"{t['bytes_downloaded']}/{t['total_size']}" if t.get("total_size") else f"{t['bytes_downloaded']} bytes"
            status = t["status"].upper()
            if t["status"] == "running":
                status = f"[bold green]{status}[/bold green]"
            elif t["status"] == "failed":
                status = f"[red]{status}[/red]"
            elif t["status"] == "completed":
                status = f"[blue]{status}[/blue]"
            table.add_row(str(idx), status, t["url"], t["dest_path"], progress)
        manager.console.print(table)
    else:
        for idx, t in enumerate(tasks, 1):
            progress = f"{t['bytes_downloaded']}/{t['total_size']}" if t.get("total_size") else f"{t['bytes_downloaded']} bytes"
            print(f"[{idx}] {t['status'].upper()} | {t['url']} -> {t['dest_path']} ({progress})")


# ----------------------------------------------------------------------
# CLI parser
# ----------------------------------------------------------------------
def create_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Download Manager (Index-Based)")
    parser.add_argument("--version", action="version", version=f"dm {VERSION}")
    sub = parser.add_subparsers(dest="command", required=True)

    add_p = sub.add_parser("add", help="Add one URL")
    add_p.add_argument("url")
    add_p.add_argument("--output-file", "-o", dest="output_file", help="Destination file path")
    add_p.add_argument("--priority", "-p", type=int, default=5)
    add_p.add_argument("--checksum")
    add_p.add_argument("--algo", default="sha256")

    al = sub.add_parser("add-list", help="Add URLs from a text file")
    al.add_argument("file")
    al.add_argument("--output-dir", "-o")
    al.add_argument("--priority", "-p", type=int, default=5)

    rm = sub.add_parser("remove", help="Remove downloads by index pattern; default removes all after confirmation")
    rm.add_argument("patterns", nargs="*")
    rm.add_argument("--delete-file", action="store_true")

    mv = sub.add_parser("move", help="Move pending tasks to a new position among pending tasks")
    mv.add_argument("pattern")
    mv.add_argument("target_index", type=int)

    restart = sub.add_parser("restart", help="Restart selected downloads; default restarts the latest task")
    restart.add_argument("patterns", nargs="*")

    se = sub.add_parser("search", help="Search a webpage or HTML file for links and add them")
    se.add_argument("source")
    se.add_argument("--output-dir", "-o")
    se.add_argument("--priority", "-p", type=int, default=5)

    exp = sub.add_parser("export", help="Export all non-completed tasks to a file")
    exp.add_argument("file")
    exp.add_argument("--csv", action="store_true")

    ls = sub.add_parser("list", help="List downloads")
    ls.add_argument("--active", action="store_true")
    ls.add_argument("--pending", action="store_true")
    ls.add_argument("--completed", action="store_true")
    ls.add_argument("--failed", action="store_true")
    ls.add_argument("--sort", choices=["name", "size", "url"], default=None)

    fail = sub.add_parser("failures", help="Show, retry, or clear failed links")
    fail.add_argument("--retry", action="store_true", help="Move failed links back to pending")
    fail.add_argument("--clear", action="store_true", help="Clear the failure log")

    sub.add_parser("status", help="Show counts")

    run = sub.add_parser("run", help="Download selected pending/failed tasks, then exit")
    run.add_argument("patterns", nargs="*")
    run.add_argument("--config", "-c")
    run.add_argument("--download-dir", "-d")
    run.add_argument("--output", "-o", help="Backward-compatible alias for --download-dir")
    run.add_argument("--max-concurrent", type=int)
    run.add_argument("--speed-limit", type=int)
    run.add_argument("--segments", type=int)
    run.add_argument("--no-tui", action="store_true")

    return parser


def load_config(args: argparse.Namespace, cfg_path: Optional[str] = None) -> Config:
    if cfg_path is None:
        default_cfg = os.path.expanduser("~/.config/dm/config.yaml")
        if os.path.exists(default_cfg):
            cfg_path = default_cfg
    config = Config(cfg_path)
    config.update_from_args(args)
    return config


# ----------------------------------------------------------------------
# CLI entry point
# ----------------------------------------------------------------------
def main() -> None:
    parser = create_parser()
    args = parser.parse_args()

    config = load_config(args, getattr(args, "config", None))
    logger = setup_logging(config)
    manager = DownloadManager(config, logger)

    try:
        if args.command == "add":
            task = manager.add_download(
                args.url,
                dest_path=args.output_file,
                priority=args.priority,
                expected_checksum=args.checksum,
                checksum_algo=args.algo,
            )
            print(f"Added: {task.url} -> {task.dest_path}")

        elif args.command == "add-list":
            if not os.path.exists(args.file):
                print(f"Error: File not found: {args.file}", file=sys.stderr)
                raise SystemExit(1)
            added = skipped = 0
            with open(args.file, "r", encoding="utf-8") as f:
                for line_num, line in enumerate(f, 1):
                    url = line.strip()
                    if not url or url.startswith("#"):
                        continue
                    try:
                        validate_url(url)
                        dest = None
                        if args.output_dir:
                            filename = safe_filename(os.path.basename(urlparse(url).path)) or "download"
                            dest = os.path.join(args.output_dir, filename)
                        task = manager.add_download(url, dest_path=dest, priority=args.priority)
                        print(f"Added: {task.url} -> {task.dest_path}")
                        added += 1
                    except Exception as e:
                        print(f"Warning: Line {line_num} skipped: {url} ({e})")
                        skipped += 1
            print(f"\nBatch add complete. Added: {added}, Skipped: {skipped}")

        elif args.command == "remove":
            if not args.patterns:
                total = len(manager._index_tasks())
                if total == 0:
                    print("No downloads to remove.")
                    return
                if not confirm(f"Do you want to remove all links (total: {total})?"):
                    print("Operation cancelled.")
                    return
            succ, errs = manager.remove_by_indices(args.patterns, delete_file=args.delete_file)
            print(f"Removed {succ} download(s).")
            for e in errs:
                print(f"  {e}")

        elif args.command == "move":
            succ, errs = manager.move_by_indices(args.pattern, args.target_index)
            print(f"Moved {succ} pending task(s) to position {args.target_index}.")
            for e in errs:
                print(f"  {e}")

        elif args.command == "restart":
            succ, errs = manager.restart_by_indices(args.patterns)
            print(f"Restarted {succ} download(s).")
            for e in errs:
                print(f"  {e}")

        elif args.command == "search":
            added, errs = manager.search_and_add_links(args.source, args.output_dir, args.priority)
            print(f"\nAdded {added} link(s).")
            for e in errs:
                print(f"  {e}")

        elif args.command == "export":
            manager.export_tasks(args.file, as_csv=args.csv)

        elif args.command == "list":
            print_list(
                manager,
                active_only=args.active,
                pending_only=args.pending,
                completed_only=args.completed,
                failed_only=args.failed,
                sort_by=args.sort,
            )

        elif args.command == "failures":
            failed_log = Path(config.failed_log).expanduser()
            if args.clear:
                count = manager.clear_failure_log()
                print(f"Cleared failure log ({count} entries).")
            elif args.retry:
                count_state = manager.retry_failed_from_state()
                count_log = manager.retry_failed_from_log()
                if failed_log.exists():
                    failed_log.unlink()
                print(f"Re-added {count_state + count_log} failed link(s) as pending.")
            else:
                if not failed_log.exists():
                    print("No failure log found.")
                    return
                with open(failed_log, "r", encoding="utf-8") as f:
                    lines = [line.strip() for line in f if line.strip()]
                if not lines:
                    print("No failed links.")
                    return
                print("Failed links (use --retry to add them back):")
                for i, line in enumerate(lines, 1):
                    print(f"{i}. {line}")

        elif args.command == "status":
            st = manager.get_status()
            print(f"Active: {st['active']}, Pending: {st['pending']}, Failed: {st['failed']}, Completed: {st['completed']}")

        elif args.command == "run":
            manager.check_for_updates()
            activated = manager.run_only_patterns(args.patterns)
            if activated == 0:
                print("No pending/failed tasks selected.")
                return
            manager.start()

    finally:
        manager._save_state()


if __name__ == "__main__":
    main()
