# Test Results

## T1.1: Add single valid URL
```
Added: https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf
```

## T1.2: Add with custom output
```
Added: https://example-downloads.com/files/image.png -> /tmp/custom_image.png
```

## T1.3: Add duplicate URL
```
WARNING: URL already exists: https://example-downloads.com/files/document.pdf
Added: https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf
```

## T1.4: Add with priority 1
```
Added: https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip
```

## T1.5: Add with checksum
```
Added: https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip
```

## T1.6: Add invalid URL
```
Traceback (most recent call last):
  File "/home/rezayov.guest/downloadmanager/dm.py", line 1734, in <module>
    main()
  File "/home/rezayov.guest/downloadmanager/dm.py", line 1615, in main
    task = manager.add_download(
           ^^^^^^^^^^^^^^^^^^^^^
  File "/home/rezayov.guest/downloadmanager/dm.py", line 685, in add_download
    validate_url(url)
  File "/home/rezayov.guest/downloadmanager/dm.py", line 375, in validate_url
    raise ValueError(f"Invalid URL: {url}")
ValueError: Invalid URL: not-a-valid-url
```

## List after T1.1-T1.6
```
[1] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[2] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[3] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[4] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
```

## T2.1: Add-list from file
```
WARNING: URL already exists: https://example-downloads.com/files/document.pdf
WARNING: URL already exists: https://example-downloads.com/files/image.png
WARNING: URL already exists: https://example-downloads.com/files/archive.zip
Added: https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf
Added: https://example-downloads.com/files/image.png -> /tmp/custom_image.png
Added: https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip
Added: https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4
Added: https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3
Added: https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe
Added: https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt
Added: https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb
Added: https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm
Added: https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin
Added: https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip

Batch add complete. Added: 11, Skipped: 0
```

## List after add-list
```
[1] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[2] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[3] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[4] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[5] PENDING | https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4 (0 bytes)
[6] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[7] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[8] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[9] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[10] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[11] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[12] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
```

## T3.1: Search local HTML file
```
Added: https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg
Added: https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png
Added: https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4
Added: https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4
Added: https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe
Added: https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe
Added: https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd
Added: https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip
Added: https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip
Added: https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page
Added: https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo

Added 11 link(s).
```

## List after search (T3.1)
```
[1] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[2] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[3] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[4] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[5] PENDING | https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4 (0 bytes)
[6] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[7] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[8] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[9] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[10] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[11] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[12] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
[13] PENDING | https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg (0 bytes)
[14] PENDING | https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png (0 bytes)
[15] PENDING | https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4 (0 bytes)
[16] PENDING | https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4 (0 bytes)
[17] PENDING | https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe (0 bytes)
[18] PENDING | https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe (0 bytes)
[19] PENDING | https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd (0 bytes)
[20] PENDING | https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip (0 bytes)
[21] PENDING | https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip (0 bytes)
[22] PENDING | https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page (0 bytes)
[23] PENDING | https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo (0 bytes)
```

## T5.1: Move task 5 to position 1
```
Moved 1 pending task(s) to position 1.
```

## List after T5.1
```
[1] PENDING | https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4 (0 bytes)
[2] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[3] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[4] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[5] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[6] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[7] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[8] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[9] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[10] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[11] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[12] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
[13] PENDING | https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg (0 bytes)
[14] PENDING | https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png (0 bytes)
[15] PENDING | https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4 (0 bytes)
[16] PENDING | https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4 (0 bytes)
[17] PENDING | https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe (0 bytes)
[18] PENDING | https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe (0 bytes)
[19] PENDING | https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd (0 bytes)
[20] PENDING | https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip (0 bytes)
[21] PENDING | https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip (0 bytes)
[22] PENDING | https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page (0 bytes)
[23] PENDING | https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo (0 bytes)
```

## T5.3: Move range 1-2 to front
```
Moved 2 pending task(s) to position 1.
```

## List after T5.3
```
[1] PENDING | https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4 (0 bytes)
[2] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[3] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[4] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[5] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[6] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[7] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[8] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[9] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[10] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[11] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[12] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
[13] PENDING | https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg (0 bytes)
[14] PENDING | https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png (0 bytes)
[15] PENDING | https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4 (0 bytes)
[16] PENDING | https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4 (0 bytes)
[17] PENDING | https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe (0 bytes)
[18] PENDING | https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe (0 bytes)
[19] PENDING | https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd (0 bytes)
[20] PENDING | https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip (0 bytes)
[21] PENDING | https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip (0 bytes)
[22] PENDING | https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page (0 bytes)
[23] PENDING | https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo (0 bytes)
```

## T5.5: Move with exclusion pattern 1-5~2
```
Moved 4 pending task(s) to position 1.
```

## List after T5.5
```
[1] PENDING | https://example-downloads.com/files/video.mp4 -> /home/rezayov.guest/Downloads/Manager/video.mp4 (0 bytes)
[2] PENDING | https://example-downloads.com/files/document.pdf -> /home/rezayov.guest/Downloads/Manager/document.pdf (0 bytes)
[3] PENDING | https://example-downloads.com/files/image.png -> /tmp/custom_image.png (0 bytes)
[4] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[5] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[6] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[7] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[8] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[9] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[10] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[11] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[12] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
[13] PENDING | https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg (0 bytes)
[14] PENDING | https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png (0 bytes)
[15] PENDING | https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4 (0 bytes)
[16] PENDING | https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4 (0 bytes)
[17] PENDING | https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe (0 bytes)
[18] PENDING | https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe (0 bytes)
[19] PENDING | https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd (0 bytes)
[20] PENDING | https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip (0 bytes)
[21] PENDING | https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip (0 bytes)
[22] PENDING | https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page (0 bytes)
[23] PENDING | https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo (0 bytes)
```

## T6.1: Remove task at index 1
```
echo 'y' | Removed 1 download(s).
```

## T6.4: Remove range 1-2
```
echo 'y' | Removed 2 download(s).
```

## List after T6.1, T6.4
```
[1] PENDING | https://example-downloads.com/files/archive.zip -> /home/rezayov.guest/Downloads/Manager/archive.zip (0 bytes)
[2] PENDING | https://example-downloads.com/files/urgent.zip -> /home/rezayov.guest/Downloads/Manager/urgent.zip (0 bytes)
[3] PENDING | https://example-downloads.com/files/audio.mp3 -> /home/rezayov.guest/Downloads/Manager/audio.mp3 (0 bytes)
[4] PENDING | https://another-site.org/downloads/setup.exe -> /home/rezayov.guest/Downloads/Manager/setup.exe (0 bytes)
[5] PENDING | https://another-site.org/downloads/readme.txt -> /home/rezayov.guest/Downloads/Manager/readme.txt (0 bytes)
[6] PENDING | https://mirror.example.net/repo/package.deb -> /home/rezayov.guest/Downloads/Manager/package.deb (0 bytes)
[7] PENDING | https://mirror.example.net/repo/package.rpm -> /home/rezayov.guest/Downloads/Manager/package.rpm (0 bytes)
[8] PENDING | https://invalid-domain-check.com/file1.bin -> /home/rezayov.guest/Downloads/Manager/file1.bin (0 bytes)
[9] PENDING | https://duplicate-test.com/file duplication test.zip -> /home/rezayov.guest/Downloads/Manager/file duplication test.zip (0 bytes)
[10] PENDING | https://cdn.example.com/audio/background.ogg -> /home/rezayov.guest/Downloads/Manager/background.ogg (0 bytes)
[11] PENDING | https://cdn.example.com/images/logo.png -> /home/rezayov.guest/Downloads/Manager/logo.png (0 bytes)
[12] PENDING | https://cdn.example.com/videos/backup.mp4 -> /home/rezayov.guest/Downloads/Manager/backup.mp4 (0 bytes)
[13] PENDING | https://cdn.example.com/videos/intro.mp4 -> /home/rezayov.guest/Downloads/Manager/intro.mp4 (0 bytes)
[14] PENDING | https://downloads.example.com/software/installer_v1.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v1.0.exe (0 bytes)
[15] PENDING | https://downloads.example.com/software/installer_v2.0.exe -> /home/rezayov.guest/Downloads/Manager/installer_v2.0.exe (0 bytes)
[16] PENDING | https://example.com/../etc/passwd -> /home/rezayov.guest/Downloads/Manager/passwd (0 bytes)
[17] PENDING | https://example.com/file with spaces.zip -> /home/rezayov.guest/Downloads/Manager/file with spaces.zip (0 bytes)
[18] PENDING | https://example.com/file%20encoded.zip -> /home/rezayov.guest/Downloads/Manager/file encoded.zip (0 bytes)
[19] PENDING | https://external-site.com/page -> /home/rezayov.guest/Downloads/Manager/page (0 bytes)
[20] PENDING | https://github.com/project/repo -> /home/rezayov.guest/Downloads/Manager/repo (0 bytes)
```

## T9.1: Show failures
```
No failure log found.
```

## T10.1: Export to text
```
Exported 20 task(s) to /tmp/exported.txt
```

## T10.2: Export to CSV
```
Exported 20 task(s) to /tmp/exported.csv
```

## Exported text file content
```
cat /tmp/exported.txt
```

## T4.6: Status command
```
Active: 0, Pending: 20, Failed: 0, Completed: 0
```

