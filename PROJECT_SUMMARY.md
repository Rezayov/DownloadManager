# Download Manager — Project Summary

## Overview

A **feature-rich command-line download manager** written in pure Python. Supports concurrent downloads, pause/resume, segmented downloading, speed limiting, checksum verification, job queue with persistence, and index-based CLI control.

---

## Architecture

### Single-File Design

All functionality resides in `dm.py` (1,734 lines):

| Component | Lines | Purpose |
|-----------|-------|---------|
| Configuration System | 100-177 | Hierarchical config: defaults → file → env → CLI args |
| Logging Setup | 183-206 | File + console logging |
| File Locking | 212-236 | Advisory locking for state persistence |
| Task Model | 242-339 | DownloadTask dataclass with state machine |
| Throttling | 345-366 | Token-bucket speed limiter |
| DownloadManager Core | 422-1213 | Engine: add, pause, resume, worker, download logic |
| CLI Helpers | 1478-1523 | Output formatting (list, status) |
| CLI Parser | 1529-1589 | Argument parsing via argparse |
| Main Entry Point | 1605-1734 | Command dispatcher and execution |

---

## Core Components

### Configuration System

Hierarchical configuration with four levels (highest to lowest priority):

1. **CLI arguments** (e.g., `--download-dir`)
2. **Environment variables** (e.g., `DM_MAX_CONCURRENT`)
3. **Config file** (`~/.config/dm/config.yaml` or custom via `--config`)
4. **Default values** (hardcoded in `DEFAULT_CONFIG`)

Config file supports JSON or YAML formats. Paths with `~` are expanded automatically.

### Task State Machine

```
                    ┌─────────────┐
                    │   PENDING   │
                    └──────┬──────┘
                           │ worker picks up
                           ▼
                    ┌─────────────┐
            ┌───────│   RUNNING   │──────┐
            │       └─────────────┘      │
            │                  │        │
            │         ┌────────┴───┐    │
            │         ▼            ▼    ▼
            │   ┌──────────┐  ┌──────────┐
            │   │COMPLETED │  │  FAILED  │
            │   └──────────┘  └──────────┘
            │
            │ user pause
            ▼
      ┌──────────┐
      │  PAUSED  │
      └──────────┘

      (CANCELLED is terminal from any state except COMPLETED)
```

**Thread-safety mechanisms:**
- `threading.RLock` for task dictionary operations
- `threading.Event` for pause/cancel signaling
- Priority queue with `(priority, sequence, url)` tuples

### Download Engine

**Producer-Consumer Pattern:**
- `PriorityQueue` holds pending tasks
- Worker threads consume tasks respecting `max_concurrent`
- Supports segmented downloads (multiple ranges per file) via `ThreadPoolExecutor`
- Stall detection: fails if no progress for `stall_timeout` seconds

**HTTP Handling:**
- `requests.Session` with retry strategy (backoff, 500-504 status codes)
- Range requests for resume and segmentation
- Timeout, proxy support, custom User-Agent
- Speed limiting via token-bucket `Throttle` class

### Index-Based Commands

Tasks are displayed with 1-based indices (sorted by creation time). Supports patterns:

| Pattern | Meaning |
|---------|---------|
| `1-5` | Indices 1 through 5 |
| `3,7,9` | Specific indices |
| `1-5~3` | All from 1-5 except 3 |
| `1,2,3-5~4` | Complex exclusion |

### User Interface

- **TUI mode** (default): Live progress bars via `rich` library
- **Simple mode** (fallback): Single-line status updates

---

## Command Reference

| Command | Description |
|---------|-------------|
| `dm add <url>` | Add single download |
| `dm add-list <file>` | Batch add from text file (one URL per line) |
| `dm list` | List all tasks with indices |
| `dm pause <pattern>` | Pause matching tasks |
| `dm resume` | Resume all paused/failed tasks |
| `dm remove <pattern>` | Remove tasks |
| `dm move <pattern> <index>` | Reorder pending tasks |
| `dm restart <pattern>` | Re-download failed/pending tasks |
| `dm search <source>` | Extract links from HTML page/file |
| `dm export <file>` | Export tasks to file |
| `dm failures` | Show/retry/clear failed links |
| `dm run` | Start download processing |

---

## Data Flow

```
User Command
     │
     ▼
┌─────────────────┐
│ create_parser() │  (argparse)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ main()          │  dispatch
└────────┬────────┘
         │
         ▼
┌─────────────────────────────────────────────────────┐
│ DownloadManager                                      │
│                                                     │
│  ┌─────────────┐  ┌─────────────┐                  │
│  │ pending_    │  │ active_     │  Dictionary      │
│  │ tasks{}     │  │ tasks{}     │  keyed by URL   │
│  └─────────────┘  └─────────────┘                  │
│  ┌─────────────┐  ┌─────────────┐                  │
│  │ failed_     │  │completed_   │                  │
│  │ tasks{}     │  │ tasks{}     │                  │
│  └─────────────┘  └─────────────┘                  │
│                                                     │
│  ┌─────────────────────────────────────┐           │
│  │ PriorityQueue                       │           │
│  │ (priority, sequence, url)           │           │
│  └─────────────────────────────────────┘           │
│                                                     │
│  ┌─────────────────────────────────────┐           │
│  │ Workers (threading.Thread)           │           │
│  │ _worker() → _single_download()       │           │
│  │          or _segmented_download()   │           │
│  └─────────────────────────────────────┘           │
└─────────────────────────────────────────────────────┘
         │
         ▼
   State Persistence (JSON)
   ~/Downloads/Manager/state.json
```

---

## Key Implementation Details

### Segmented Download Logic

```
┌────────────────────────────────────────────────────────┐
│  Server supports Range?                                │
│              │                                         │
│              ▼ No                                     │
│     _single_download()                                │
│              │                                         │
│              ▼ Yes                                    │
│    _remote_size_for_range_download()                   │
│              │                                         │
│              ▼                                        │
│    Create N segments (N = min(segments, total_size))  │
│    For each segment:                                   │
│      - Check if .partN exists and size matches       │
│      - If complete, skip; otherwise add to job list  │
│    ThreadPoolExecutor downloads segments in parallel  │
│    Merge segments → final file                        │
└────────────────────────────────────────────────────────┘
```

### Pause/Resume Mechanism

- Each `DownloadTask` has `_cancel_event: threading.Event`
- **Pause**: Sets cancel event; worker checks `is_cancelled` during chunk loops
- **Resume**: Clears cancel event, resets task status to PENDING, re-queues
- State is saved after every modification to `state.json`

### Filename Collision Handling

`add_download()` calls `_unique_dest_path()` which:
1. Takes desired path
2. Appends counter suffix if file exists: `file_1.txt`, `file_2.txt`
3. Returns unique path avoiding conflicts with existing tasks

### Link Extraction (search command)

For HTML source:
1. Fetches URL or reads local file
2. Uses BeautifulSoup if available, otherwise regex fallback
3. Extracts from `<a>`, `<video>`, `<audio>`, `<source>`, `<img>` tags
4. Converts relative URLs to absolute using `urljoin`
5. Validates each URL scheme (http/https only)
6. Adds each valid URL as a download task

---

## File Structure

```
downloadmanager/
├── dm.py           # Main application (1734 lines)
├── pyproject.toml  # Project metadata
├── README.md       # Documentation
└── .venv/          # Python virtual environment
```

---

## Dependencies

| Package | Purpose | Required |
|---------|---------|----------|
| `requests` | HTTP client | Yes |
| `rich` | TUI progress bars | Optional |
| `pyyaml` | YAML config parsing | Optional |
| `beautifulsoup4` | HTML link extraction | Optional |

---

## State Persistence

**Location:** `~/Downloads/Manager/state.json`

**Schema:**
```json
{
  "version": "2.1.0",
  "saved_at": 1234567890.123,
  "tasks": [
    {
      "url": "https://example.com/file.zip",
      "dest_path": "/home/user/Downloads/file.zip",
      "priority": 5,
      "sequence": 12345,
      "expected_checksum": "abc123...",
      "checksum_algo": "sha256",
      "headers": {},
      "auto_filename": false,
      "bytes_downloaded": 1024000,
      "total_size": 10485760,
      "status": "pending",
      "error": null,
      "created_at": 1234567890.123,
      "completed_at": null
    }
  ]
}
```

On startup, if `status == "running"` (crash recovery), automatically reset to `"pending"`.

---

## Error Handling

| Error Type | Handling |
|------------|----------|
| Network timeout | Retry with exponential backoff |
| HTTP 500-504 | Retry with backoff |
| HTTP 416 (Range error) | Special handling for completed downloads |
| Stall detection | Fail task if no progress for `stall_timeout` |
| Checksum mismatch | Fail task after download |
| Disk full | Propagate OSError, fail task |

Failed links are logged to `~/Downloads/Manager/failed_links.txt` for later retry.

---

## Extensibility

### Plugin System

Place Python files in `~/.config/dm/plugins/`. Each plugin can define:

```python
def register_hooks(manager: DownloadManager):
    manager.register_hook("on_start", my_on_start)
    manager.register_hook("on_progress", my_on_progress)
    manager.register_hook("on_complete", my_on_complete)
    manager.register_hook("on_error", my_on_error)
```

### Hooks Available

| Hook | Trigger |
|------|---------|
| `on_start` | Before download begins |
| `on_progress` | After each chunk written |
| `on_complete` | After successful download |
| `on_error` | After failure |

---

## Version

Current version: **2.1.0**

---

## Potential Issue Areas (User-Reported)

The user reports that:
- **Downloading itself works well**
- **Adding links and other options have many bugs**

Known concern areas based on architecture:
1. `move` command — multi-item move may reorder incorrectly
2. `add-list` command — batch URL addition may have edge cases
3. `search` command — link extraction and filtering logic
4. Index pattern parsing — complex patterns with exclusions