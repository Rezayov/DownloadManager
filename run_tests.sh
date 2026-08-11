#!/bin/bash
# Test script for download manager

DM="python3 /home/rezayov.guest/downloadmanager/dm.py"
RESULTS="/home/rezayov.guest/downloadmanager/test_results.md"

log_test() {
    echo "## $1" >> "$RESULTS"
    echo '```' >> "$RESULTS"
    echo "$2" >> "$RESULTS"
    echo '```' >> "$RESULTS"
    echo "" >> "$RESULTS"
}

echo "# Test Results" > "$RESULTS"
echo "" >> "$RESULTS"

# Clean state
rm -f ~/Downloads/Manager/state.json 2>/dev/null

# T1.1: Add single URL
log_test "T1.1: Add single valid URL" "$($DM add https://example-downloads.com/files/document.pdf 2>&1)"

# T1.2: Add with custom output
log_test "T1.2: Add with custom output" "$($DM add https://example-downloads.com/files/image.png -o /tmp/custom_image.png 2>&1)"

# T1.3: Add duplicate URL
log_test "T1.3: Add duplicate URL" "$($DM add https://example-downloads.com/files/document.pdf 2>&1)"

# T1.4: Add with priority
log_test "T1.4: Add with priority 1" "$($DM add https://example-downloads.com/files/urgent.zip -p 1 2>&1)"

# T1.5: Add with checksum
log_test "T1.5: Add with checksum" "$($DM add https://example-downloads.com/files/archive.zip --checksum abc123 --algo sha256 2>&1)"

# T1.6: Add invalid URL
log_test "T1.6: Add invalid URL" "$($DM add 'not-a-valid-url' 2>&1)" || true

# List tasks
log_test "List after T1.1-T1.6" "$($DM list 2>&1)"

# T2.1: Add-list from file
log_test "T2.1: Add-list from file" "$($DM add-list /home/rezayov.guest/downloadmanager/test_links.txt 2>&1)"

# List after add-list
log_test "List after add-list" "$($DM list 2>&1)"

# T3.1: Search local HTML file
log_test "T3.1: Search local HTML file" "$($DM search /home/rezayov.guest/downloadmanager/test_page.html 2>&1)"

# List after search
log_test "List after search (T3.1)" "$($DM list 2>&1)"

# T5.1: Move single task to front
log_test "T5.1: Move task 5 to position 1" "$($DM move 5 1 2>&1)"

# List after move
log_test "List after T5.1" "$($DM list 2>&1)"

# T5.3: Move range 1-2 to front
log_test "T5.3: Move range 1-2 to front" "$($DM move 1-2 1 2>&1)"

# List after range move
log_test "List after T5.3" "$($DM list 2>&1)"

# T5.5: Move with exclusion
log_test "T5.5: Move with exclusion pattern 1-5~2" "$($DM move 1-5~2 1 2>&1)"

# List after exclusion move
log_test "List after T5.5" "$($DM list 2>&1)"

# T6.1: Remove single task
log_test "T6.1: Remove task at index 1" "echo 'y' | $($DM remove 1 2>&1)"

# T6.4: Remove range
log_test "T6.4: Remove range 1-2" "echo 'y' | $($DM remove 1-2 2>&1)"

# List after removes
log_test "List after T6.1, T6.4" "$($DM list 2>&1)"

# T9.1: Show failures (should be empty)
log_test "T9.1: Show failures" "$($DM failures 2>&1)"

# T10.1: Export to text
log_test "T10.1: Export to text" "$($DM export /tmp/exported.txt 2>&1)"

# T10.2: Export to CSV
log_test "T10.2: Export to CSV" "$($DM export /tmp/exported.csv --csv 2>&1)"

# Show exported content
if [ -f /tmp/exported.txt ]; then
    log_test "Exported text file content" "cat /tmp/exported.txt"
fi

# T4.6: Status
log_test "T4.6: Status command" "$($DM status 2>&1)"

echo "Tests complete. Results in $RESULTS"
