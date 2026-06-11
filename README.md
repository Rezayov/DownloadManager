# 📥 Download Manager – A Self‑Configurable CLI Downloader with Index‑Based Control

## 🎯 Project Overview

This is a **feature‑rich command‑line download manager** written in pure Python. It supports concurrent downloads, pause/resume, segmented downloading, speed limiting, checksum verification, and a full job queue with persistence. All tasks are controlled using **1‑based indexes** (e.g., `dm pause 1-3,5`), making it easy to manage many downloads interactively.

> **Learning goal:** Build a production‑ready download manager that handles real‑world challenges – resuming interrupted downloads, throttling, retries, stall detection, and a clean CLI with optional TUI (using Rich).

---

## 📁 Project Structure (Single‑File)

| File | What It Does | Key Concepts Learned | Skills You'll Gain |
|------|--------------|----------------------|---------------------|
| `dm.py` | Everything – CLI parser, download engine, state management, TUI | `argparse`, `threading`, `queue.PriorityQueue`, `requests` with retry, `rich.progress`, `dataclasses`, `enum`, JSON state persistence, signal handling | Write a complete, self‑contained Python application with professional‑grade features |

---

## 🧠 Core Technical Concepts (Organised by Feature)

### 1. **Configuration Management**
- **Hierarchical config**: default values → file (JSON/YAML) → environment variables → CLI arguments.
- **Expansion of `~`** paths, dynamic overriding.
- **Singleton‑style** config object that propagates to all components.

### 2. **Task Abstraction & State Machine**
- `DownloadTask` dataclass with priority (for PriorityQueue), status enum (`PENDING`, `RUNNING`, `PAUSED`, `COMPLETED`, `FAILED`, `CANCELLED`).
- **Thread‑safe** state changes using `threading.RLock`.
- **Pause/Resume** via `threading.Event`.
- **Persistent state** saved to JSON on every change; restored on restart.

### 3. **Concurrent Download Engine**
- **Producer‑consumer** pattern: a `PriorityQueue` holds pending tasks, consumer threads pick tasks respecting `max_concurrent`.
- **Segmented downloads** (multiple ranges per file) with `ThreadPoolExecutor` – significantly speeds up large files on servers that support `Range`.
- **Stall detection**: each task tracks `last_progress_time`; if no progress for `stall_timeout`, it fails and logs.

### 4. **Robust HTTP Handling**
- Uses `requests.Session` with retry strategy (backoff, status codes 500‑504).
- **Range requests** for resume and segmentation.
- Timeout, proxy support, custom User‑Agent.
- Speed limiting via token‑bucket `Throttle` class.

### 5. **Index‑Based Command System**
- Parse complex patterns: `1-5`, `3,7,9`, or exclusive `1-5~3` (all from 1‑5 except 3).
- Commands work on **sorted task list** (by creation time) using indices.
- Examples:
  - `dm pause 2-4` – pause tasks 2,3,4
  - `dm remove --delete-file 1` – remove first task and delete its partial files
  - `dm move 3 1` – move the 3rd pending task to the top of the pending queue

### 6. **User Interface Modes**
- **TUI mode** (default if `rich` installed): live progress bars, per‑task speed, ETA.
- **Simple mode** (fallback): single‑line status update.

### 7. **Extra Features**
- **Search & add** links from a webpage or HTML file (regex extraction of `<a>`, `<video>`, `<source>`).
- **Export** task list to CSV or text.
- **Failure logging** – failed links saved to `failed_links.txt`; can retry all later.
- **Checksum verification** (SHA256, etc.) after download.
- **Plugins** – automatically loads Python files from `~/.config/dm/plugins` and calls `register_hooks()`.
- **Update check** against GitHub API.

---

## 🛠️ Skills You Will Develop

After studying and modifying this code, you will be able to:

1. **Build a CLI tool** with `argparse` and subcommands (like `git`, `docker`).
2. **Manage concurrency** using `threading`, `queue`, `Semaphore`, `Event`.
3. **Implement resumable downloads** with HTTP `Range` headers.
4. **Write thread‑safe code** with locks and atomic state updates.
5. **Design a persistent state** using JSON and file I/O.
6. **Create a live terminal UI** with `rich.progress` and `rich.table`.
7. **Parse complex index patterns** for batch operations.
8. **Handle signals** (SIGINT, SIGTERM) to save state before exit.
9. **Use the `requests` library** with retries, timeouts, streaming.
10. **Implement a speed limiter** (token bucket algorithm).
11. **Add plugin architecture** via dynamic module loading.
12. **Extract links from HTML** using regular expressions.

---

## 🧪 How to Use This Script

### Installation
```bash
pip install requests rich pyyaml   # pyyaml optional, rich optional but recommended
```

### Basic Usage
```bash
# Add a download
python dm.py add https://example.com/file.zip

# Add with custom priority (lower number = higher priority)
python dm.py add https://example.com/bigfile.iso --priority 1

# List all tasks (shows indexes)
python dm.py list

# Pause tasks 2 and 3
python dm.py pause 2-3

# Resume all paused/failed tasks
python dm.py resume

# Move pending task 5 to position 1 (first in queue)
python dm.py move 5 1

# Restart a failed task (delete partial files and re‑queue)
python dm.py restart 4

# Remove task 1 and delete its files
python dm.py remove --delete-file 1

# Export task list to CSV
python dm.py export tasks.csv --csv

# Run the download manager (starts processing queue)
python dm.py run

# Run only tasks 1-3
python dm.py run 1-3
```

### Advanced Features
```bash
# Add all links from a webpage
python dm.py search https://example.com/page.html --output-dir ~/Downloads

# Retry all failed links from log
python dm.py failures --retry

# Use a custom config file
python dm.py run --config ~/myconfig.yaml

# Limit speed to 1 MB/s
python dm.py run --speed-limit 1048576
```

### Configuration
Create `~/.config/dm/config.yaml`:
```yaml
download_dir: ~/Downloads
max_concurrent: 4
chunk_size: 524288
segments: 4
retries: 3
stall_timeout: 30
speed_limit: 0  # 0 = unlimited
user_agent: "MyDM/1.0"
proxy: null
checksum_verify: true
```

Or set environment variables: `DM_MAX_CONCURRENT=8`, `DM_SPEED_LIMIT=2000000`

---

## 🔍 Real‑World Value

This script mirrors the architecture of **professional download managers** (like `aria2`, `wget2`, IDM):
- **Concurrent segmented downloads** maximise bandwidth.
- **Resume capability** handles network interruptions.
- **Priority queue** lets urgent downloads jump ahead.
- **State persistence** survives crashes or reboots.
- **Batch operations** via index patterns are user‑friendly for large queues.

Understanding this code prepares you to build **any network‑facing CLI tool** – from a web scraper to a cloud storage sync utility.

---

## 📚 Prerequisites

- Intermediate Python (classes, decorators, context managers, threading basics)
- Familiarity with HTTP (headers, range requests, status codes)
- No previous download manager experience needed – the code explains each component.

---

## 🚀 Extension Ideas

- **Add BitTorrent support** via `libtorrent`.
- **Implement a web interface** using Flask.
- **Add archive extraction** (unzip, untar) after download.
- **Schedule downloads** (cron‑like).
- **Integrate with browser** via extension.
- **Add post‑download hooks** (virus scan, move to cloud).

---

## 📖 Code Organisation at a Glance

| Section | Lines | Purpose |
|---------|-------|---------|
| Shebang & docstring | 1‑30 | Overview and usage examples |
| Imports | 32‑45 | `os`, `sys`, `threading`, `queue`, `requests`, `rich`, etc. |
| Config class | 47‑110 | Hierarchical config loading |
| Logging setup | 112‑128 | File + console logger |
| Task dataclass | 130‑190 | Download task state machine |
| Throttle class | 192‑214 | Token‑bucket speed limiter |
| DownloadManager class | 216‑900 | Core engine (add, pause, resume, worker, download logic) |
| CLI helpers | 902‑950 | `print_list`, `confirm` |
| Parser & main | 952‑1080 | `argparse` subcommands + dispatcher |

---

## 🧪 Debugging Tips

- Run with `python dm.py run --no-tui` to see raw logs in terminal.
- Check `~/Downloads/Manager/logs/dm.log` for detailed errors.
- Inspect state file `~/Downloads/Manager/state.json` to see saved queue.
- Set environment `DM_DEBUG=1` (if added) to enable more logging.

---

*This single‑file download manager demonstrates how to combine networking, concurrency, persistence, and user interaction into a polished command‑line application – skills directly transferable to any Python backend tool.*
