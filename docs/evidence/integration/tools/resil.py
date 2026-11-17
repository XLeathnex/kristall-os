#!/usr/bin/python3
# resil.py — kill -9 each long-running Kristall process of the owner's session in turn; time until a new
# process runs again (and, for the shell, until `kristall-shellctl status` answers with bridge+glass).
import json, os, signal, subprocess, time
TARGETS = [("shell (quickshell)", "quickshell --no-duplicate -p /usr/share/kristall/shell"),
           ("shell helper", "/usr/lib/kristall/shell/kristall-shell-helper"),
           ("assistant daemon", "kristall_assistant.daemon"),
           ("appearance service", "kristall-appearance run"),
           ("power session daemon", "kristall-power session"),
           ("settings watcher (shell)", "kristall-settings watch --full --initial$"),
           ]
def pids(pat):
    r = subprocess.run(["pgrep", "-u", str(os.getuid()), "-f", pat], capture_output=True, text=True)
    return {int(p) for p in r.stdout.split()}
def shell_ok():
    r = subprocess.run(["kristall-shellctl", "status"], capture_output=True, text=True, timeout=5)
    try:
        s = json.loads(r.stdout)
        return s.get("bridge") is True and s.get("glass") == "active" and not s.get("safeMode")
    except Exception:
        return False
out = []
for name, pat in TARGETS:
    before = pids(pat)
    if not before:
        out.append({"process": name, "result": "not running"}); continue
    victim = min(before)
    t0 = time.monotonic()
    os.kill(victim, signal.SIGKILL)
    back = None
    while time.monotonic() - t0 < 30:
        now = pids(pat) - {victim}
        if now:
            back = time.monotonic() - t0; break
        time.sleep(0.05)
    usable = None
    if back is not None and name.startswith("shell"):
        while time.monotonic() - t0 < 40:
            try:
                if shell_ok():
                    usable = time.monotonic() - t0; break
            except subprocess.TimeoutExpired:
                pass
            time.sleep(0.2)
    out.append({"process": name, "killed": victim, "back_s": round(back, 2) if back else None,
                "shell_usable_s": round(usable, 2) if usable else None})
    time.sleep(3)
print(json.dumps(out, indent=1))
