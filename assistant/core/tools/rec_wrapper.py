#!/usr/bin/env python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Stand-in for ``claude`` that runs the real CLI and records the stream.

Used by record_fixtures.py: set REC_REAL_CLI, REC_FILE.  Every line written
to the CLI (stdin) is recorded as {"dir":"in","t":…,"msg":…} and every line it
prints as {"dir":"out",…}.  argv is recorded once, first.
"""
import json
import os
import signal
import subprocess
import sys
import threading
import time

real = os.environ["REC_REAL_CLI"]
rec = open(os.environ["REC_FILE"], "a", encoding="utf-8")
lock = threading.Lock()
t0 = time.monotonic()


def log(direction: str, line: str) -> None:
    try:
        msg = json.loads(line)
    except ValueError:
        msg = {"_raw": line}
    with lock:
        rec.write(json.dumps({"dir": direction, "t": round(time.monotonic() - t0, 3), "msg": msg},
                             ensure_ascii=False) + "\n")
        rec.flush()


log("argv", json.dumps({"argv": sys.argv[1:]}))
p = subprocess.Popen([real] + sys.argv[1:], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                     stderr=sys.stderr, bufsize=0)
for s in (signal.SIGTERM, signal.SIGINT):
    signal.signal(s, lambda n, f: p.send_signal(n))


def pump_in() -> None:
    for raw in sys.stdin.buffer:
        log("in", raw.decode(errors="replace").rstrip("\n"))
        try:
            p.stdin.write(raw)
            p.stdin.flush()
        except BrokenPipeError:
            break
    try:
        p.stdin.close()
    except OSError:
        pass


threading.Thread(target=pump_in, daemon=True).start()
for raw in p.stdout:
    log("out", raw.decode(errors="replace").rstrip("\n"))
    sys.stdout.buffer.write(raw)
    sys.stdout.buffer.flush()
sys.exit(p.wait())
