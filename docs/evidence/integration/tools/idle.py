#!/usr/bin/python3
# idle.py SECONDS — the desktop left alone: frames KWin painted (glass status counter, every frame
# KWin composites passes the effect), per-process CPU, RSS and context switches (≈ wakeups) of the
# owner's session processes. Run as the owner.
import json, os, subprocess, sys, time
T = int(sys.argv[1]) if len(sys.argv) > 1 else 60
WATCH = ("kwin_wayland", "quickshell", "kristall", "python", "plasmashell", "Xwayland", "kded6", "ksmserver",
         "kglobalacceld", "pipewire", "wireplumber", "powerdevil", "xdg-desktop", "gmenudbusmenuproxy", "kaccess", "sherpa")
def frames():
    out = subprocess.run(["kristall-glass-ctl", "status"], capture_output=True, text=True).stdout
    return json.loads(out)["frames"]
def procs():
    r = {}
    for pid in os.listdir("/proc"):
        if not pid.isdigit(): continue
        try:
            st = open(f"/proc/{pid}/stat").read()
            uid = os.stat(f"/proc/{pid}").st_uid
            if uid != os.getuid(): continue
            cmd = open(f"/proc/{pid}/cmdline").read().replace("\0", " ").strip()
            f = st.rsplit(")", 1)[1].split()
            ticks = int(f[11]) + int(f[12])
            stat = dict(l.split(":\t", 1) for l in open(f"/proc/{pid}/status").read().splitlines() if ":\t" in l)
            rss = int(stat["VmRSS"].split()[0]) if "VmRSS" in stat else 0
            cs = int(stat.get("voluntary_ctxt_switches", 0)) + int(stat.get("nonvoluntary_ctxt_switches", 0))
            r[int(pid)] = (cmd, ticks, rss, cs)
        except (OSError, ValueError, KeyError, IndexError):
            pass
    return r
hz = os.sysconf("SC_CLK_TCK")
f0, p0, t0 = frames(), procs(), time.monotonic()
time.sleep(min(30, T))
f30 = frames()
time.sleep(max(0, T - 30))
f1, p1, t1 = frames(), procs(), time.monotonic()
dt = t1 - t0
rows = []
for pid, (cmd, tk, rss, cs) in p1.items():
    if pid not in p0: continue
    name = cmd.split()[0].rsplit("/", 1)[-1] if cmd else "?"
    label = cmd[:110]
    cpu = (tk - p0[pid][1]) / hz / dt * 100
    wk = (cs - p0[pid][3]) / dt
    rows.append((label, pid, rss / 1024.0, cpu, wk))
rows.sort(key=lambda r: -r[2])
print(json.dumps({"seconds": round(dt, 1), "frames_first_30s": f30 - f0, "fps_first_30s": round((f30 - f0) / 30.0, 3),
                  "frames_total": f1 - f0}))
tot_rss = tot_cpu = tot_wk = 0
kr = [r for r in rows if "kristall" in r[0] or "quickshell" in r[0]]
for label, pid, rss, cpu, wk in rows:
    print(f"{rss:8.1f} MB  {cpu:6.2f} %  {wk:7.2f} cs/s  {pid:6d}  {label}")
for label, pid, rss, cpu, wk in kr:
    tot_rss += rss; tot_cpu += cpu; tot_wk += wk
print(f"KRISTALL TOTAL (kristall-*, quickshell, their helpers): {tot_rss:.1f} MB RSS, {tot_cpu:.2f} % CPU, {tot_wk:.1f} context switches/s")
print(f"ALL OWNER PROCESSES: {sum(r[2] for r in rows):.1f} MB RSS, {sum(r[3] for r in rows):.2f} % CPU, {sum(r[4] for r in rows):.1f} cs/s")
