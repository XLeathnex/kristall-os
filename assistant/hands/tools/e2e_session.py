# SPDX-License-Identifier: GPL-3.0-or-later
"""End-to-end helper (dev container, under dbus-run-session): keeps a headless KWin with the real
bridge (development mode off) running, plus a stand-in for the assistant daemon's socket that logs
every agent_cursor/tool_activity request to OUT/cursor.jsonl.  Writes OUT/env.sh for
`run-hands.sh`, which a Claude Code MCP config on the host starts with `docker exec -i`.
Stops when OUT/stop exists.  Usage: e2e_session.py OUT"""
import json
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, os.path.join(REPO, "kwin/bridge/tests/support"))
sys.path.insert(0, os.path.join(os.path.dirname(HERE), "tests"))
os.environ.setdefault("KRISTALL_BRIDGE_BUILD", "/tmp/kb")
import harness  # noqa: E402
from support.mock_daemon import MockDaemon  # noqa: E402

out = sys.argv[1]
os.makedirs(out, exist_ok=True)
for f in ("stop", "cursor.jsonl"):
    try:
        os.unlink(os.path.join(out, f))
    except FileNotFoundError:
        pass
s = harness.Session(dev=False, width=1440, height=900, name="e2e").start()
daemon = MockDaemon(os.path.join(s.runtime, "kristall", "assistant.sock")).start()
env = s.env()
with open(os.path.join(out, "env.sh"), "w") as f:
    for k in ("XDG_RUNTIME_DIR", "WAYLAND_DISPLAY", "XDG_CONFIG_HOME", "DBUS_SESSION_BUS_ADDRESS"):
        f.write(f"export {k}='{env.get(k) or os.environ.get(k, '')}'\n")
    f.write("export QT_QPA_PLATFORM=wayland KRISTALL_HANDS_LOG_STDERR=1 KRISTALL_SETTINGS_BIN=/nonexistent\n")
    f.write(f"export HOME='{out}/home'\n")
os.makedirs(os.path.join(out, "home", "Dokumente"), exist_ok=True)
print("ready", flush=True)
written = 0
try:
    while not os.path.exists(os.path.join(out, "stop")):
        time.sleep(0.5)
        if len(daemon.received) > written:
            with open(os.path.join(out, "cursor.jsonl"), "a") as f:
                for t, m in daemon.received[written:]:
                    f.write(json.dumps({"t": round(t, 3), **m}, ensure_ascii=False) + "\n")
            written = len(daemon.received)
finally:
    daemon.stop()
    s.stop()
