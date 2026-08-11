# Download Manager — Bug Report

## Summary

Based on systematic testing, logical bugs and issues in the task management and link handling areas are documented below. Actual download functionality was NOT tested (user confirmed it works).

> **STATUS:** All six bugs below have been FIXED in `dm.py`. Verification commands are listed under each bug.

---

## BUG-001: Path Traversal Vulnerability in Link Extraction — FIXED

**Severity:** Critical

**Test Case:** T3.1 (Search local HTML file)

**Description:** The search command extracts links from HTML and saves them to disk. A path traversal attack is possible when a URL contains `../` sequences.

**Example:** URL with `../` becomes file in download directory.

**Code Location:** `dm.py` — `safe_filename` function (was lines 378-382).

**Fix Applied:** `safe_filename` now (1) strips query/fragment, (2) takes the final component after splitting on both `/` and `\\`, (3) defensively strips a leading `..` if it survives basename (e.g. `..` or `..secret`), (4) replaces spaces and control chars with `_`, (5) collapses repeated `_` and trims ends. `https://example.com/../etc/passwd` → `passwd`, `https://x/..` → `download`, `..%2f..%2fetc%2fpasswd` → `passwd`.

**Verify:** `python3 dm.py add "https://example.com/../etc/passwd"` → dest stays inside Manager dir.

---

## BUG-002: Spaces in URLs Not Handled — FIXED

**Severity:** High

**Test Case:** T2.1 (Add-list from file)

**Description:** When a URL contains spaces, the resulting filename kept the literal space, which breaks shells and is unsafe on many filesystems.

**Code Location:** `dm.py` — `safe_filename` (consumed by `add_download`, `add-list`, `search_and_add_links`).

**Fix Applied:** `safe_filename` now replaces whitespace (and the previously handled `/` and `:`) via `re.sub(r"[\x00-\x1f\s/:]+", "_", name)`. `file name.zip` → `file_name.zip`, `file%20name.zip` → `file_name.zip`.

**Verify:** `python3 dm.py add "https://example.com/file name.zip"` → `.../file_name.zip`.

---

## BUG-003: Invalid URL Crashes CLI Without Graceful Error — FIXED

**Severity:** High

**Test Case:** T1.6 (Add invalid URL)

**Description:** When adding an invalid URL, the program crashed with a traceback instead of a clean error message.

**Code Location:** `dm.py` — `main()` `add` command handler.

**Fix Applied:** Wrapped `manager.add_download(...)` in a `try/except ValueError` that prints `Error: <msg>` to stderr and raises `SystemExit(1)`.

**Verify:** `python3 dm.py add "not-a-url"` → `Error: Invalid URL: not-a-url`, exit code 1 (no traceback).

---

## BUG-004: Add-List Duplicates Counted as Added — FIXED

**Severity:** Medium

**Test Case:** T2.1 (Add-list from file)

**Description:** When `add-list` encountered duplicate URLs it silently returned the existing task and still incremented `added`. Output showed "Added: 11, Skipped: 0" even when many URLs were duplicates.

**Code Location:** `dm.py` — `main()` `add-list` handler; helper `DownloadManager.find_task()`.

**Fix Applied:** Added `DownloadManager.find_task(url)` (thread-safe lookup across pending/active/failed/completed). The `add-list` handler checks `find_task(url)` before calling `add_download`; duplicates print `Skipped (duplicate): <url>` and increment `skipped` instead of `added`.

**Verify:** `python3 dm.py add-list test_links.txt` twice — second run shows `Added: 0, Skipped: 11`.

---

## BUG-005: Relative Links Not Extracted from HTML — FIXED

**Severity:** Medium

**Test Case:** T3.1 (Search local HTML file)

**Description:** Relative links like `/downloads/manual.pdf` were NOT extracted, because for a local file source `base_url = None` and the `urljoin` branch was gated on `if base_url and ...`.

**Code Location:** `dm.py` — `search_and_add_links` (signature extended with `base_url_override`, `filter_extensions`).

**Fix Applied:**
- New optional CLI flag `search --base-url URL` to resolve relative links when scanning a local HTML file.
- When no override is supplied, the method auto-detects an HTML `<base href="...">` tag in the file and uses it as the base.
- Relative links (`/path`, `path`, `//host/path`) are now resolved via `urljoin(base_url, link)` (or `https:`-prefixed for `//host` form) and added when the result is `http(s)://...`.

**Verify:** `python3 dm.py search test_page.html --base-url "https://example.com/"` includes `/downloads/manual.pdf` and `/images/icon.svg`.

---

## BUG-006: Search Extracts Non-Download Links (External Pages) — FIXED

**Severity:** Low

**Test Case:** T3.1 (Search local HTML file)

**Description:** Links like `https://external-site.com/page` and `https://github.com/project/repo` were extracted and added as downloads, but these are just web pages, not downloadable files.

**Code Location:** `dm.py` — `search_and_add_links`; module-level `DOWNLOAD_EXTENSIONS` whitelist.

**Fix Applied:** New optional CLI flag `search --no-filter` toggles filtering. By default (`filter_extensions=True`) only links whose path has a recognized download extension (archives, installers, media, images, docs, etc. — see `DOWNLOAD_EXTENSIONS`) are added. Non-downloadable pages like `/page` or `/user/repo` are skipped and logged at INFO level. Protocols `mailto:`, `javascript:`, `ftp:` and pure `#` fragments are always excluded.

**Verify:**
- `python3 dm.py search test_page.html --base-url "https://example.com/"` → 10 links (no `/page`, no `/project/repo`).
- `python3 dm.py search test_page.html --base-url "https://example.com/" --no-filter` → all `http(s)` links added (filter off).

---

## Notes on Test Execution

1. All tests were run using imaginary URLs (no actual downloads)
2. The test script `run_tests.sh` was used to execute tests
3. Full results are in `test_results.md`
4. Test data files created:
   - `test_links.txt` - URL list for add-list testing
   - `test_page.html` - HTML page with links for search testing

## Regression Verification (after fixes)

```
python3 -m py_compile dm.py    # OK (no syntax errors)
python3 dm.py --version         # dm 2.1.0
python3 dm.py add "not-a-url"   # Error: Invalid URL: not-a-url  (exit 1, no traceback)
python3 dm.py add-list test_links.txt   # Added: 11, Skipped: 0  (first run)
python3 dm.py add-list test_links.txt   # Added: 0, Skipped: 11  (second run)
python3 dm.py search test_page.html --base-url "https://example.com/"  # 10 links, relative incl.
```
