#!/usr/bin/python3
# hold.py MOD KEY TAPS SHOT — hold MOD, tap KEY TAPS times, take screenshot SHOT while held, release.
import subprocess, sys, time
K = {"alt": 56, "meta": 125, "ctrl": 29, "shift": 42, "tab": 15, "grave": 41}
mod, key, taps, shot = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4]
p = subprocess.Popen(["/opt/integ/owner"], stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
def c(l):
    p.stdin.write(l + "\n"); p.stdin.flush(); p.stdout.readline()
c(f"key {K[mod]} 1"); time.sleep(0.1)
for _ in range(taps):
    c(f"key {K[key]} 1"); time.sleep(0.05); c(f"key {K[key]} 0"); time.sleep(0.35)
time.sleep(0.8)
subprocess.run(["python3", "/integ/shot.py", shot])
c(f"key {K[mod]} 0")
p.stdin.close(); p.wait(5)
