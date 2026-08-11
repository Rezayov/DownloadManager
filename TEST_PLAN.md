# Test Plan — Download Manager

## Purpose

Test the download manager's functionality with emphasis on areas user reported as buggy:
- Adding links (single, batch, search)
- Other options (move, restart, remove, etc.)

**Note:** Tests use imaginary URLs that don't actually exist. Download logic is not tested (user confirms it works). Focus is on **task management logic**.

---

## Test Data

Imaginary download links are stored in:
- `test_links.txt` — Simple URL list for `add-list` command
- `test_links_with_options.txt` — URLs with inline options (if supported)

---

## Test Cases

### Group 1: Adding Downloads

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T1.1 | Add single valid URL | `dm add https://example.com/file1.zip` | Task added with auto-generated filename | Clean state |
| T1.2 | Add single URL with custom output | `dm add https://example.com/file2.zip -o /tmp/custom.zip` | Task added with specified path | Clean state |
| T1.3 | Add same URL twice | `dm add https://example.com/file1.zip` (twice) | Second add should warn and return existing task | After T1.1 |
| T1.4 | Add URL with priority | `dm add https://example.com/urgent.zip -p 1` | Task added with priority 1 (higher) | Clean state |
| T1.5 | Add URL with checksum | `dm add https://example.com/file.zip --checksum abc123 --algo sha256` | Task stored with checksum info | Clean state |
| T1.6 | Add invalid URL | `dm add not-a-valid-url` | Should reject with validation error | Clean state |
| T1.7 | Add URL with http scheme | `dm add http://example.com/file.zip` | Should accept (both http/https valid) | Clean state |

### Group 2: Batch Adding (add-list)

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T2.1 | Add multiple URLs from file | `dm add-list test_links.txt` | All valid URLs added, skipped count shown | Create test_links.txt |
| T2.2 | Add-list with output-dir | `dm add-list test_links.txt -o /tmp/downloads` | All files saved to specified directory | After T2.1 |
| T2.3 | Add-list with priority | `dm add-list test_links.txt -p 3` | All tasks get priority 3 | After T2.1 |
| T2.4 | Add-list with comments | Add lines starting with # in file | Comments should be skipped | Create file with comments |
| T2.5 | Add-list nonexistent file | `dm add-list nonexistent.txt` | Error message displayed | N/A |
| T2.6 | Add-list empty file | `dm add-list empty.txt` | Should report Added: 0, Skipped: 0 | Create empty file |

### Group 3: Search and Add Links

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T3.1 | Search local HTML file | `dm search test_page.html` | Extract and add all http/https links | Create HTML file with links |
| T3.2 | Search with output-dir | `dm search test_page.html -o /tmp/downloads` | Links added with specified output dir | After T3.1 |
| T3.3 | Search with priority | `dm search test_page.html -p 1` | All found links get priority 1 | After T3.1 |
| T3.4 | Search URL (if mock available) | `dm search https://example.com/page.html` | Fetch and extract links | Network available? |
| T3.5 | Search nonexistent file | `dm search noexist.html` | Error: File not found | N/A |

### Group 4: List and Status

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T4.1 | List all tasks | `dm list` | Shows all tasks with indices | After T1.1, T1.2, T1.4 |
| T4.2 | List only active | `dm list --active` | Shows only running tasks | None should be active |
| T4.3 | List only pending | `dm list --pending` | Shows only pending tasks | After previous adds |
| T4.4 | List only completed | `dm list --completed` | Shows completed tasks | None should be completed |
| T4.5 | List only failed | `dm list --failed` | Shows failed tasks | None should be failed |
| T4.6 | Status command | `dm status` | Shows count summary | After T4.1 |
| T4.7 | List sort by name | `dm list --sort name` | Tasks sorted alphabetically | After T1.1, T1.2 |
| T4.8 | List sort by size | `dm list --sort size` | Tasks sorted by total_size | After T1.1, T1.2 |
| T4.9 | List sort by url | `dm list --sort url` | Tasks sorted by URL | After T1.1, T1.2 |

### Group 5: Move Operations

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T5.1 | Move single task to front | `dm move 3 1` | Task at index 3 moves to position 1 | Need 5+ pending tasks |
| T5.2 | Move single task to end | `dm move 1 5` | Task at index 1 moves to position 5 | After T5.1 |
| T5.3 | Move range to front | `dm move 1-2 1` | Tasks 1-2 move to front (order preserved) | Need 5+ pending tasks |
| T5.4 | Move multiple to middle | `dm move 1-2 3` | Tasks 1-2 move before position 3 | After T5.3 |
| T5.5 | Move with exclusion | `dm move 1-5~2 1` | Move 1,3,4,5 to front | Need 5+ tasks |
| T5.6 | Move invalid index | `dm move 99 1` | Error: no matching tasks | N/A |
| T5.7 | Move to invalid position | `dm move 1 99` | Should clamp to max position | After T5.1 |
| T5.8 | Move only pending | `dm move 1 1` when task 1 is running | Should only consider pending tasks | Need a running task |

### Group 6: Remove Operations

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T6.1 | Remove single task | `dm remove 1` | Task at index 1 removed | After T5.1 |
| T6.2 | Remove without delete-file | `dm remove 2` then check file | File should still exist | Add task with known file |
| T6.3 | Remove with delete-file | `dm remove --delete-file 3` | Task removed AND file deleted | Add task with known file |
| T6.4 | Remove range | `dm remove 1-3` | Tasks 1,2,3 removed | Need 3+ tasks |
| T6.5 | Remove all with confirm | `dm remove` (answer Y) | All tasks removed after Y | After T6.4 |
| T6.6 | Remove cancel | `dm remove` (answer N) | No tasks removed | After T6.5 setup |
| T6.7 | Remove invalid index | `dm remove 99` | Error: index out of range | N/A |

### Group 7: Restart Operations

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T7.1 | Restart single task | `dm restart 1` | Task 1 reset and re-queued | Need a completed/failed task |
| T7.2 | Restart range | `dm restart 1-2` | Tasks 1 and 2 reset and re-queued | Need 2+ tasks |
| T7.3 | Restart default (latest) | `dm restart` (no pattern) | Restarts highest index task | After T7.1 |
| T7.4 | Restart invalid index | `dm restart 99` | Error message, no change | N/A |

### Group 8: Run Operations

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T8.1 | Run all pending | `dm run` | Processes all pending tasks | Need pending tasks |
| T8.2 | Run specific pattern | `dm run 1-3` | Only tasks 1-3 processed | Need 5+ pending |
| T8.3 | Run with no pending | `dm run` | Message: No pending/failed tasks | Remove all tasks |
| T8.4 | Run with speed limit | `dm run --speed-limit 1000` | Speed should be throttled | Need pending tasks |
| T8.5 | Run with max concurrent | `dm run --max-concurrent 2` | Max 2 concurrent downloads | Need 5+ pending |

### Group 9: Failures Management

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T9.1 | Show failures | `dm failures` | Lists all failed links | Need failed tasks |
| T9.2 | Retry failures | `dm failures --retry` | Failed tasks moved to pending | After T9.1 |
| T9.3 | Clear failure log | `dm failures --clear` | Log file deleted | After T9.2 |

### Group 10: Export

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T10.1 | Export to text | `dm export output.txt` | One URL per line | Need tasks |
| T10.2 | Export to CSV | `dm export output.csv --csv` | CSV with headers | Need tasks |
| T10.3 | Export no tasks | Export from empty state | Message: No tasks to export | Remove all tasks |

### Group 11: Configuration

| ID | Test | Command | Expected Behavior | Pre-conditions |
|----|------|---------|------------------|----------------|
| T11.1 | Custom config file | `dm run --config custom.yaml` | Uses settings from file | Create custom config |
| T11.2 | Env override | `DM_MAX_CONCURRENT=8 dm run` | Environment overrides file | Set env var |
| T11.3 | CLI override | `dm run --max-concurrent 1` | CLI overrides all | Any state |

---

## Execution Order

### Phase 1: Setup
1. Create `test_links.txt` with imaginary URLs
2. Create `test_page.html` with embedded links
3. Ensure clean state (remove state.json if exists)

### Phase 2: Add Tests (T1.*, T2.*)
Run add-related tests. Check state after each.

### Phase 3: Search Tests (T3.*)
Run search command tests.

### Phase 4: List/Status Tests (T4.*)
Run list and status commands to verify state.

### Phase 5: Move Tests (T5.*)
Run move tests. **CRITICAL: Check order preservation**

### Phase 6: Remove Tests (T6.*)
Run remove tests.

### Phase 7: Restart Tests (T7.*)
Run restart tests.

### Phase 8: Run Tests (T8.*)
Skipped (actual downloads). Just verify pattern matching works.

### Phase 9: Failures Tests (T9.*)
Run failures tests.

### Phase 10: Export Tests (T10.*)
Run export tests.

### Phase 11: Config Tests (T11.*)
Test configuration hierarchy.

---

## Success Criteria

1. All add operations complete without errors
2. List shows correct indices after all operations
3. Move preserves relative order when moving multiple tasks
4. Remove correctly deletes tasks and optionally files
5. Restart correctly resets task state
6. Pattern parsing handles ranges, commas, and exclusions correctly
7. Configuration hierarchy works (CLI > ENV > file > defaults)

---

## Bug Reporting Format

For each bug found:

```markdown
## BUG-[ID]: [Short Title]

**Test Case:** T-X.Y
**Severity:** Critical / High / Medium / Low
**Description:** [What happened]
**Expected:** [What should happen]
**Actual:** [What actually happened]
**Command Used:** [Full command]
**State:** [Relevant state before/after]
**Code Location:** [File:Line if identified]
**Fix Suggestion:** [Optional]
```