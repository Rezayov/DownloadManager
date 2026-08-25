#!/usr/bin/env python3
"""
Tests for:
  1. `dm search --pattern REGEX` / `--exclude-pattern REGEX`
  2. default download directory = caller's current working directory

Run with:  uv run python3 test_search_flags.py
"""

import os
import subprocess
import sys
import tempfile
from pathlib import Path

DM_PY = str(Path(__file__).resolve().parent / "dm.py")

HTML = """<html><body>
<a href="http://media.test/videos/video.mp4">a</a>
<a href="http://media.test/videos/video_1080p.mp4">b</a>
<a href="http://media.test/files/backup.zip">c</a>
<a href="http://media.test/images/thumb.png">d</a>
<a href="http://media.test/watch/download?id=42">e</a>
</body></html>
"""

results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))


def dm(args, cwd, env_extra=None):
    """Run dm isolated to `cwd`: fresh state per call so cases never collide."""
    env = {
        **os.environ,
        "DM_LOG_DIR": os.path.join(cwd, "_logs"),
        "DM_STATE_FILE": os.path.join(cwd, "_state", "state.json"),
        "DM_FAILED_LOG": os.path.join(cwd, "_failed.txt"),
        # NOTE: DM_DOWNLOAD_DIR deliberately NOT set by default
    }
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, DM_PY, *args],
        capture_output=True, text=True, env=env, cwd=cwd, timeout=60,
    )


def added_urls(proc):
    return {ln.split("->")[0].split()[1] for ln in proc.stdout.splitlines() if ln.startswith("Added:")}


def added_dests(proc):
    return {ln.split("->")[1].strip() for ln in proc.stdout.splitlines() if ln.startswith("Added:")}


def sandbox(root):
    d = Path(tempfile.mkdtemp(prefix="case-", dir=root))
    (d / "page.html").write_text(HTML)
    return d


def main():
    tmp = tempfile.mkdtemp(prefix="dm-search-test-")

    # ---------- regex flags ----------
    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html")], cwd=str(s))
    check("R0 baseline adds 4 download-ext links", len(added_urls(r)) == 4, r.stdout)

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--pattern", r"\.mp4$"], cwd=str(s))
    urls = added_urls(r)
    check(
        "R1 --pattern keeps only .mp4",
        len(urls) == 2 and all(u.endswith(".mp4") for u in urls),
        f"{urls} | {r.stdout}{r.stderr}",
    )

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--exclude-pattern", "(backup|thumb)"], cwd=str(s))
    urls = added_urls(r)
    check(
        "R2 --exclude-pattern drops matches",
        len(urls) == 2 and all(".mp4" in u for u in urls),
        f"{urls} | {r.stdout}{r.stderr}",
    )

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--pattern", "download", "--no-filter"], cwd=str(s))
    urls = added_urls(r)
    check(
        "R3 pattern+--no-filter catches extension-less link",
        any("watch/download?id=42" in u for u in urls),
        f"{urls} | {r.stdout}",
    )

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--pattern", "("], cwd=str(s))
    check("R4 invalid regex -> clean error", "Invalid regex pattern" in r.stdout + r.stderr)

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--pattern", r"watch\?id="], cwd=str(s))
    check(
        "R5 pattern respects extension filter (combined)",
        len(added_urls(r)) == 0,
        r.stdout,
    )

    # ---------- cwd default download dir ----------
    s = sandbox(tmp)
    r = dm(["add", "http://host-one.test/files/report.pdf"], cwd=str(s))
    expected = os.path.realpath(str(s / "report.pdf"))
    got = next(iter(added_dests(r)), "")
    check(
        "C1 default dest = current working directory",
        os.path.realpath(got) == expected,
        f"{got} vs {expected} | {r.stdout}{r.stderr}",
    )

    s = sandbox(tmp)
    r = dm(["add", "http://host-two.test/files/other.zip", "-o", str(s / "exact.bin")], cwd=str(s))
    got = next(iter(added_dests(r)), "")
    check("C2 -o stays an exact file path", got == str(s / "exact.bin"), f"{got} | {r.stdout}")

    s = sandbox(tmp)
    envdl = Path(tempfile.mkdtemp(prefix="env-", dir=tmp))
    r = dm(["add", "http://host-three.test/files/three.tar.gz"], cwd=str(s), env_extra={"DM_DOWNLOAD_DIR": str(envdl)})
    got = next(iter(added_dests(r)), "")
    check("C3 DM_DOWNLOAD_DIR overrides cwd default", os.path.realpath(got) == os.path.realpath(str(envdl / "three.tar.gz")), f"{got} | {r.stdout}")

    s = sandbox(tmp)
    r = dm(["add", "http://host-four.test/files/four.bin", "--download-dir", str(s / "flagged")], cwd=str(s))
    got = next(iter(added_dests(r)), "")
    check(
        "C4 --download-dir creates dir and appends filename",
        got == os.path.join(str(s / "flagged"), "four.bin"),
        f"{got} | {r.stdout}{r.stderr}",
    )

    s = sandbox(tmp)
    r = dm(["search", str(s / "page.html"), "--pattern", r"\.zip$", "--download-dir", str(s / "zips")], cwd=str(s))
    got = next(iter(added_dests(r)), "")
    check(
        "C5 search --download-dir lands in that dir",
        got == os.path.join(str(s / "zips"), "backup.zip"),
        f"{got} | {r.stdout}{r.stderr}",
    )

    s = sandbox(tmp)
    dm(["add", "http://host-five.test/files/x.pdf"], cwd=str(s))
    stray_state = list(Path(s).glob("**/state.json"))
    check("C6 central state stays out of cwd", all("_state" in str(p) or "_logs" in str(p) for p in stray_state), str(stray_state))

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
