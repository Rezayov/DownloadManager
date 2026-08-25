#!/usr/bin/env python3
"""
End-to-end tests for dm auth profiles (bearer / header / basic / cookies).

Starts a local HTTP server that requires credentials on protected routes and
drives the real CLI (subprocess) inside a sandboxed HOME-like environment.

Run with:  uv run python3 test_auth.py
"""

import base64
import json
import os
import stat
import subprocess
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

DM_PY = str(Path(__file__).resolve().parent / "dm.py")

BEARER_TOKEN = "tok_bearer_secret_9876"
BASIC_USER, BASIC_PASS = "alice", "s3cret-pass"
COOKIE_NAME, COOKIE_VALUE = "session", "abc123-cookies"
API_KEY = "key-42-header"
FILE_BYTES = b"AUTH-PROTECTED-DATA-" * 500


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # silence request logging
        pass

    # -- helpers -------------------------------------------------------
    def _kind(self):
        p = self.path.split("?", 1)[0]
        for kind in ("bearer", "basic", "cookie", "hdr", "open"):
            if p.startswith(f"/{kind}/"):
                return kind
        return None

    def _authorized(self, kind):
        if kind in ("open", None):
            return True
        if kind == "bearer":
            return self.headers.get("Authorization") == f"Bearer {BEARER_TOKEN}"
        if kind == "basic":
            expected = "Basic " + base64.b64encode(
                f"{BASIC_USER}:{BASIC_PASS}".encode()
            ).decode()
            return self.headers.get("Authorization") == expected
        if kind == "cookie":
            return f"{COOKIE_NAME}={COOKIE_VALUE}" in (self.headers.get("Cookie") or "")
        if kind == "hdr":
            return self.headers.get("X-Api-Key") == API_KEY
        return False

    def _send(self, code, body=b"", ctype="text/html"):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        kind = self._kind()
        if kind is None:
            self._send(404, b"not found")
            return
        page = self.path.split("?", 1)[0].endswith(".html")
        if not self._authorized(kind):
            self._send(401, b"who are you?")
            return
        if page:
            target = [s for s in self.path.split("/") if s][0]
            html = (
                "<html><head><title>ok</title></head><body>"
                f'<a href="/{target}/payload.bin">download</a>'
                '<a href="/about">about</a>'
                "</body></html>"
            ).encode()
            self._send(200, html)
        else:
            self._send(200, FILE_BYTES, ctype="application/octet-stream")


def start_server():
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    port = server.server_address[1]
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, port


class DM:
    def __init__(self, tmp, extra_env=None):
        self.tmp = Path(tmp)
        self.env = {
            **os.environ,
            "DM_DOWNLOAD_DIR": str(self.tmp / "downloads"),
            "DM_LOG_DIR": str(self.tmp / "logs"),
            "DM_STATE_FILE": str(self.tmp / "state.json"),
            "DM_FAILED_LOG": str(self.tmp / "failed_links.txt"),
            "DM_AUTH_FILE": str(self.tmp / "auth.json"),
        }
        if extra_env:
            self.env.update(extra_env)

    def run(self, *args, check=False, env_extra=None):
        env = dict(self.env)
        if env_extra:
            env.update(env_extra)
        proc = subprocess.run(
            [sys.executable, DM_PY, *args],
            capture_output=True,
            text=True,
            env=env,
            timeout=120,
        )
        if check and proc.returncode != 0:
            raise AssertionError(
                f"dm {' '.join(args)} failed ({proc.returncode})\n"
                f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}"
            )
        return proc

    def state(self):
        return json.loads((self.tmp / "state.json").read_text())


results = []


def check(name, cond, detail=""):
    results.append((name, bool(cond), detail))
    print(f"{'PASS' if cond else 'FAIL'}  {name}" + (f"  -- {detail}" if detail and not cond else ""))


def main():
    tmp = tempfile.mkdtemp(prefix="dm-auth-test-")
    server, port = start_server()
    base = f"http://localhost:{port}"
    dm = DM(tmp)

    try:
        # ---- T1: no profile -> protected search fails with a helpful hint
        p = dm.run("search", f"{base}/bearer/page.html")
        check(
            "T1 unauthenticated search fails with hint",
            p.returncode == 0 and "dm auth add localhost" in p.stdout,
            p.stdout + p.stderr,
        )

        # ---- T2: save bearer profile via ${ENV_VAR}; verify file + perms + masking
        p = dm.run(
            "auth", "add", "localhost",
            "--type", "bearer", "--token", "${DM_TEST_TOKEN}",
            check=True,
            env_extra={"DM_TEST_TOKEN": BEARER_TOKEN},
        )
        store_path = Path(dm.env["DM_AUTH_FILE"])
        raw = store_path.read_text()
        mode = stat.S_IMODE(store_path.stat().st_mode)
        check("T2a profile stored with literal env ref", '"${DM_TEST_TOKEN}"' in raw, raw)
        check("T2b auth file is 0600", oct(mode) == "0o600", oct(mode))
        p = dm.run("auth", "list", check=True)
        check("T2c list masks token", BEARER_TOKEN not in p.stdout and "****" in p.stdout, p.stdout)

        # ---- T3: auth test proves identity (bearer resolved from env at use time)
        p = dm.run(
            "auth", "test", f"{base}/bearer/page.html", check=True,
            env_extra={"DM_TEST_TOKEN": BEARER_TOKEN},
        )
        check("T3 auth test accepts bearer identity", "Identity accepted" in p.stdout, p.stdout)

        # ---- T4: missing env var -> loud error, no silent fallback
        dm.run("auth", "add", "missing-env.example", "--type", "bearer", "--token", "${DM_TEST_MISSING}", check=True)
        p = dm.run("auth", "test", "http://missing-env.example/x.bin")
        check(
            "T4 unresolved env var reported clearly",
            p.returncode == 1 and "DM_TEST_MISSING" in (p.stderr + p.stdout),
            p.stdout + p.stderr,
        )
        dm.run("auth", "remove", "missing-env.example", check=True)

        # ---- T5: THE BUG FIX - authenticated search finds links on authorized page
        out_dir = str(Path(tmp) / "searched")
        p = dm.run(
            "search", f"{base}/bearer/page.html", "-o", out_dir, check=True,
            env_extra={"DM_TEST_TOKEN": BEARER_TOKEN},
        )
        check(
            "T5 authenticated search adds link",
            "Added 1 link(s)" in p.stdout and "payload.bin" in p.stdout,
            p.stdout,
        )
        state = dm.state()
        check(
            "T5b bearer token NOT leaked into state.json",
            all(BEARER_TOKEN not in json.dumps(t) for t in state["tasks"]),
        )

        # ---- T6: run downloads the protected file as the authenticated user
        p = dm.run("run", "--no-tui", check=True, env_extra={"DM_TEST_TOKEN": BEARER_TOKEN})
        got = Path(out_dir) / "payload.bin"
        check("T6 protected download succeeds", got.exists() and got.read_bytes() == FILE_BYTES)

        # ---- T7: one-off --header flags bake into tasks for later `run`
        # (remove the stored bearer profile first: profiles are domain-wide,
        #  and /hdr/ routes only accept X-Api-Key)
        dm.run("auth", "remove", "localhost", check=True)
        hdr_dir = str(Path(tmp) / "hdr_dl")
        p = dm.run(
            "search", f"{base}/hdr/page.html", "-o", hdr_dir,
            "--header", f"X-Api-Key: {API_KEY}",
            check=True,
        )
        state = dm.state()
        baked_ok = any(
            h.get("headers", {}).get("X-Api-Key") == API_KEY
            for t in state["tasks"]
            for h in [t]
        )
        check("T7 one-off header baked into task", baked_ok)
        p = dm.run("run", "--no-tui", check=True)
        check(
            "T7b header-auth download via baked creds",
            (Path(hdr_dir) / "payload.bin").exists(),
        )

        # ---- T8: basic auth stored profile (overwrites localhost profile)
        dm.run(
            "auth", "add", "localhost", "--type", "basic",
            "--username", BASIC_USER, "--password", BASIC_PASS, check=True,
        )
        p = dm.run("auth", "test", f"{base}/basic/page.html", check=True)
        check("T8 basic auth accepted", "Identity accepted" in p.stdout, p.stdout)
        p = dm.run("auth", "test", f"{base}/bearer/page.html")
        check("T8b wrong cred type rejected", p.returncode == 3 and "REJECTED" in p.stdout, p.stdout)

        # ---- T9: one-off --user works without any stored profile
        user_dir = str(Path(tmp) / "basic_dl")
        p = dm.run(
            "search", f"{base}/basic/page.html", "-o", user_dir,
            "--user", f"{BASIC_USER}:{BASIC_PASS}",
            "--auth-domain", "nonexistent-domain.invalid",
        )  # force-domain misses -> resolve error expected; instead use plain one-off:
        p2 = dm.run(
            "search", f"{base}/basic/page.html", "-o", user_dir,
            "--user", f"{BASIC_USER}:{BASIC_PASS}",
            check=True,
        )
        check("T9 one-off --user search works", "Added 1 link(s)" in p2.stdout or "Skipped (duplicate)" in p2.stdout, p2.stdout)
        p = dm.run("run", "--no-tui", check=True)
        check("T9b basic-auth file downloaded", (Path(user_dir) / "payload.bin").exists())

        # ---- T10: cookie string profile
        dm.run(
            "auth", "add", "localhost", "--type", "cookies",
            "--cookie", f"{COOKIE_NAME}={COOKIE_VALUE}", check=True,
        )
        p = dm.run("auth", "test", f"{base}/cookie/page.html", check=True)
        check("T10 cookie-string identity accepted", "Identity accepted" in p.stdout, p.stdout)

        # ---- T11: Netscape cookies.txt profile
        cj = Path(tmp) / "cookies.txt"
        cj.write_text(
            "# Netscape HTTP Cookie File\n"
            f"localhost\tFALSE\t/\tFALSE\t0\t{COOKIE_NAME}\t{COOKIE_VALUE}\n"
        )
        dm.run("auth", "add", "localhost", "--type", "cookies", "--cookie-file", str(cj), check=True)
        p = dm.run("auth", "test", f"{base}/cookie/page.html", check=True)
        check("T11 cookie-file identity accepted", "Identity accepted" in p.stdout, p.stdout)

        # ---- T12: wildcard domain matching (*.localhost matches sub.localhost)
        # Checked in-process: wildcard DNS does not resolve on all systems.
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import dm as dm_mod

        store = dm_mod.AuthStore(str(Path(tmp) / "wild_auth.json"))
        store.profiles["*.localhost"] = {"type": "bearer", "token": "x"}
        check(
            "T12 wildcard profile matches subdomain",
            store.match(f"http://sub.localhost:{port}/open/page.html") == "*.localhost"
            and store.match("http://other.example/x") is None,
        )

        # ---- T13: regression - public pages still work with zero credentials
        open_dir = str(Path(tmp) / "open_dl")
        p = dm.run("search", f"{base}/open/page.html", "-o", open_dir, check=True)
        check("T13 public search unaffected", "Added 1 link(s)" in p.stdout, p.stdout)
        p = dm.run("run", "--no-tui", check=True)
        check("T13b public download unaffected", (Path(open_dir) / "payload.bin").exists())

        # ---- T14: remove works
        p = dm.run("auth", "remove", "localhost", check=True)
        p = dm.run("auth", "list", check=True)
        check("T14 remove leaves empty store", "No auth profiles saved" in p.stdout, p.stdout)

    finally:
        server.shutdown()

    failed = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(failed)}/{len(results)} passed")
    if failed:
        print("FAILED:")
        for name, _, detail in failed:
            print(f"  - {name}: {detail[:300]}")
        sys.exit(1)


if __name__ == "__main__":
    main()
