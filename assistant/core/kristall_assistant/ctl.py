# SPDX-License-Identifier: GPL-3.0-or-later
"""kristall-assistant-ctl: small control client for testing the daemon.

    kristall-assistant-ctl status                 hello + snapshot
    kristall-assistant-ctl watch [--levels]       print every event
    kristall-assistant-ctl ask "Frage" [--speak]  ask by text, stream the reply, answer permission prompts
    kristall-assistant-ctl listen                 ask by voice
    kristall-assistant-ctl cancel | stop-speaking | end-listening | new-conversation | prepare
    kristall-assistant-ctl allow REQUEST_ID [--always] | deny REQUEST_ID
    kristall-assistant-ctl cursor X Y [--label L] [--pulse click] [--hide]   publish an agent cursor (as a tool)
    kristall-assistant-ctl demo-error CODE | demo-account STATUS               (daemon in --demo only)
    kristall-assistant-ctl send '{"type": ...}'   send raw JSON
"""
from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import time

from .config import Paths


class Conn:
    def __init__(self, path: str, retries: int = 0):
        self.s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        delay = 0.2
        for i in range(retries + 1):
            try:
                self.s.connect(path)
                break
            except (FileNotFoundError, ConnectionRefusedError):
                if i == retries:
                    raise
                time.sleep(delay)
                delay = min(delay * 2, 3.0)
        self.f = self.s.makefile("rb")
        self.n = 0

    def send(self, msg: dict) -> int:
        self.n += 1
        msg = dict(msg, id=self.n)
        self.s.sendall((json.dumps(msg, ensure_ascii=False) + "\n").encode())
        return self.n

    def recv(self) -> dict | None:
        line = self.f.readline()
        return json.loads(line) if line else None

    def until_ack(self, mid: int) -> dict:
        while True:
            m = self.recv()
            if m is None:
                raise ConnectionError("daemon closed the connection")
            if m.get("type") == "ack" and m.get("id") == mid:
                return m


def _txt(d, lang="de"):
    return d.get(lang) or d.get("de") if isinstance(d, dict) else str(d)


def run_turn(c: Conn, msg: dict, as_json: bool, lang: str) -> int:
    mid = c.send(msg)
    ack = c.until_ack(mid)
    if not ack.get("ok"):
        print(json.dumps(ack, ensure_ascii=False))
        return 2
    tid = ack["turn_id"]
    rc = 0
    while True:
        m = c.recv()
        if m is None:
            return 3
        if m.get("turn_id") not in (tid, None) and m.get("type") != "state":
            continue
        if as_json:
            print(json.dumps(m, ensure_ascii=False), flush=True)
        t = m["type"]
        if t == "transcript" and not as_json:
            print(("» " if m["final"] else "… ") + m["text"], file=sys.stderr, flush=True)
        elif t == "reply_delta" and not as_json:
            print(m["text"], end="", flush=True)
        elif t == "activity" and not as_json and m["status"] == "running":
            print(f"\n  [{_txt(m['text'], lang)}]", file=sys.stderr, flush=True)
        elif t == "error":
            if not as_json:
                print(f"\n! {m['code']}: {_txt(m['message'], lang)}", file=sys.stderr)
            rc = 1
        elif t == "permission_request":
            if not as_json:
                print(f"\n? {_txt(m['question'], lang)}\n  {m.get('explanation','')}\n  ({m['technical']})",
                      file=sys.stderr)
            if sys.stdin.isatty():   # otherwise leave it to another client (the interface)
                r = input("  [j]a / [i]mmer / [n]ein: ").strip().lower()
                ans = {"j": "allow_once", "y": "allow_once", "i": "allow_always", "a": "allow_always"}.get(r[:1], "deny")
                c.send({"type": "permission_reply", "request_id": m["request_id"], "decision": ans})
        elif t == "turn_finished":
            if not as_json:
                print()
            return rc


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="kristall-assistant-ctl", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("command")
    p.add_argument("args", nargs="*")
    p.add_argument("--json", action="store_true", help="print raw events")
    p.add_argument("--levels", action="store_true")
    p.add_argument("--speak", action="store_true")
    p.add_argument("--always", action="store_true")
    p.add_argument("--label")
    p.add_argument("--pulse")
    p.add_argument("--hide", action="store_true")
    p.add_argument("--socket", default=str(Paths.from_env().socket))
    p.add_argument("--lang", default=os.environ.get("LANG", "de")[:2])
    a = p.parse_args(argv)
    try:
        c = Conn(a.socket, retries=3)
    except OSError as e:
        print(f"cannot connect to {a.socket}: {e}", file=sys.stderr)
        return 4
    hello, snap = c.recv(), c.recv()
    cmd = a.command
    simple = {"cancel": "cancel", "stop-speaking": "stop_speaking", "end-listening": "end_listening",
              "new-conversation": "new_conversation", "prepare": "prepare", "account-changed": "account_changed"}
    if cmd == "status":
        print(json.dumps({"hello": hello, "snapshot": snap}, ensure_ascii=False, indent=1))
        return 0
    if cmd in simple:
        ack = c.until_ack(c.send({"type": simple[cmd]}))
        return 0 if ack.get("ok") else 1
    if cmd == "watch":
        c.send({"type": "hello", "client": "ctl", "role": "control", "subscribe": ["levels"] if a.levels else []})
        try:
            while (m := c.recv()) is not None:
                if m.get("type") != "ack":
                    print(json.dumps(m, ensure_ascii=False), flush=True)
        except KeyboardInterrupt:
            pass
        return 0
    if cmd == "ask":
        return run_turn(c, {"type": "invoke", "mode": "text", "text": " ".join(a.args), "source": "ctl",
                            "speak": a.speak}, a.json, a.lang)
    if cmd == "listen":
        return run_turn(c, {"type": "invoke", "mode": "voice", "source": "ctl"}, a.json, a.lang)
    if cmd in ("allow", "deny") and a.args:
        dec = "deny" if cmd == "deny" else ("allow_always" if a.always else "allow_once")
        ack = c.until_ack(c.send({"type": "permission_reply", "request_id": a.args[0], "decision": dec}))
        print(json.dumps(ack, ensure_ascii=False))
        return 0 if ack.get("ok") else 1
    if cmd == "cursor":
        c.send({"type": "hello", "client": "ctl-cursor", "role": "tool"})
        msg: dict = {"type": "agent_cursor", "visible": not a.hide}
        if len(a.args) >= 2:
            msg["x"], msg["y"] = float(a.args[0]), float(a.args[1])
        if a.label:
            msg["label"] = a.label
        if a.pulse:
            msg["pulse"] = a.pulse
        ack = c.until_ack(c.send(msg))
        return 0 if ack.get("ok") else 1
    if cmd == "demo-error" and a.args:
        return 0 if c.until_ack(c.send({"type": "demo_error", "code": a.args[0]})).get("ok") else 1
    if cmd == "demo-account" and a.args:
        return 0 if c.until_ack(c.send({"type": "demo_account", "status": a.args[0]})).get("ok") else 1
    if cmd == "send" and a.args:
        ack = c.until_ack(c.send(json.loads(a.args[0])))
        print(json.dumps(ack, ensure_ascii=False))
        return 0 if ack.get("ok") else 1
    p.print_help()
    return 2


if __name__ == "__main__":
    sys.exit(main())
