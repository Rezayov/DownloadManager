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

# Regex link hunting: only add links matching a pattern (Python re.search on the URL)
python dm.py search https://example.com/library --pattern '\.mp4$'
python dm.py search https://example.com/library --pattern 'season-?2' --exclude-pattern '(sample|trailer)'
# Combine with --no-filter to catch extension-less links (e.g. /download?id=42)
python dm.py search https://example.com/dl --pattern 'download\?id=' --no-filter

# Retry all failed links from log
python dm.py failures --retry

# Use a custom config file
python dm.py run --config ~/myconfig.yaml

# Limit speed to 1 MB/s
python dm.py run --speed-limit 1048576
```

### Where downloads go by default
Unless you say otherwise, downloads are saved **in the directory you run dm
from** (your current working directory). Override it with any of (highest
priority first):

1. `-o/--output-file` (`add`) or `-o/--output-dir` (`add-list`, `search`)
2. `-d/--download-dir` (`add`, `add-list`, `search`, `run`)
3. `DM_DOWNLOAD_DIR` environment variable
4. `download_dir:` in `~/.config/dm/config.yaml`

Central state, logs, and failure logs stay in their configured locations
(`~/Downloads/Manager/...` by default) no matter where files land.

### Authentication (proving your identity on protected domains)
dm can save per-domain credentials so `add`, `add-list`, `search`, and `run`
can download from links you are authorized for. Credentials live in
`~/.config/dm/auth.json` (created with `0600` permissions) and all values
support `${ENV_VAR}` references so secrets can stay out of files.

```bash
# Bearer / API token (recommended: reference an env var)
export MY_TOKEN=ghp_xxxxxxxx
dm auth add dl.example.com --type bearer --token '${MY_TOKEN}'

# Arbitrary headers (repeatable)
dm auth add api.example.com --type header --header 'X-Api-Key: 123456'

# HTTP Basic auth (password prompted securely if omitted)
dm auth add nas.local --type basic --username reza

# Cookies: inline string or a cookies.txt exported from your browser
dm auth add forum.example.com --type cookies --cookie 'session=abc; theme=dark'
dm auth add tracker.example.com --type cookies --cookie-file ~/cookies.txt

# Wildcards match subdomains; exact host beats wildcard beats parent domain
dm auth add '*.example.com' --type bearer --token '${MY_TOKEN}'
```

Once saved, credentials apply automatically whenever a task's URL matches the
domain — including page fetching for `search`:

```bash
# Finds links on pages that require login, then downloads them as you
dm search https://dl.example.com/library -o ~/Downloads

# Verify identity against any URL before downloading
dm auth test https://dl.example.com/file.bin   # prints HTTP status + verdict
dm auth list                                    # secrets shown masked
dm auth remove dl.example.com
```

One-off credentials are also available without saving anything:
`--cookie 'k=v'`, `--header 'Name: Value'` (repeatable), `--user USER:PASS`,
and `--auth-domain DOMAIN` to force a specific profile. When used with
`add`/`add-list`/`search`, one-off credentials are baked into those tasks so a
later `dm run` keeps working. Stored profiles are never baked into tasks —
they resolve fresh at request time, rotate safely, and never touch
`state.json`. On 401/403 responses dm logs a hint telling you exactly which
`dm auth add ...` command to run.

### Configuration
Create `~/.config/dm/config.yaml`:
```yaml
# download_dir defaults to the directory dm is invoked from if not set here
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

Or set environment variables: `DM_MAX_CONCURRENT=8`, `DM_SPEED_LIMIT=2000000`, `DM_AUTH_FILE=~/.config/dm/auth.json`

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
