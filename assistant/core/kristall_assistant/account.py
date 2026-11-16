# SPDX-License-Identifier: GPL-3.0-or-later
"""kristall-assistant-account: the machinery behind "Sign in with Claude".

Every command prints JSON lines on stdout (one object per line) so the Setup
Assistant can show progress; the last line is always ``{"event": "result", …}``.

    status                         is the CLI installed, recent enough, signed in?
    install [--channel C]          install Claude Code for this user with Anthropic's official installer
    update                         update the installed CLI (``claude update``)
    login [--console]              start "Sign in with Claude"; emits open_url / need_code events.
                                   A code typed by the owner is passed on stdin, one line,
                                   either the bare code or {"code": "…"}.
    logout                         sign out

We never read or store the owner's credentials: the CLI does the sign-in
itself and keeps its tokens where it always does.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import socket
import sys
import tempfile
import urllib.error
import urllib.request

from .brain import cli as climod
from .config import Paths
from .errors import ERRORS

INSTALLER_URL = os.environ.get("KRISTALL_CLAUDE_INSTALLER_URL", "https://claude.ai/install.sh")
ANSI = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]|\x1b\][^\x07]*\x07")
URL_RE = re.compile(r"https://[^\s\"'<>]+")


def out(**ev) -> None:
    sys.stdout.write(json.dumps(ev, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def result(ok: bool, status: dict | None = None, code: str | None = None, detail: str = "") -> int:
    ev: dict = {"event": "result", "ok": ok}
    if status is not None:
        ev["status"] = status
    if code:
        spec = ERRORS.get(code)
        ev["error"] = {"code": code, "message": {"de": spec.de.format(when="").strip(), "en": spec.en.format(when="").strip()}
                       if spec else {"de": detail, "en": detail}}
        if detail:
            ev["error"]["detail"] = detail[:300]
    out(**ev)
    return 0 if ok else 1


def notify_daemon() -> None:
    """Tell a running daemon to re-check the sign-in state (best effort)."""
    try:
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
            s.settimeout(1.0)
            s.connect(str(Paths.from_env().socket))
            s.sendall(b'{"type":"account_changed"}\n')
    except OSError:
        pass


async def stream(argv: list[str], *, stdin_lines: asyncio.Queue | None = None, timeout: float = 900,
                 on_line=None, env: dict | None = None) -> int:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdin=asyncio.subprocess.PIPE if stdin_lines else asyncio.subprocess.DEVNULL,
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
        env=env or climod.child_env(), cwd=os.path.expanduser("~"))

    async def feed():
        while True:
            line = await stdin_lines.get()
            if line is None or proc.stdin is None:
                break
            proc.stdin.write((line + "\n").encode())
            await proc.stdin.drain()

    feeder = asyncio.ensure_future(feed()) if stdin_lines else None
    buf = b""

    async def read():
        nonlocal buf
        while True:
            chunk = await proc.stdout.read(1024)
            if not chunk:
                break
            buf += chunk
            # prompts like "Paste code here if prompted >" end without a newline
            while b"\n" in buf or b"> " in buf[-3:]:
                if b"\n" in buf:
                    line, buf = buf.split(b"\n", 1)
                else:
                    line, buf = buf, b""
                text = ANSI.sub("", line.decode(errors="replace")).strip()
                if text:
                    out(event="log", line=text[:500])
                    if on_line:
                        on_line(text)
    try:
        await asyncio.wait_for(asyncio.gather(read(), proc.wait()), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        return 124
    finally:
        if feeder:
            feeder.cancel()
    return proc.returncode or 0


async def cmd_status() -> int:
    st = await climod.check()
    out(event="status", **st.as_dict())
    return result(True, st.as_dict())


async def cmd_install(channel: str | None) -> int:
    if os.geteuid() == 0 and not os.environ.get("KRISTALL_ASSISTANT_TEST_ALLOW_ROOT"):
        return result(False, None, "internal", "refusing to install as root; run as the owner")
    out(event="progress", stage="download_installer", percent=5)
    tmpdir = tempfile.mkdtemp(prefix="kristall-claude-install-")
    script = os.path.join(tmpdir, "install.sh")
    try:
        req = urllib.request.Request(INSTALLER_URL, headers={"User-Agent": "kristall-assistant-account"})
        with urllib.request.urlopen(req, timeout=60) as r, open(script, "wb") as f:
            data = r.read()
            if not data.startswith(b"#!"):
                return result(False, None, "service_error", "installer download returned unexpected content")
            f.write(data)
    except (urllib.error.URLError, OSError) as e:
        return result(False, None, "offline", str(e))
    out(event="progress", stage="running_installer", percent=20)
    argv = ["bash", script] + ([channel] if channel else [])
    rc = await stream(argv, timeout=1200)
    shutil.rmtree(tmpdir, ignore_errors=True)
    out(event="progress", stage="verifying", percent=90)
    st = await climod.check()
    notify_daemon()
    if rc != 0 or st.status == "cli_missing":
        return result(False, st.as_dict(), "service_error", f"installer exit code {rc}")
    out(event="progress", stage="done", percent=100)
    return result(True, st.as_dict())


async def cmd_update() -> int:
    path = climod.find_cli()
    if not path:
        return result(False, None, "cli_missing")
    out(event="progress", stage="updating", percent=10)
    env = climod.child_env()
    env.pop("DISABLE_AUTOUPDATER", None)
    rc = await stream([path, "update"], timeout=1200, env=env)
    st = await climod.check()
    notify_daemon()
    if rc != 0:
        return result(False, st.as_dict(), "service_error", f"claude update exit code {rc}")
    out(event="progress", stage="done", percent=100)
    return result(st.status in ("ready", "signed_out"), st.as_dict(),
                  None if st.status in ("ready", "signed_out") else "cli_outdated")


async def cmd_login(console: bool, open_browser: bool) -> int:
    path = climod.find_cli()
    if not path:
        return result(False, None, "cli_missing")
    st = await climod.check()
    if st.status == "cli_outdated":
        return result(False, st.as_dict(), "cli_outdated")
    q: asyncio.Queue = asyncio.Queue()
    seen: set[str] = set()

    def on_line(text: str) -> None:
        for url in URL_RE.findall(text):
            if url not in seen:
                seen.add(url)
                out(event="open_url", url=url)
                if open_browser and shutil.which("xdg-open"):
                    os.spawnlp(os.P_NOWAIT, "xdg-open", "xdg-open", url)
        if "code" in text.lower() and ("paste" in text.lower() or "enter" in text.lower()):
            out(event="need_code")

    async def read_stdin():
        loop = asyncio.get_running_loop()
        while True:
            line = await loop.run_in_executor(None, sys.stdin.readline)
            if not line:
                break
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                line = str(obj.get("code", "")) if isinstance(obj, dict) else line
            except ValueError:
                pass
            if line:
                out(event="progress", stage="code_received")
                await q.put(line)

    reader = asyncio.ensure_future(read_stdin())
    out(event="progress", stage="waiting_for_browser")
    argv = [path, "auth", "login", "--console" if console else "--claudeai"]
    rc = await stream(argv, stdin_lines=q, timeout=900, on_line=on_line)
    reader.cancel()
    st = await climod.check()
    notify_daemon()
    if rc == 0 and st.logged_in:
        return result(True, st.as_dict())
    return result(False, st.as_dict(), "not_signed_in", f"login exit code {rc}")


async def cmd_logout() -> int:
    path = climod.find_cli()
    if not path:
        return result(False, None, "cli_missing")
    rc = await stream([path, "auth", "logout"], timeout=60)
    st = await climod.check()
    notify_daemon()
    return result(rc == 0, st.as_dict(), None if rc == 0 else "service_error")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kristall-assistant-account", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command", choices=["status", "install", "update", "login", "logout"])
    p.add_argument("--channel", choices=["stable", "latest"])
    p.add_argument("--console", action="store_true", help="sign in with an Anthropic Console account instead")
    p.add_argument("--open", action="store_true", help="also open the sign-in page with xdg-open")
    a = p.parse_args(argv)
    try:
        if a.command == "status":
            return asyncio.run(cmd_status())
        if a.command == "install":
            return asyncio.run(cmd_install(a.channel))
        if a.command == "update":
            return asyncio.run(cmd_update())
        if a.command == "login":
            return asyncio.run(cmd_login(a.console, a.open))
        return asyncio.run(cmd_logout())
    except KeyboardInterrupt:
        return result(False, None, "internal", "interrupted")


if __name__ == "__main__":
    sys.exit(main())
