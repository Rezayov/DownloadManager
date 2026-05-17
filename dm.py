#!/usr/bin/env python3
"""
Self‑Configurable Download Manager with CLI Control (Index‑Based)
================================================================

Features (final):
- Add, remove, pause, resume, move, restart downloads using indexes (1‑based)
- Failed tasks are logged to a file and kept in the list
- Pause/resume/remove without pattern → all tasks (confirmation for remove)
- Move pending tasks to a new position among pending tasks
- Restart selected tasks (delete partial files and start over)
- Run only selected tasks via index pattern (`dm run 1-5`)
- Export the task list to a file (text or CSV)
- Improved search: extracts links from <a>, <video>, <audio>, <source>, <img>
- Automatic filename collision avoidance
- Concurrent downloads with priority queue, resumable, checksums, etc.
- List sorting by name/size/URL (optional, default is creation order)
- Timeout and stall detection (stalled downloads automatically fail)

Usage:
    dm add <url> [--output PATH] [--priority N] [--checksum HASH]
    dm add-list <file.txt> [--output-dir DIR] [--priority N]
    dm pause [pattern ...]
    dm resume [pattern ...]
    dm remove [--delete-file] [pattern ...]
    dm move <pattern> <target-index>
    dm restart [pattern ...]
    dm search <url-or-file> [--output-dir DIR] [--priority N]
    dm export <file> [--csv]
    dm list [--active] [--pending] [--completed] [--sort name|size|url]
    dm failures [--retry] [--clear]
    dm status
    dm run [pattern ...] [--config CONFIG] [--max-concurrent N]
"""

import os, sys, time, json, logging, threading, signal, hashlib, argparse, re
from queue import PriorityQueue, Empty
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Callable, Set, Tuple
from pathlib import Path
from urllib.parse import urlparse, urljoin
from concurrent.futures import ThreadPoolExecutor, as_completed
from enum import Enum

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

try:
    import yaml
except ImportError:
    yaml = None

try:
    from rich.console import Console
    from rich.table import Table
    from rich.progress import (
        Progress,
        BarColumn,
        TextColumn,
        TimeRemainingColumn,
        TransferSpeedColumn,
        TaskID,
    )
    from rich.live import Live
    from rich.panel import Panel

    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    Console = None

# ----------------------------------------------------------------------
# Configuration Management
# ----------------------------------------------------------------------
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
    "user_agent": "DM/2.0",
    "proxy": None,
    "checksum_verify": True,
    "segments": 1,
    "throttle_check_interval": 0.1,
    "plugin_dir": "~/Downloads/Manager/plugins",
    "update_check": True,
    "update_url": "https://api.github.com/repos/yourname/dm/releases/latest",
    "tui": True,
}


class Config:
    def __init__(self, config_path=None):
        self.data = DEFAULT_CONFIG.copy()
        self.config_path = config_path
        self._load_from_file()
        self._apply_env_overrides()
        self._expand_paths()

    def _load_from_file(self):
        if self.config_path and os.path.exists(self.config_path):
            with open(self.config_path, "r") as f:
                if self.config_path.endswith((".yaml", ".yml")):
                    if yaml is None:
                        raise ImportError("PyYAML required for YAML config")
                    self.data.update(yaml.safe_load(f))
                else:
                    self.data.update(json.load(f))

    def _apply_env_overrides(self):
        mapping = {
            "DM_DOWNLOAD_DIR": "download_dir",
            "DM_LOG_DIR": "log_dir",
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
        for env, key in mapping.items():
            if env in os.environ:
                val = os.environ[env]
                if key in (
                    "max_concurrent",
                    "chunk_size",
                    "retries",
                    "speed_limit",
                    "segments",
                    "timeout",
                    "stall_timeout",
                ):
                    val = int(val)
                self.data[key] = val

    def _expand_paths(self):
        for key in (
            "download_dir",
            "log_dir",
            "state_file",
            "plugin_dir",
            "failed_log",
        ):
            self.data[key] = os.path.expanduser(self.data[key])

    def __getattr__(self, name):
        if name in self.data:
            return self.data[name]
        raise AttributeError(f"Config has no attribute '{name}'")

    def update_from_args(self, args):
        if hasattr(args, "output") and args.output:
            self.data["download_dir"] = args.output
        if hasattr(args, "max_concurrent") and args.max_concurrent:
            self.data["max_concurrent"] = args.max_concurrent
        if hasattr(args, "speed_limit") and args.speed_limit is not None:
            self.data["speed_limit"] = args.speed_limit
        if hasattr(args, "segments") and args.segments:
            self.data["segments"] = args.segments
        if hasattr(args, "no_tui") and args.no_tui:
            self.data["tui"] = False


# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------
def setup_logging(config):
    log_dir = Path(config.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "dm.log"
    logger = logging.getLogger("dm")
    logger.setLevel(logging.DEBUG)

    fh = logging.FileHandler(log_file)
    fh.setLevel(logging.DEBUG)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setLevel(logging.WARNING)
    ch.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
    logger.addHandler(ch)

    return logger


# ----------------------------------------------------------------------
# Task & State
# ----------------------------------------------------------------------
class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(order=True)
class DownloadTask:
    priority: int
    url: str = field(compare=False)
    dest_path: str = field(compare=False)
    expected_checksum: Optional[str] = field(default=None, compare=False)
    checksum_algo: str = field(default="sha256", compare=False)
    headers: Dict[str, str] = field(default_factory=dict, compare=False)

    _pause_event: threading.Event = field(
        default_factory=threading.Event, compare=False, init=False
    )
    _cancel_event: threading.Event = field(
        default_factory=threading.Event, compare=False, init=False
    )
    bytes_downloaded: int = field(default=0, compare=False, init=False)
    total_size: int = field(default=0, compare=False, init=False)
    status: TaskStatus = field(default=TaskStatus.PENDING, compare=False, init=False)
    error: Optional[str] = field(default=None, compare=False, init=False)
    segments_completed: Dict[int, int] = field(
        default_factory=dict, compare=False, init=False
    )
    created_at: float = field(default_factory=time.time, compare=False, init=False)
    completed_at: Optional[float] = field(default=None, compare=False, init=False)
    last_progress_time: float = field(default_factory=time.time, init=False)

    def pause(self):
        self._pause_event.set()
        self.status = TaskStatus.PAUSED

    def resume(self):
        self._pause_event.clear()
        if self.status == TaskStatus.PAUSED:
            self.status = TaskStatus.RUNNING

    def cancel(self):
        self._cancel_event.set()
        self._pause_event.set()
        self.status = TaskStatus.CANCELLED

    @property
    def is_paused(self):
        return self._pause_event.is_set()

    @property
    def is_cancelled(self):
        return self._cancel_event.is_set()

    @property
    def progress_percent(self):
        if self.total_size > 0:
            return (self.bytes_downloaded / self.total_size) * 100
        return 0.0

    def update_progress_time(self):
        self.last_progress_time = time.time()

    def is_stalled(self, stall_timeout):
        return (time.time() - self.last_progress_time) > stall_timeout

    def to_dict(self):
        return {
            "url": self.url,
            "dest_path": self.dest_path,
            "priority": self.priority,
            "bytes_downloaded": self.bytes_downloaded,
            "total_size": self.total_size,
            "status": self.status.value,
            "error": self.error,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
        }


# ----------------------------------------------------------------------
# Throttle
# ----------------------------------------------------------------------
class Throttle:
    def __init__(self, rate_bps):
        self.rate = rate_bps
        self.tokens = 0.0
        self.last_time = time.monotonic()
        self.lock = threading.Lock()

    def consume(self, bytes_count):
        if self.rate <= 0:
            return 0.0
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last_time
            self.tokens += elapsed * self.rate
            self.tokens = min(self.tokens, self.rate)
            self.last_time = now
            if bytes_count <= self.tokens:
                self.tokens -= bytes_count
                return 0.0
            else:
                deficit = bytes_count - self.tokens
                wait = deficit / self.rate
                self.tokens = 0.0
                return wait


# ----------------------------------------------------------------------
# Download Manager Core
# ----------------------------------------------------------------------
class DownloadManager:
    def __init__(self, config, logger):
        self.config = config
        self.logger = logger
        self.queue: PriorityQueue = PriorityQueue()
        self.pending_tasks: Dict[str, DownloadTask] = {}
        self.active_tasks: Dict[str, DownloadTask] = {}
        self.failed_tasks: Dict[str, DownloadTask] = {}
        self.completed_tasks: List[DownloadTask] = []
        self.task_lock = threading.RLock()
        self.executor = ThreadPoolExecutor(max_workers=config.max_concurrent * 2)
        self.running = True
        self.throttle = Throttle(config.speed_limit) if config.speed_limit > 0 else None
        self.session = self._create_session()
        self.state_file = Path(config.state_file)
        self.state_file.parent.mkdir(parents=True, exist_ok=True)

        # Concurrency control: at most max_concurrent active downloads
        self.active_semaphore = threading.Semaphore(config.max_concurrent)

        self.console = Console() if RICH_AVAILABLE and config.tui else None
        self.progress = None
        self.task_ids: Dict[str, TaskID] = {}
        self.live: Optional[Live] = None

        self.hooks: Dict[str, List[Callable]] = {
            "on_start": [],
            "on_progress": [],
            "on_complete": [],
            "on_error": [],
        }
        self._load_plugins()

        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)

        self._load_state()

    def _create_session(self):
        session = requests.Session()
        retry = Retry(
            total=self.config.retries,
            backoff_factor=self.config.retry_backoff,
            status_forcelist=[500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        session.headers.update({"User-Agent": self.config.user_agent})
        if self.config.proxy:
            session.proxies = {"http": self.config.proxy, "https": self.config.proxy}
        return session

    def _load_plugins(self):
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

    def register_hook(self, event, callback):
        if event in self.hooks:
            self.hooks[event].append(callback)

    def _trigger_hook(self, event, task, **kwargs):
        for cb in self.hooks[event]:
            try:
                cb(task, **kwargs)
            except Exception as e:
                self.logger.error(f"Hook error ({event}): {e}")

    # ------------------------------------------------------------------
    # Failure logging
    # ------------------------------------------------------------------
    def _log_failed_link(self, task):
        failed_log_path = Path(self.config.failed_log).expanduser()
        failed_log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(failed_log_path, "a", encoding="utf-8") as f:
            f.write(f"{task.url} | {task.dest_path} | {task.error}\n")
        self.logger.info(f"Logged failed link: {task.url}")

    # ------------------------------------------------------------------
    # Index Helpers
    # ------------------------------------------------------------------
    def _get_sorted_task_list(self):
        with self.task_lock:
            tasks = (
                list(self.pending_tasks.values())
                + list(self.active_tasks.values())
                + list(self.failed_tasks.values())
            )
            tasks.sort(key=lambda t: t.created_at)
        return tasks

    @staticmethod
    def _parse_pattern(pattern, max_idx):
        result = set()
        if "~" in pattern:
            inc, exc = pattern.split("~", 1)
            inc_set = DownloadManager._parse_simple_pattern(inc, max_idx)
            exc_set = DownloadManager._parse_simple_pattern(exc, max_idx)
            result = inc_set - exc_set
        else:
            result = DownloadManager._parse_simple_pattern(pattern, max_idx)
        return {i for i in result if 1 <= i <= max_idx}

    @staticmethod
    def _parse_simple_pattern(pattern, max_idx):
        indices = set()
        for part in pattern.split(","):
            part = part.strip()
            if "-" in part:
                try:
                    s, e = map(int, part.split("-"))
                    if s <= e:
                        indices.update(range(s, e + 1))
                except ValueError:
                    pass
            else:
                try:
                    indices.add(int(part))
                except ValueError:
                    pass
        return indices

    def _resolve_indices(self, patterns, allowed_statuses=None):
        tasks = self._get_sorted_task_list()
        if allowed_statuses:
            eligible = {
                i + 1 for i, t in enumerate(tasks) if t.status in allowed_statuses
            }
        else:
            eligible = set(range(1, len(tasks) + 1))
        all_indices = set()
        for pat in patterns:
            all_indices.update(self._parse_pattern(pat, len(tasks)))
        return all_indices & eligible

    # ------------------------------------------------------------------
    # State Persistence
    # ------------------------------------------------------------------
    def _save_state(self):
        state = {"pending": [], "active": [], "failed": []}
        with self.task_lock:
            for t in self.pending_tasks.values():
                state["pending"].append(t.to_dict())
            for t in self.active_tasks.values():
                state["active"].append(t.to_dict())
            for t in self.failed_tasks.values():
                state["failed"].append(t.to_dict())
        with open(self.state_file, "w") as f:
            json.dump(state, f, indent=2)

    def _load_state(self):
        if not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r") as f:
                state = json.load(f)
            for item in state.get("pending", []):
                task = DownloadTask(
                    priority=item["priority"],
                    url=item["url"],
                    dest_path=item["dest_path"],
                )
                task.bytes_downloaded = item["bytes_downloaded"]
                task.total_size = item["total_size"]
                task.status = TaskStatus(item["status"])
                with self.task_lock:
                    self.pending_tasks[task.url] = task
                    self.queue.put(task)
            # FIXED: previously active (paused) tasks go to pending queue
            for item in state.get("active", []):
                task = DownloadTask(
                    priority=item["priority"],
                    url=item["url"],
                    dest_path=item["dest_path"],
                )
                task.bytes_downloaded = item["bytes_downloaded"]
                task.total_size = item["total_size"]
                task.status = TaskStatus.PAUSED
                with self.task_lock:
                    self.pending_tasks[task.url] = task
                    self.queue.put(task)
            for item in state.get("failed", []):
                task = DownloadTask(
                    priority=item["priority"],
                    url=item["url"],
                    dest_path=item["dest_path"],
                )
                task.bytes_downloaded = item["bytes_downloaded"]
                task.total_size = item["total_size"]
                task.status = TaskStatus.FAILED
                task.error = item.get("error")
                with self.task_lock:
                    self.failed_tasks[task.url] = task
            self.logger.info(
                f"Loaded {sum(len(state[k]) for k in state)} tasks from state"
            )
        except Exception as e:
            self.logger.error(f"Failed to load state: {e}")

    def _signal_handler(self, signum, frame):
        self.logger.info("Shutdown signal received. Saving state...")
        self.running = False
        self._save_state()
        self.executor.shutdown(wait=False)
        sys.exit(0)

    # ------------------------------------------------------------------
    # Adding downloads (with collision avoidance)
    # ------------------------------------------------------------------
    def add_download(
        self,
        url,
        dest_path=None,
        priority=5,
        expected_checksum=None,
        checksum_algo="sha256",
        headers=None,
    ):
        if not dest_path:
            parsed = urlparse(url)
            filename = os.path.basename(parsed.path) or "download"
            dest_path = os.path.join(self.config.download_dir, filename)
        else:
            dest_path = os.path.expanduser(dest_path)

        os.makedirs(os.path.dirname(dest_path), exist_ok=True)

        base, ext = os.path.splitext(dest_path)
        counter = 1
        candidate = dest_path
        with self.task_lock:
            used = {
                t.dest_path
                for t in list(self.pending_tasks.values())
                + list(self.active_tasks.values())
                + list(self.failed_tasks.values())
            }
        while os.path.exists(candidate) or candidate in used:
            candidate = f"{base}_{counter}{ext}"
            counter += 1
        dest_path = candidate

        task = DownloadTask(
            priority=priority,
            url=url,
            dest_path=dest_path,
            expected_checksum=expected_checksum,
            checksum_algo=checksum_algo,
            headers=headers or {},
        )
        with self.task_lock:
            if (
                url in self.pending_tasks
                or url in self.active_tasks
                or url in self.failed_tasks
            ):
                self.logger.warning(f"URL already in queue: {url}")
                return (
                    self.pending_tasks.get(url)
                    or self.active_tasks.get(url)
                    or self.failed_tasks[url]
                )
            self.pending_tasks[url] = task
            self.queue.put(task)
        self.logger.info(f"Queued: {url}")
        self._save_state()
        return task

    # ------------------------------------------------------------------
    # Remove / Pause / Resume (single URL)
    # ------------------------------------------------------------------
    def remove_download(self, url, delete_file=False):
        with self.task_lock:
            for d in (self.pending_tasks, self.active_tasks, self.failed_tasks):
                task = d.pop(url, None)
                if task:
                    task.cancel()
                    self.logger.info(f"Removed: {url}")
                    if delete_file:
                        self._cleanup_files(task)
                    self._save_state()
                    return True
        return False

    def _cleanup_files(self, task):
        try:
            for p in [task.dest_path, task.dest_path + ".part"]:
                if os.path.exists(p):
                    os.remove(p)
            i = 0
            while True:
                seg = f"{task.dest_path}.part{i}"
                if os.path.exists(seg):
                    os.remove(seg)
                    i += 1
                else:
                    break
        except Exception as e:
            self.logger.error(f"Cleanup error: {e}")

    def pause_download(self, url):
        with self.task_lock:
            task = self.active_tasks.get(url) or self.pending_tasks.get(url)
            if task:
                task.pause()
                self.logger.info(f"Paused: {url}")
                self._save_state()
                return True
        return False

    def resume_download(self, url):
        with self.task_lock:
            task = (
                self.active_tasks.get(url)
                or self.pending_tasks.get(url)
                or self.failed_tasks.get(url)
            )
            if not task:
                return False
            if task.status == TaskStatus.PAUSED:
                # FIXED: if task is still in active_tasks, move it to pending queue
                if url in self.active_tasks:
                    del self.active_tasks[url]
                    self.pending_tasks[url] = task
                    self.queue.put(task)
                task.resume()
                self.logger.info(f"Resumed: {url}")
                self._save_state()
                return True
            elif task.status == TaskStatus.FAILED:
                task.status = TaskStatus.PENDING
                task.error = None
                del self.failed_tasks[url]
                self.pending_tasks[url] = task
                self.queue.put(task)
                self.logger.info(f"Resumed failed task: {url}")
                self._save_state()
                return True
        return False

    def get_status(self):
        with self.task_lock:
            all_tasks = (
                list(self.pending_tasks.values())
                + list(self.active_tasks.values())
                + list(self.failed_tasks.values())
            )
            return {
                "pending": len(self.pending_tasks),
                "active": len(self.active_tasks),
                "failed": len(self.failed_tasks),
                "completed": len(self.completed_tasks),
                "tasks": [t.to_dict() for t in all_tasks],
            }

    # ------------------------------------------------------------------
    # Index‑based commands
    # ------------------------------------------------------------------
    def pause_by_indices(self, patterns):
        if not patterns:
            indices = set(range(1, len(self._get_sorted_task_list()) + 1))
        else:
            indices = self._resolve_indices(patterns)
        tasks = self._get_sorted_task_list()
        success, errors = 0, []
        for idx in sorted(indices):
            if idx > len(tasks):
                errors.append(f"Index {idx} out of range")
                continue
            task = tasks[idx - 1]
            if self.pause_download(task.url):
                success += 1
            else:
                errors.append(f"Failed to pause {task.url} (index {idx})")
        return success, errors

    def resume_by_indices(self, patterns):
        if not patterns:
            tasks = self._get_sorted_task_list()
            indices = {
                i + 1
                for i, t in enumerate(tasks)
                if t.status in (TaskStatus.PAUSED, TaskStatus.FAILED)
            }
        else:
            indices = self._resolve_indices(
                patterns, allowed_statuses={TaskStatus.PAUSED, TaskStatus.FAILED}
            )
        tasks = self._get_sorted_task_list()
        success, errors = 0, []
        for idx in sorted(indices):
            if idx > len(tasks):
                errors.append(f"Index {idx} out of range")
                continue
            task = tasks[idx - 1]
            if self.resume_download(task.url):
                success += 1
            else:
                errors.append(f"Failed to resume {task.url} (index {idx})")
        return success, errors

    def remove_by_indices(self, patterns, delete_file=False):
        if not patterns:
            indices = set(range(1, len(self._get_sorted_task_list()) + 1))
        else:
            indices = self._resolve_indices(patterns)
        tasks = self._get_sorted_task_list()
        success, errors = 0, []
        for idx in sorted(indices, reverse=True):
            if idx > len(tasks):
                errors.append(f"Index {idx} out of range")
                continue
            task = tasks[idx - 1]
            if self.remove_download(task.url, delete_file):
                success += 1
            else:
                errors.append(f"Failed to remove {task.url} (index {idx})")
        return success, errors

    def move_by_indices(self, patterns, target_index):
        """Move selected PENDING tasks to a new position among pending tasks."""
        with self.task_lock:
            pending_list = sorted(
                self.pending_tasks.values(), key=lambda t: t.created_at
            )
            total_pending = len(pending_list)
            if total_pending == 0:
                return 0, ["No pending tasks to move."]

            max_idx = total_pending
            indices = (
                self._parse_pattern(patterns, max_idx)
                if patterns
                else set(range(1, max_idx + 1))
            )
            indices = {i for i in indices if 1 <= i <= max_idx}
            if not indices:
                return 0, ["No matching pending tasks."]

            selected = []
            for idx in sorted(indices, reverse=True):
                task = pending_list.pop(idx - 1)
                selected.insert(0, task)

            insert_pos = target_index - 1
            insert_pos = max(0, min(insert_pos, len(pending_list)))

            new_order = pending_list[:insert_pos] + selected + pending_list[insert_pos:]

            self.queue = PriorityQueue()
            self.pending_tasks.clear()
            base_time = time.time()
            for i, t in enumerate(new_order):
                t.priority = i + 1
                t.created_at = base_time + i * 0.001
                self.pending_tasks[t.url] = t
                self.queue.put(t)

            self._save_state()
            return len(selected), []

    # ------------------------------------------------------------------
    # Restart command: delete partial files and re-add task
    # ------------------------------------------------------------------
    def restart_by_indices(self, patterns):
        """Delete all partial files for selected tasks, remove them, and add them again."""
        tasks = self._get_sorted_task_list()
        total = len(tasks)
        if total == 0:
            return 0, ["No tasks to restart."]

        if not patterns:
            # Default: last link (most recent)
            indices = {total}
        else:
            indices = self._resolve_indices(patterns)

        indices = {i for i in indices if 1 <= i <= total}
        if not indices:
            return 0, ["No valid indices."]

        success = 0
        errors = []
        # We restart in reverse order so that index shifting doesn't affect later tasks
        for idx in sorted(indices, reverse=True):
            task = tasks[idx - 1]
            url = task.url
            dest = task.dest_path
            # Delete any partial files
            try:
                if os.path.exists(dest):
                    os.remove(dest)
                part = dest + ".part"
                if os.path.exists(part):
                    os.remove(part)
                i = 0
                while True:
                    seg = f"{dest}.part{i}"
                    if os.path.exists(seg):
                        os.remove(seg)
                        i += 1
                    else:
                        break
            except Exception as e:
                errors.append(f"Failed to delete files for {url}: {e}")
                continue

            # Remove the task from all dictionaries
            with self.task_lock:
                self.pending_tasks.pop(url, None)
                self.active_tasks.pop(url, None)
                self.failed_tasks.pop(url, None)
                # Cancel the old task
                task.cancel()
            # Now re-add the download with the same destination
            try:
                new_task = self.add_download(
                    url,
                    dest_path=dest,
                    priority=task.priority,
                    expected_checksum=task.expected_checksum,
                    checksum_algo=task.checksum_algo,
                    headers=task.headers,
                )
                if new_task:
                    success += 1
                    self.logger.info(f"Restarted: {url}")
                else:
                    errors.append(f"Failed to re-add {url}")
            except Exception as e:
                errors.append(f"Failed to re-add {url}: {e}")
        return success, errors

    # ------------------------------------------------------------------
    # Run only selected pattern(s)
    # ------------------------------------------------------------------
    def run_only_patterns(self, patterns):
        """Pause all tasks, then resume only those matching patterns (if they are paused or failed)."""
        tasks = self._get_sorted_task_list()
        for task in tasks:
            if task.status in (TaskStatus.PENDING, TaskStatus.RUNNING):
                self.pause_download(task.url)
        if patterns:
            succ, errs = self.resume_by_indices(patterns)
            if errs:
                for e in errs:
                    self.logger.warning(e)
            self.logger.info(f"Activated {succ} task(s) for run")
        else:
            self.resume_by_indices([])
        time.sleep(0.1)

    # ------------------------------------------------------------------
    # Export task list to a file
    # ------------------------------------------------------------------
    def export_tasks(self, filepath, as_csv=False):
        tasks = self._get_sorted_task_list()
        if not tasks:
            print("No tasks to export.")
            return
        try:
            with open(filepath, "w", encoding="utf-8") as f:
                if as_csv:
                    f.write("index,status,url,destination,size_downloaded,total_size\n")
                    for idx, t in enumerate(tasks, 1):
                        f.write(
                            f"{idx},{t.status.value},{t.url},{t.dest_path},{t.bytes_downloaded},{t.total_size}\n"
                        )
                else:
                    for t in tasks:
                        f.write(t.url + "\n")
            print(f"Exported {len(tasks)} task(s) to {filepath}")
        except Exception as e:
            print(f"Export failed: {e}")

    # ------------------------------------------------------------------
    # Search & add links (improved)
    # ------------------------------------------------------------------
    def search_and_add_links(self, source, output_dir=None, priority=5):
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

        patterns = [
            r'<a\s+(?:[^>]*?\s)?href=(["\'])(.*?)\1',
            r'<video\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
            r'<audio\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
            r'<source\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
            r'<img\s+(?:[^>]*?\s)?src=(["\'])(.*?)\1',
        ]
        raw_links = set()
        for pat in patterns:
            for m in re.finditer(pat, content, re.IGNORECASE):
                raw_links.add(m.group(2))

        absolute_links = set()
        for link in raw_links:
            link = link.strip()
            if not link:
                continue
            if base_url and not link.startswith(("http://", "https://")):
                try:
                    link = urljoin(base_url, link)
                except Exception:
                    continue
            if link.startswith(("http://", "https://")):
                absolute_links.add(link)

        added, errors = 0, []
        for url in sorted(absolute_links):
            try:
                dest = None
                if output_dir:
                    parsed = urlparse(url)
                    filename = os.path.basename(parsed.path) or "download"
                    dest = os.path.join(output_dir, filename)
                task = self.add_download(url, dest_path=dest, priority=priority)
                print(f"Added: {task.url} -> {task.dest_path}")
                added += 1
            except Exception as e:
                errors.append(f"Failed to add {url}: {e}")
        return added, errors

    # ------------------------------------------------------------------
    # Status line for simple run mode (shows active + stalled info)
    # ------------------------------------------------------------------
    def get_status_line(self):
        with self.task_lock:
            if not self.active_tasks and not self.failed_tasks:
                return "No active downloads."
            lines = []
            for task in self.active_tasks.values():
                fn = os.path.basename(task.dest_path)
                if task.total_size:
                    progress = f"{task.bytes_downloaded}/{task.total_size} ({task.progress_percent:.1f}%)"
                else:
                    progress = f"{task.bytes_downloaded} bytes"
                if task.is_stalled(self.config.stall_timeout):
                    lines.append(f"[STALLED] {fn}: {progress}")
                else:
                    lines.append(f"{fn}: {progress}")
            for task in self.failed_tasks.values():
                fn = os.path.basename(task.dest_path)
                lines.append(f"[FAILED] {fn}: {task.error or 'unknown error'}")
            return " | ".join(lines)

    # ------------------------------------------------------------------
    # Run Manager
    # ------------------------------------------------------------------
    def start(self):
        if self.console:
            self._start_tui()
        else:
            self._start_simple()

    def _start_simple(self):
        workers = []
        for _ in range(self.config.max_concurrent * 2):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            workers.append(t)
        try:
            while self.running:
                status_line = self.get_status_line()
                sys.stdout.write(f"\r\033[K{status_line}")
                sys.stdout.flush()
                time.sleep(1)
        except KeyboardInterrupt:
            self._signal_handler(None, None)
        finally:
            print()

    def _start_tui(self):
        if not RICH_AVAILABLE:
            return self._start_simple()
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
        self.progress_table = Table.grid(expand=True)
        self.progress_table.add_row(
            Panel(self.progress, title="Downloads", border_style="green")
        )

        workers = []
        for _ in range(self.config.max_concurrent * 2):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            workers.append(t)

        with Live(self.progress_table, console=self.console, refresh_per_second=10):
            try:
                while self.running:
                    self._update_tui()
                    time.sleep(0.1)
            except KeyboardInterrupt:
                self._signal_handler(None, None)

    def _update_tui(self):
        with self.task_lock:
            # Remove finished tasks from progress bar
            for url in list(self.task_ids.keys()):
                if url not in self.active_tasks:
                    self.progress.remove_task(self.task_ids.pop(url))
            # Add or update active tasks
            for task in self.active_tasks.values():
                if task.url not in self.task_ids:
                    fn = os.path.basename(task.dest_path)
                    self.task_ids[task.url] = self.progress.add_task(
                        f"[cyan]{fn}",
                        filename=fn,
                        total=task.total_size if task.total_size > 0 else None,
                        completed=task.bytes_downloaded,
                    )
                else:
                    tid = self.task_ids[task.url]
                    self.progress.update(
                        tid,
                        completed=task.bytes_downloaded,
                        total=task.total_size if task.total_size > 0 else None,
                    )

    # ------------------------------------------------------------------
    # Worker Thread (with stall detection)
    # ------------------------------------------------------------------
    def _worker(self):
        while self.running:
            try:
                task = self.queue.get(timeout=1)
            except Empty:
                continue
            if task.is_cancelled:
                self.queue.task_done()
                continue

            self.active_semaphore.acquire()
            try:
                with self.task_lock:
                    self.pending_tasks.pop(task.url, None)
                    self.active_tasks[task.url] = task
                    task.status = TaskStatus.RUNNING
                    task.update_progress_time()

                try:
                    self._download_task(task)
                except Exception as e:
                    task.status = TaskStatus.FAILED
                    task.error = str(e)
                    self.logger.error(f"Download failed: {task.url} - {e}")
                    self._trigger_hook("on_error", task, error=e)
                finally:
                    with self.task_lock:
                        if task.status == TaskStatus.COMPLETED:
                            task.completed_at = time.time()
                            self.completed_tasks.append(task)
                            if len(self.completed_tasks) > 100:
                                self.completed_tasks.pop(0)
                        elif task.status == TaskStatus.FAILED:
                            self._log_failed_link(task)
                            self.failed_tasks[task.url] = task
                        del self.active_tasks[task.url]
                        if task.url in self.task_ids:
                            self.progress.remove_task(self.task_ids.pop(task.url))
                    self.queue.task_done()
                    self._save_state()
            finally:
                self.active_semaphore.release()

    # ------------------------------------------------------------------
    # Download logic with stall detection and timeout
    # ------------------------------------------------------------------
    def _download_task(self, task):
        self._trigger_hook("on_start", task)
        try:
            if self.config.segments > 1 and self._supports_range(task.url):
                self._segmented_download(task)
            else:
                self._single_download(task)
        except Exception as e:
            task.status = TaskStatus.FAILED
            task.error = str(e)
            return

        if (
            task.status == TaskStatus.COMPLETED
            and self.config.checksum_verify
            and task.expected_checksum
        ):
            if not self._verify_checksum(
                task.dest_path, task.expected_checksum, task.checksum_algo
            ):
                task.status = TaskStatus.FAILED
                task.error = "Checksum mismatch"
                self.logger.error(f"Checksum mismatch for {task.url}")
                return
        self._trigger_hook("on_complete", task)

    def _supports_range(self, url):
        try:
            resp = self.session.head(url, timeout=self.config.timeout)
            return resp.headers.get("Accept-Ranges") == "bytes"
        except:
            return False

    def _single_download(self, task):
        headers = task.headers.copy()
        file_path = task.dest_path
        part_path = file_path + ".part"
        downloaded = 0
        mode = "wb"
        if os.path.exists(part_path):
            downloaded = os.path.getsize(part_path)
            headers["Range"] = f"bytes={downloaded}-"
            mode = "ab"
        elif os.path.exists(file_path):
            downloaded = os.path.getsize(file_path)
            headers["Range"] = f"bytes={downloaded}-"
            mode = "ab"
            part_path = file_path
        task.bytes_downloaded = downloaded
        task.update_progress_time()

        for attempt in range(self.config.retries + 1):
            try:
                with self.session.get(
                    task.url, stream=True, headers=headers, timeout=self.config.timeout
                ) as r:
                    if r.status_code not in (200, 206):
                        r.raise_for_status()
                    if downloaded > 0 and r.status_code == 200:
                        downloaded = 0
                        mode = "wb"
                    total = int(r.headers.get("Content-Length", 0))
                    if r.status_code == 206:
                        task.total_size = downloaded + total
                    else:
                        task.total_size = total
                    with open(part_path, mode) as f:
                        for chunk in r.iter_content(chunk_size=self.config.chunk_size):
                            while task.is_paused and not task.is_cancelled:
                                time.sleep(0.5)
                            if task.is_cancelled:
                                return
                            if chunk:
                                if self.throttle:
                                    wait = self.throttle.consume(len(chunk))
                                    if wait > 0:
                                        time.sleep(wait)
                                f.write(chunk)
                                task.bytes_downloaded += len(chunk)
                                task.update_progress_time()
                                self._trigger_hook("on_progress", task)
                            # Stall detection
                            if task.is_stalled(self.config.stall_timeout):
                                raise Exception(
                                    f"Download stalled for {self.config.stall_timeout}s"
                                )
                break
            except (requests.RequestException, IOError) as e:
                if attempt == self.config.retries:
                    raise
                wait = self.config.retry_backoff**attempt
                self.logger.warning(
                    f"Retry {attempt + 1}/{self.config.retries} for {task.url} in {wait}s"
                )
                time.sleep(wait)
                mode = "ab"
                downloaded = (
                    os.path.getsize(part_path) if os.path.exists(part_path) else 0
                )
                headers["Range"] = f"bytes={downloaded}-"
                task.bytes_downloaded = downloaded
                task.update_progress_time()

        if part_path != file_path:
            os.rename(part_path, file_path)
        task.status = TaskStatus.COMPLETED

    def _segmented_download(self, task):
        num = self.config.segments
        try:
            head = self.session.head(task.url, timeout=self.config.timeout)
            total_size = int(head.headers.get("Content-Length", 0))
        except:
            total_size = 0
        if total_size == 0:
            self._single_download(task)
            return
        task.total_size = total_size
        seg_size = total_size // num
        parts = []
        for i in range(num):
            start = i * seg_size
            end = start + seg_size - 1 if i < num - 1 else total_size - 1
            parts.append((start, end))
        part_files = [f"{task.dest_path}.part{i}" for i in range(num)]
        seg_downloaded = []
        for i, pf in enumerate(part_files):
            if os.path.exists(pf):
                sz = os.path.getsize(pf)
                seg_downloaded.append(sz)
                s, e = parts[i]
                parts[i] = (s + sz, e)
            else:
                seg_downloaded.append(0)
        with ThreadPoolExecutor(max_workers=num) as ex:
            futs = []
            for idx, (s, e) in enumerate(parts):
                futs.append(
                    ex.submit(
                        self._download_segment,
                        task,
                        idx,
                        s,
                        e,
                        part_files[idx],
                        seg_downloaded[idx],
                    )
                )
            for fut in as_completed(futs):
                if fut.exception():
                    task.status = TaskStatus.FAILED
                    task.error = str(fut.exception())
                    return
        with open(task.dest_path, "wb") as out:
            for pf in part_files:
                with open(pf, "rb") as inf:
                    while chunk := inf.read(self.config.chunk_size):
                        out.write(chunk)
                os.remove(pf)
        task.status = TaskStatus.COMPLETED

    def _download_segment(self, task, idx, start, end, part_path, initial_bytes=0):
        headers = task.headers.copy()
        if start > end:
            return
        headers["Range"] = f"bytes={start}-{end}"
        for attempt in range(self.config.retries + 1):
            try:
                with self.session.get(
                    task.url, stream=True, headers=headers, timeout=self.config.timeout
                ) as r:
                    r.raise_for_status()
                    mode = "ab" if initial_bytes > 0 else "wb"
                    with open(part_path, mode) as f:
                        for chunk in r.iter_content(chunk_size=self.config.chunk_size):
                            while task.is_paused and not task.is_cancelled:
                                time.sleep(0.5)
                            if task.is_cancelled:
                                return
                            if chunk:
                                f.write(chunk)
                                with self.task_lock:
                                    task.bytes_downloaded += len(chunk)
                                task.update_progress_time()
                break
            except Exception as e:
                if attempt == self.config.retries:
                    raise
                time.sleep(self.config.retry_backoff**attempt)

    def _verify_checksum(self, path, expected, algo):
        h = hashlib.new(algo)
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(8192), b""):
                h.update(chunk)
        return h.hexdigest().lower() == expected.lower()

    def check_for_updates(self):
        if not self.config.update_check:
            return
        try:
            resp = requests.get(self.config.update_url, timeout=5)
            latest = resp.json()["tag_name"]
            if latest != "2.0.0":
                self.logger.info(f"Update available: {latest} (you have 2.0.0)")
        except Exception as e:
            self.logger.debug(f"Update check failed: {e}")


# ----------------------------------------------------------------------
# CLI Helpers
# ----------------------------------------------------------------------
def print_list(
    manager, active_only=False, pending_only=False, completed_only=False, sort_by=None
):
    status = manager.get_status()
    all_tasks = status["tasks"]
    # Filter
    if active_only:
        tasks = [t for t in all_tasks if t["status"] == "running"]
    elif pending_only:
        tasks = [t for t in all_tasks if t["status"] in ("pending", "paused")]
    elif completed_only:
        tasks = [t for t in all_tasks if t["status"] == "completed"]
    else:
        tasks = all_tasks

    if not tasks:
        print("No downloads found.")
        return

    # Apply sorting (if requested)
    if sort_by == "name":
        tasks.sort(key=lambda t: os.path.basename(t["dest_path"]).lower())
    elif sort_by == "size":
        tasks.sort(key=lambda t: t.get("total_size", 0))
    elif sort_by == "url":
        tasks.sort(key=lambda t: t["url"])
    else:
        # Default: sort by creation time (oldest first) to match index order
        tasks.sort(key=lambda t: t["created_at"])

    if RICH_AVAILABLE and manager.console:
        table = Table(title="Downloads", show_lines=True)
        table.add_column("#", style="cyan", no_wrap=True)
        table.add_column("Status", style="green")
        table.add_column("URL", style="white")
        table.add_column("Destination", style="dim")
        table.add_column("Progress", style="yellow")
        for idx, t in enumerate(tasks, 1):
            progress = (
                f"{t['bytes_downloaded']}/{t['total_size']}"
                if t["total_size"]
                else f"{t['bytes_downloaded']} bytes"
            )
            status_str = t["status"].upper()
            if t["status"] == "running":
                status_str = f"[bold green]{status_str}[/bold green]"
            elif t["status"] == "paused":
                status_str = f"[yellow]{status_str}[/yellow]"
            elif t["status"] == "failed":
                status_str = f"[red]{status_str}[/red]"
            elif t["status"] == "completed":
                status_str = f"[blue]{status_str}[/blue]"
            table.add_row(str(idx), status_str, t["url"], t["dest_path"], progress)
        manager.console.print(table)
    else:
        for idx, t in enumerate(tasks, 1):
            progress = (
                f"{t['bytes_downloaded']}/{t['total_size']}"
                if t["total_size"]
                else f"{t['bytes_downloaded']} bytes"
            )
            print(
                f"[{idx}] {t['status'].upper()} | {t['url']} -> {t['dest_path']} ({progress})"
            )


def confirm(prompt, default="y"):
    ans = input(f"{prompt} [y/N]: ").strip().lower()
    if not ans:
        ans = default
    return ans == "y"


# ----------------------------------------------------------------------
# CLI Entry Point
# ----------------------------------------------------------------------
def create_parser():
    parser = argparse.ArgumentParser(description="Download Manager (Index‑Based)")
    sub = parser.add_subparsers(dest="command", required=True)

    # add
    add_p = sub.add_parser("add")
    add_p.add_argument("url")
    add_p.add_argument("--output", "-o")
    add_p.add_argument("--priority", "-p", type=int, default=5)
    add_p.add_argument("--checksum")
    add_p.add_argument("--algo", default="sha256")

    # add-list
    al = sub.add_parser("add-list")
    al.add_argument("file")
    al.add_argument("--output-dir", "-o")
    al.add_argument("--priority", "-p", type=int, default=5)

    # pause
    pa = sub.add_parser("pause")
    pa.add_argument("patterns", nargs="*", help="Index patterns (default: all)")

    # resume
    re = sub.add_parser("resume")
    re.add_argument(
        "patterns", nargs="*", help="Index patterns (default: all paused/failed"
    )

    # remove
    rm = sub.add_parser("remove")
    rm.add_argument("patterns", nargs="*", help="Index patterns (default: all)")
    rm.add_argument("--delete-file", action="store_true")

    # move
    mv = sub.add_parser(
        "move", help="Move pending tasks to a new position among pending tasks"
    )
    mv.add_argument("pattern", help="Index pattern of pending tasks to move")
    mv.add_argument(
        "target_index", type=int, help="1‑based position in the pending list"
    )

    # restart
    restart = sub.add_parser(
        "restart",
        help="Restart selected downloads (delete partial files and start over)",
    )
    restart.add_argument(
        "patterns", nargs="*", help="Index patterns (default: last link)"
    )

    # search
    se = sub.add_parser(
        "search", help="Search a webpage or HTML file for links and add them"
    )
    se.add_argument("source", help="URL or path to HTML file")
    se.add_argument("--output-dir", "-o")
    se.add_argument("--priority", "-p", type=int, default=5)

    # export
    exp = sub.add_parser("export", help="Export all non‑completed tasks to a file")
    exp.add_argument("file", help="Output file path")
    exp.add_argument("--csv", action="store_true", help="Export as CSV")

    # list
    ls = sub.add_parser("list")
    ls.add_argument("--active", action="store_true")
    ls.add_argument("--pending", action="store_true")
    ls.add_argument("--completed", action="store_true")
    ls.add_argument(
        "--sort",
        choices=["name", "size", "url"],
        default=None,
        help="Sort by filename, total size, or URL (default: creation order)",
    )

    # failures
    fail = sub.add_parser("failures", help="Show or retry previously failed links")
    fail.add_argument(
        "--retry", action="store_true", help="Add all failed links back to the queue"
    )
    fail.add_argument("--clear", action="store_true", help="Clear the failure log")

    # status
    sub.add_parser("status")

    # run
    run = sub.add_parser(
        "run", help="Start the download manager (optionally only for selected tasks)"
    )
    run.add_argument(
        "patterns", nargs="*", help="Index patterns of tasks to run (default: all)"
    )
    run.add_argument("--config", "-c")
    run.add_argument("--resume", action="store_true")
    run.add_argument("--output", "-o")
    run.add_argument("--max-concurrent", type=int)
    run.add_argument("--speed-limit", type=int)
    run.add_argument("--segments", type=int)
    run.add_argument("--no-tui", action="store_true")

    return parser


def main():
    parser = create_parser()
    args = parser.parse_args()

    def load_config(cfg_path=None):
        if cfg_path is None:
            default_cfg = os.path.expanduser("~/.config/dm/config.yaml")
            if os.path.exists(default_cfg):
                cfg_path = default_cfg
        config = Config(cfg_path)
        if hasattr(args, "output") and args.output:
            config.data["download_dir"] = args.output
        if hasattr(args, "max_concurrent") and args.max_concurrent:
            config.data["max_concurrent"] = args.max_concurrent
        if hasattr(args, "speed_limit") and args.speed_limit is not None:
            config.data["speed_limit"] = args.speed_limit
        if hasattr(args, "segments") and args.segments:
            config.data["segments"] = args.segments
        if hasattr(args, "no_tui") and args.no_tui:
            config.data["tui"] = False
        return config

    if args.command == "run":
        config = load_config(args.config)
        logger = setup_logging(config)
        manager = DownloadManager(config, logger)
        manager.check_for_updates()
        manager.run_only_patterns(args.patterns)
        manager.start()
    else:
        config = load_config()
        logger = setup_logging(config)
        manager = DownloadManager(config, logger)

        if args.command == "add":
            task = manager.add_download(
                args.url,
                dest_path=args.output,
                priority=args.priority,
                expected_checksum=args.checksum,
                checksum_algo=args.algo,
            )
            print(f"Added: {task.url} -> {task.dest_path}")

        elif args.command == "add-list":
            if not os.path.exists(args.file):
                print(f"Error: File not found: {args.file}")
                sys.exit(1)
            added = skipped = 0
            with open(args.file, "r") as f:
                for line_num, line in enumerate(f, 1):
                    url = line.strip()
                    if not url:
                        continue
                    if not url.startswith(("http://", "https://")):
                        print(f"Warning: Line {line_num} skipped: {url}")
                        skipped += 1
                        continue
                    dest = None
                    if args.output_dir:
                        parsed = urlparse(url)
                        filename = os.path.basename(parsed.path) or "download"
                        dest = os.path.join(args.output_dir, filename)
                    try:
                        task = manager.add_download(
                            url, dest_path=dest, priority=args.priority
                        )
                        print(f"Added: {task.url} -> {task.dest_path}")
                        added += 1
                    except Exception as e:
                        print(f"Error adding {url}: {e}")
                        skipped += 1
            print(f"\nBatch add complete. Added: {added}, Skipped: {skipped}")

        elif args.command == "pause":
            succ, errs = manager.pause_by_indices(args.patterns)
            print(f"Paused {succ} download(s).")
            for e in errs:
                print(f"  {e}")

        elif args.command == "resume":
            succ, errs = manager.resume_by_indices(args.patterns)
            print(f"Resumed {succ} download(s).")
            for e in errs:
                print(f"  {e}")

        elif args.command == "remove":
            if not args.patterns:
                total = len(manager._get_sorted_task_list())
                if total == 0:
                    print("No downloads to remove.")
                    sys.exit(0)
                if not confirm(f"Do you want to remove all links (total: {total})?"):
                    print("Operation cancelled.")
                    sys.exit(0)
            succ, errs = manager.remove_by_indices(
                args.patterns, delete_file=args.delete_file
            )
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
            added, errs = manager.search_and_add_links(
                args.source, args.output_dir, args.priority
            )
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
                sort_by=args.sort,
            )

        elif args.command == "failures":
            failed_log = Path(config.failed_log).expanduser()
            if not failed_log.exists():
                print("No failure log found.")
                sys.exit(0)
            with open(failed_log, "r", encoding="utf-8") as f:
                lines = [l.strip() for l in f if l.strip()]
            if args.clear:
                failed_log.unlink()
                print(f"Cleared failure log ({len(lines)} entries).")
            elif args.retry:
                added = 0
                for line in lines:
                    parts = line.split(" | ")
                    url = parts[0]
                    dest = parts[1] if len(parts) > 1 else None
                    try:
                        manager.add_download(url, dest_path=dest)
                        added += 1
                    except Exception as e:
                        print(f"Failed to re-add {url}: {e}")
                print(f"Re‑added {added} failed links.")
                failed_log.unlink()
            else:
                print("Failed links (use --retry to add them back):")
                for i, line in enumerate(lines, 1):
                    print(f"{i}. {line}")

        elif args.command == "status":
            st = manager.get_status()
            print(
                f"Active: {st['active']}, Pending: {st['pending']}, Failed: {st['failed']}, Completed: {st['completed']}"
            )

        manager._save_state()


if __name__ == "__main__":
    main()
