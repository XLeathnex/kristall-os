#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""A stand-in for the ``claude`` CLI that replays recorded stream-JSON.

Environment:
  FAKE_CLAUDE_FIXTURE   recorded session (tests/fixtures/*.jsonl, made by tools/record_fixtures.py)
  FAKE_CLAUDE_MODE      instead of a fixture, synthesise an error state:
                        not_signed_in | rate_limited | credit_exhausted | offline | overloaded |
                        refusal | crash | slow (streams forever until interrupted)
  FAKE_CLAUDE_VERSION   what ``--version`` prints (default "2.1.325 (Claude Code)")
  FAKE_CLAUDE_LOGGED_IN "0" makes ``auth status`` report signed out
  FAKE_CLAUDE_LOG       append argv and every stdin line here (for assertions)
  FAKE_CLAUDE_DELAY     cap on replayed inter-message delay in seconds (default 0.02)

Replay is strict: each recorded *input* line must arrive (same type/subtype)
before the following recorded output is written, so a test fails if the
daemon speaks the protocol differently from the real CLI.
"""
import json
import os
import select
import sys
import time

FIX_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
LOG = os.environ.get("FAKE_CLAUDE_LOG")
DELAY = float(os.environ.get("FAKE_CLAUDE_DELAY", "0.02"))


def log(kind, data):
    if LOG:
        with open(LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps({"kind": kind, "data": data}, ensure_ascii=False) + "\n")


def emit(msg):
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


_buf = b""


def read_msg(timeout=30.0):
    global _buf
    end = time.monotonic() + timeout
    while b"\n" not in _buf:
        left = end - time.monotonic()
        if left <= 0:
            return "timeout"
        r, _, _ = select.select([sys.stdin.buffer], [], [], left)
        if not r:
            return "timeout"
        chunk = os.read(sys.stdin.fileno(), 65536)
        if not chunk:
            return None
        _buf += chunk
    line, _buf = _buf.split(b"\n", 1)
    msg = json.loads(line)
    log("in", msg)
    return msg


def kind(m):
    if m.get("type") == "control_request":
        return "control_request:" + m["request"]["subtype"]
    if m.get("type") == "control_response":
        return "control_response"
    return m.get("type")


def fail(why):
    sys.stderr.write(f"fake_claude: {why}\n")
    sys.exit(3)


def replay(path):
    lines = [json.loads(l) for l in open(path, encoding="utf-8")]
    rid_map = {}               # recorded SDK request ids -> actual
    last_t = 0.0
    pending_in = []            # inputs that arrived before we expected them
    for rec in lines:
        d, m = rec["dir"], rec["msg"]
        if d == "argv":
            continue
        if d == "in":
            want = kind(m)
            # find a matching actual input (earlier unexpected ones are kept)
            got = None
            for i, p in enumerate(pending_in):
                if kind(p) == want:
                    got = pending_in.pop(i)
                    break
            while got is None:
                a = read_msg()
                if a == "timeout":
                    fail(f"timed out waiting for {want}")
                if a is None:
                    return
                if kind(a) == want:
                    got = a
                else:
                    pending_in.append(a)
            if want.startswith("control_request"):
                rid_map[m["request_id"]] = got["request_id"]
            continue
        # output
        dt = max(0.0, rec["t"] - last_t)
        last_t = rec["t"]
        time.sleep(min(dt, DELAY))
        if m.get("type") == "control_response":
            r = dict(m["response"])
            if r.get("request_id") in rid_map:
                r["request_id"] = rid_map[r["request_id"]]
            m = dict(m, response=r)
        emit(m)
    # stay alive like the real CLI until stdin closes (more turns would need more fixture)
    while True:
        a = read_msg(timeout=3600)
        if a is None or a == "timeout":
            return
        if kind(a) == "control_request:interrupt":
            emit({"type": "control_response", "response": {"subtype": "success", "request_id": a["request_id"],
                                                          "response": {}}})


# ----------------------------------------------------------------- synthetic modes

SID = "00000000-0000-4000-8000-000000000000"


def init_response(req):
    return {"type": "control_response", "response": {"subtype": "success", "request_id": req["request_id"],
            "response": {"commands": [], "agents": [], "output_style": "default", "models": [],
                         "account": {}, "pid": os.getpid()}}}


def result(is_error, text, **kw):
    r = {"type": "result", "subtype": "success", "is_error": is_error, "duration_ms": 10, "duration_api_ms": 5,
         "num_turns": 1, "result": text, "stop_reason": kw.pop("stop_reason", "end_turn"), "session_id": SID,
         "total_cost_usd": 0, "usage": {}, "uuid": "r-" + str(time.time())}
    r.update(kw)
    return r


def assistant(text, error=None, stop_reason=None):
    m = {"type": "assistant", "message": {"model": "claude-haiku-5-5", "id": f"msg_{time.time()}", "type": "message",
         "role": "assistant", "content": [{"type": "text", "text": text}] if text else [],
         "stop_reason": stop_reason}, "parent_tool_use_id": None, "session_id": SID}
    if error:
        m["error"] = error
    return m


def synthetic(mode):
    while True:
        m = read_msg(timeout=3600)
        if m is None or m == "timeout":
            return
        k = kind(m)
        if k == "control_request:initialize":
            emit(init_response(m))
            continue
        if k == "control_request:interrupt":
            emit({"type": "control_response", "response": {"subtype": "success", "request_id": m["request_id"],
                                                          "response": {}}})
            emit(result(True, "", subtype="error_during_execution", stop_reason=None))
            continue
        if k != "user":
            continue
        emit({"type": "system", "subtype": "init", "session_id": SID, "model": "claude-haiku-5-5", "tools": []})
        if mode == "crash":
            sys.exit(1)
        if mode == "not_signed_in":
            emit(assistant("Not logged in · Please run /login", error="authentication_failed"))
            emit(result(True, "Not logged in · Please run /login"))
        elif mode in ("rate_limited", "credit_exhausted"):
            typ = "five_hour" if mode == "rate_limited" else "seven_day"
            emit({"type": "rate_limit_event", "rate_limit_info": {"status": "rejected", "resetsAt": int(time.time()) + 3600,
                  "rateLimitType": typ}, "uuid": "u1", "session_id": SID})
            emit(assistant("You've hit your limit", error="rate_limit"))
            emit(result(True, "You've hit your limit", api_error_status=429))
        elif mode == "billing":
            emit(assistant("Credit balance is too low", error="billing_error"))
            emit(result(True, "Credit balance is too low"))
        elif mode == "offline":
            for i in range(1, 4):
                emit({"type": "system", "subtype": "api_retry", "attempt": i, "max_retries": 10, "retry_delay_ms": 500,
                      "error_status": None, "error": "unknown", "uuid": f"x{i}", "session_id": SID})
                time.sleep(0.05)
            # then hang like the real CLI would while retrying, until interrupted
            m2 = read_msg(timeout=60)
            if isinstance(m2, dict) and kind(m2) == "control_request:interrupt":
                emit({"type": "control_response", "response": {"subtype": "success",
                      "request_id": m2["request_id"], "response": {}}})
                emit(result(True, "", subtype="error_during_execution", stop_reason=None))
        elif mode == "overloaded":
            emit({"type": "system", "subtype": "api_retry", "attempt": 1, "max_retries": 2, "retry_delay_ms": 10,
                  "error_status": 529, "error": "overloaded", "uuid": "o1", "session_id": SID})
            emit(assistant("API Error: 529 Overloaded", error="server_error"))
            emit(result(True, "API Error: 529 Overloaded", api_error_status=529))
        elif mode == "refusal":
            emit(assistant("", stop_reason="refusal"))
            emit(result(False, "", stop_reason="refusal"))
        elif mode == "slow":
            emit({"type": "stream_event", "event": {"type": "message_start", "message": {"id": "msg_slow"}},
                  "session_id": SID, "uuid": "s0"})
            n = 0
            while True:
                emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0,
                      "delta": {"type": "text_delta", "text": f"Wort{n} "}}, "session_id": SID, "uuid": f"s{n}"})
                n += 1
                m2 = read_msg(timeout=0.05)
                if isinstance(m2, dict) and kind(m2) == "control_request:interrupt":
                    emit({"type": "control_response", "response": {"subtype": "success",
                          "request_id": m2["request_id"], "response": {}}})
                    emit(result(True, "", subtype="error_during_execution", stop_reason=None))
                    break
                if m2 is None:
                    return
        else:
            fail(f"unknown mode {mode}")


def main():
    argv = sys.argv[1:]
    log("argv", argv)
    if argv[:1] == ["--version"]:
        print(os.environ.get("FAKE_CLAUDE_VERSION", "2.1.325 (Claude Code)"))
        return
    if argv[:2] == ["auth", "status"]:
        li = os.environ.get("FAKE_CLAUDE_LOGGED_IN", "1") != "0"
        print(json.dumps({"loggedIn": li, "authMethod": "claude.ai" if li else None, "apiProvider": "firstParty"}))
        return
    if argv[:2] == ["auth", "logout"]:
        print("Successfully logged out from your Anthropic account.")
        return
    if argv[:2] == ["auth", "login"]:
        print("Opening browser to sign in…")
        print("If the browser didn't open, visit: https://claude.com/cai/oauth/authorize?code=true&client_id=test")
        sys.stdout.write("Paste code here if prompted > ")
        sys.stdout.flush()
        line = sys.stdin.readline().strip()
        if line == "good-code":
            print("Login successful.")
            return
        print("OAuth error: invalid code")
        sys.exit(1)
    if argv[:1] == ["update"]:
        print("Claude Code is up to date (2.1.325)")
        return
    fx = os.environ.get("FAKE_CLAUDE_FIXTURE")
    mode = os.environ.get("FAKE_CLAUDE_MODE")
    if fx:
        if not os.path.isabs(fx):
            fx = os.path.join(FIX_DIR, fx if fx.endswith(".jsonl") else fx + ".jsonl")
        replay(fx)
    elif mode:
        synthetic(mode)
    else:
        fail("set FAKE_CLAUDE_FIXTURE or FAKE_CLAUDE_MODE")


if __name__ == "__main__":
    main()
