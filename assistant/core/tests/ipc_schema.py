# SPDX-License-Identifier: GPL-3.0-or-later
"""Machine-checkable copy of docs/contracts/assistant-ipc.md (server → client
messages).  test_protocol.py checks every event the daemon emits against this,
and checks that the contract documents exactly these message types."""

S, I, F, B, D, L, N = str, int, float, bool, dict, list, type(None)
NUM = (int, float)
BI = {"de": S, "en": S}           # bilingual text

COMMON = {"type": (S, True), "seq": (I, True), "ts": (I, True)}

STATE_VALUES = {"idle", "listening", "transcribing", "thinking", "acting", "speaking", "error"}

EVENTS = {
    "hello": {"protocol": (I, True), "daemon": (S, True), "version": (S, True), "demo": (B, True)},
    "snapshot": {"state": (S, True), "turn": ((D, N), True), "account": (D, True),
                 "pending_permissions": (L, True), "agent_cursor": ((D, N), True), "assistant": (D, True),
                 "voice": (D, True)},
    "ack": {"id": ((S, I, N), True), "ok": (B, True), "code": (S, False), "message": (D, False),
            "turn_id": (S, False), "detail": (S, False), "re": (S, False)},
    "state": {"state": (S, True), "turn_id": ((S, N), True), "detail": (S, False)},
    "turn_started": {"turn_id": (S, True), "input": (S, True), "source": (S, True), "text": ((S, N), True),
                     "speak": (B, True)},
    "conversation": {"turn_id": (S, True), "conversation_id": (S, True), "continued": (B, True)},
    "level": {"source": (S, True), "value": (NUM, True)},
    "transcript": {"turn_id": (S, True), "text": (S, True), "final": (B, True)},
    "reply_delta": {"turn_id": (S, True), "text": (S, True), "segment": (I, True)},
    "reply_done": {"turn_id": (S, True), "text": (S, True), "spoken": (B, True)},
    "speech": {"turn_id": (S, True), "sentence": (I, True), "text": (S, True)},
    "activity": {"turn_id": ((S, N), True), "id": (S, True), "tool": (S, True), "status": (S, True),
                 "text": (D, True), "detail": (S, False), "source": (S, True)},
    "permission_request": {"request_id": (S, True), "turn_id": (S, True), "question": (D, True), "action": (D, True),
                           "explanation": (S, True), "category": (S, True), "can_always": (B, True),
                           "options": (L, True), "tool": (S, True), "technical": (S, True), "expires_in": (I, True)},
    "permission_resolved": {"request_id": (S, True), "turn_id": (S, True), "decision": (S, True), "by": (S, True)},
    "turn_finished": {"turn_id": (S, True), "outcome": (S, True), "error_code": ((S, N), True)},
    "error": {"code": (S, True), "message": (D, True), "retryable": (B, True), "action": ((S, N), True),
              "turn_id": ((S, N), True), "resets_at": (I, False)},
    "account": {"status": (S, True), "cli_path": ((S, N), False), "cli_version": ((S, N), False),
                "min_version": (S, False), "logged_in": ((B, N), False), "auth_method": ((S, N), False),
                "detail": (S, False)},
    "usage_warning": {"utilization": ((F, I, N), True), "resets_at": ((I, N), True), "window": ((S, N), True)},
    "agent_cursor": {"source": (S, True), "visible": (B, True), "x": (NUM, False), "y": (NUM, False),
                     "pulse": (S, False), "label": (S, False), "output": (S, False), "duration_ms": (I, False),
                     "turn_id": ((S, N), True)},
}

ENUMS = {
    ("state", "state"): STATE_VALUES,
    ("turn_started", "input"): {"voice", "text"},
    ("level", "source"): {"mic", "speech"},
    ("activity", "status"): {"running", "done", "failed"},
    ("activity", "source"): {"assistant", "tool"},
    ("permission_resolved", "decision"): {"allow_once", "allow_always", "deny"},
    ("permission_resolved", "by"): {"owner", "timeout", "cancelled"},
    ("turn_finished", "outcome"): {"completed", "cancelled", "error", "nothing_heard"},
    ("agent_cursor", "pulse"): {"click", "double_click", "right_click", "drag_start", "drag_end", "type", "scroll"},
    ("account", "status"): {"checking", "ready", "cli_missing", "cli_outdated", "signed_out", "unknown"},
}


def check(ev: dict) -> list[str]:
    errs = []
    t = ev.get("type")
    if t not in EVENTS:
        return [f"unknown event type {t!r}"]
    spec = dict(COMMON, **EVENTS[t])
    for k, (typ, req) in spec.items():
        if k not in ev:
            if req:
                errs.append(f"{t}: missing {k}")
            continue
        if not isinstance(ev[k], typ) or (typ in (I, NUM) and isinstance(ev[k], bool)):
            errs.append(f"{t}.{k}: {type(ev[k]).__name__} not {typ}")
    for k in ev:
        if k not in spec:
            errs.append(f"{t}: undocumented field {k}")
    for (et, f), allowed in ENUMS.items():
        if et == t and f in ev and ev[f] not in allowed:
            errs.append(f"{t}.{f}={ev[f]!r} not in {sorted(allowed)}")
    for f in ("question", "action", "message", "text"):
        if t in ("permission_request", "error", "activity") and f in ev and isinstance(ev[f], dict):
            if not (isinstance(ev[f].get("de"), str) and isinstance(ev[f].get("en"), str)):
                errs.append(f"{t}.{f} must have de and en strings")
    if t == "level" and not (0 <= ev.get("value", -1) <= 1):
        errs.append("level.value out of range")
    return errs
