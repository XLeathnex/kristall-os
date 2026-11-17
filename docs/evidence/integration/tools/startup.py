#!/usr/bin/python3
# startup.py — seconds from the session start (start-session.sh's timestamp) until the menu bar and the
# Dock are mapped (bridge layer namespaces) and then until the glass effect reports no frames for 2 s.
import json, os, socket, subprocess, time
t0 = float(open("/run/integ-session-start").read())
def wins():
    try:
        r = subprocess.run(["kristall-bridgectl", "windows"], capture_output=True, text=True, timeout=3)
        return json.loads(r.stdout)
    except Exception:
        return []
mapped = None
while time.time() - t0 < 180:
    ns = {w.get("namespace") for w in wins()}
    if any(n and n.startswith("kristall-bar") for n in ns) and any(n and n.startswith("kristall-dock") for n in ns):
        mapped = time.time() - t0
        break
    time.sleep(0.2)
def frames():
    return json.loads(subprocess.run(["kristall-glass-ctl", "status"], capture_output=True, text=True).stdout)["frames"]
idle = None
if mapped is not None:
    last, lt = frames(), time.time()
    while time.time() - t0 < 240:
        time.sleep(0.5)
        f = frames()
        if f != last:
            last, lt = f, time.time()
        elif time.time() - lt >= 2.0:
            idle = lt - t0
            break
print(json.dumps({"bar_and_dock_mapped_s": round(mapped, 2) if mapped else None, "idle_after_s": round(idle, 2) if idle else None}))
