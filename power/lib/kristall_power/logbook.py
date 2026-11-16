# SPDX-License-Identifier: GPL-3.0-or-later
"""Bounded JSON-lines logs (never seen by the owner; attached to doctor reports).

Each log is one file plus one rotated copy, each at most MAX_BYTES, so the total stays below
2 x MAX_BYTES. Entries: {"t": "<UTC ISO>", "ev": "<event>", ...}."""
import json
import os
import time

MAX_BYTES = 256 * 1024


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append(path: str, event: str, max_bytes: int = MAX_BYTES, **fields):
    rec = {"t": now_iso(), "ev": event}
    rec.update({k: v for k, v in fields.items() if v is not None})
    line = json.dumps(rec, separators=(",", ":"), sort_keys=True) + "\n"
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        try:
            if os.path.getsize(path) + len(line) > max_bytes:
                os.replace(path, path + ".1")
        except OSError:
            pass
        with open(path, "a") as f:
            f.write(line)
    except OSError:
        pass
    return rec


def tail(path: str, n: int = 200):
    lines = []
    for p in (path + ".1", path):
        try:
            with open(p) as f:
                lines.extend(f.readlines())
        except OSError:
            pass
    out = []
    for ln in lines[-n:]:
        try:
            out.append(json.loads(ln))
        except ValueError:
            pass
    return out
