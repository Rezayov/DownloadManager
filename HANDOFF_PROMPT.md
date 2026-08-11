# Handoff Prompt: Download Manager Debugging Task

## Context

You are taking over from a previous AI that analyzed a Python download manager project, identified bugs through systematic testing, and created documentation. Your task is to **fully debug and fix the code**.

## What Was Done

The previous model:
1. Read and analyzed the entire codebase (`dm.py` - 1734 lines)
2. Created a comprehensive project summary (`PROJECT_SUMMARY.md`)
3. Created a test plan (`TEST_PLAN.md`)
4. Created test data files (`test_links.txt`, `test_page.html`)
5. Executed tests and saved results (`test_results.md`)
6. Identified 6 bugs and documented them (`BUGS_REPORT.md`)

## Files Created (All in `/home/rezayov.guest/downloadmanager/`)

| File | Purpose |
|------|---------|
| `PROJECT_SUMMARY.md` | Full project documentation |
| `BUGS_REPORT.md` | Bug descriptions and fix suggestions |
| `TEST_PLAN.md` | Test cases that were executed |
| `test_results.md` | Actual output from running tests |
| `test_links.txt` | Imaginary URLs for add-list testing |
| `test_page.html` | HTML page with links for search testing |
| `dm.py` | **THE FILE YOU NEED TO FIX** |

## The 6 Bugs to Fix

### BUG-001: Path Traversal Vulnerability (CRITICAL)
**Location:** `dm.py:378-382` (`safe_filename` function)
**Problem:** URLs like `https://example.com/../etc/passwd` become `passwd` in download dir
**Fix:** Add sanitization to block `..` path sequences

### BUG-002: Spaces in URLs Not Handled (HIGH)
**Location:** `dm.py:676-690` (`add_download` function)
**Problem:** URL `https://example.com/file name.zip` creates file `file name.zip` with space
**Fix:** URL-encode spaces or sanitize filenames

### BUG-003: Invalid URL Crashes CLI (HIGH)
**Location:** `dm.py:1614-1622` (main's add command handler)
**Problem:** `dm add "bad-url"` throws traceback instead of clean error
**Fix:** Wrap in try-except, print friendly error

### BUG-004: Duplicate URLs Counted as Added (MEDIUM)
**Location:** `dm.py:1624-1646` (main's add-list handler)
**Problem:** When `add_download()` returns existing task, it's counted as "added" not "skipped"
**Fix:** Check if returned task is new or existing, adjust counter

### BUG-005: Relative Links Not Extracted (MEDIUM)
**Location:** `dm.py:1438-1446` (`search_and_add_links`)
**Problem:** Relative links like `/downloads/manual.pdf` not converted to absolute
**Fix:** The `urljoin()` call exists but check why relative URLs are filtered out

### BUG-006: Non-Download Links Added (LOW)
**Location:** `dm.py:1448-1460` (`search_and_add_links`)
**Problem:** `https://github.com/user/repo` added as download when it's a web page
**Fix:** Optional - filter by file extension

## Code Sections to Study

### safe_filename (BUG-001)
```python
def safe_filename(name: str) -> str:
    name = unquote(name).strip().replace("\x00", "")
    name = os.path.basename(name)  # This extracts the basename but doesn't sanitize ..
    name = re.sub(r"[/:]+", "_", name)
    return name or "download"
```

### add_download (BUG-002)
```python
def add_download(self, url, dest_path=None, ...):
    validate_url(url)
    auto_filename = dest_path is None
    if dest_path is None:
        parsed = urlparse(url)
        filename = safe_filename(os.path.basename(parsed.path)) if parsed.path else "download"
        # filename could have spaces if URL has spaces
```

### add command in main (BUG-003)
```python
if args.command == "add":
    task = manager.add_download(  # No try-except - crashes on invalid URL
        args.url,
        ...
    )
```

### add-list command in main (BUG-004)
```python
elif args.command == "add-list":
    ...
    task = manager.add_download(url, dest_path=dest, priority=args.priority)
    print(f"Added: {task.url} -> {task.dest_path}")
    added += 1  # Always increments, even when task is duplicate
```

### search_and_add_links (BUG-005, BUG-006)
```python
absolute_links: Set[str] = set()
for link in raw_links:
    link = link.strip()
    if not link:
        continue
    if base_url and not link.startswith(("http://", "https://")):
        link = urljoin(base_url, link)  # This should handle relative URLs
    if link.startswith(("http://", "https://")):
        absolute_links.add(link)  # Only http/https get added
```

## Your Task

1. **Read all the documentation files** to understand the project
2. **Read the relevant code sections** in `dm.py`
3. **Fix each bug** in the code:
   - For BUG-001: Block `..` in safe_filename
   - For BUG-002: Sanitize spaces in filenames
   - For BUG-003: Add try-except around add command
   - For BUG-004: Track duplicates properly in add-list
   - For BUG-005: Fix relative URL handling
   - For BUG-006: Optional - filter by extension
4. **Test your fixes** using the existing test data or running `python3 dm.py <command>`
5. **Verify** that fixes don't break existing functionality

## Important Notes

- Actual downloading was NOT tested - the user confirmed it works
- Focus only on task management and link handling bugs
- After fixing, run `python3 dm.py --version` to verify no syntax errors
- The code is in `/home/rezayov.guest/downloadmanager/dm.py`

## Verification Steps After Fixing

```bash
# Test invalid URL handling
python3 dm.py add "not-a-url"

# Test add-list with duplicates
python3 dm.py add-list test_links.txt  # Should show correct Added/Skipped

# Test search with relative links
python3 dm.py search test_page.html  # Should extract relative links

# List all tasks
python3 dm.py list
```

## Ready to Begin

You have full context. Fix all 6 bugs and ensure the CLI handles edge cases gracefully.