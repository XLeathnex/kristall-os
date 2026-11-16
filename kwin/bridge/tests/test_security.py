# SPDX-License-Identifier: GPL-3.0-or-later
# Access control, lock screen, malformed input and fuzzing, misbehaving clients, client crash,
# fail-soft initialisation, idleness, plugin unload.
import json
import os
import random
import shutil
import signal
import socket
import string
import subprocess
import sys
import time

from common import *  # noqa: F403

INSTALLED_CTL = "/usr/bin/kristall-bridgectl"
METHODS = ["hello", "subscribe", "window.list", "window.activate", "window.close", "window.setMinimized", "window.setMaximized",
           "window.setFullscreen", "window.setGeometry", "window.toDesktop", "window.toOutput", "window.setIconGeometry", "desktop.set",
           "workspace.showDesktop", "effect.toggle", "cursor.get", "agent.begin", "agent.end", "agent.pointer", "agent.drag", "agent.key",
           "agent.text", "screenshot", "nope", "", "debug.trace"]


def raw_client(path):
    c = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    c.settimeout(5)
    c.connect(path)
    return c


def read_lines(sock, n, timeout=5):
    buf = b""
    out = []
    end = time.monotonic() + timeout
    sock.settimeout(0.2)
    while len(out) < n and time.monotonic() < end:
        try:
            d = sock.recv(65536)
        except socket.timeout:
            continue
        if not d:
            break
        buf += d
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            out.append(json.loads(line))
    return out


def alive(s):
    b = s.bridge("probe", timeout=5)
    t0 = time.monotonic()
    b.call("hello", client="probe")
    dt = time.monotonic() - t0
    b.close()
    return s.kwin.poll() is None, dt


def run_ctl(s, args, exe=INSTALLED_CTL, prefix=()):
    return subprocess.run([*prefix, exe, "--socket", s.socket, *args], env=s.env(), capture_output=True, text=True, timeout=30)


@test
def test_access_control():
    """same-uid only; privileged methods only for installed Kristall binaries (no dev switch)"""
    check(os.path.exists(INSTALLED_CTL), "kristall-bridgectl is installed in /usr/bin for this test")
    with Session(dev=False) as s:
        b = s.bridge("untrusted")
        check(b.info["privileged"] is False, "a python test client is not privileged")
        check(len(b.call("window.list")["windows"]) >= 0, "unprivileged: window.list works")
        for method, params in (("agent.begin", {"label": "x"}), ("screenshot", {"target": "desktop"}),
                               ("agent.pointer", {"session": "x", "type": "click", "x": 1, "y": 1}), ("agent.text", {"session": "x", "text": "a"})):
            try:
                b.call(method, **params)
                check(False, f"{method} must be denied")
            except BridgeError as e:
                check(e.code == "denied", f"unprivileged {method}: denied")
        r = run_ctl(s, ["call", "agent.begin", '{"label":"from bridgectl"}'])
        check(r.returncode == 0 and "session" in r.stdout, f"/usr/bin/kristall-bridgectl (python, -I) is privileged: {r.stdout.strip()[:60]} {r.stderr.strip()[:100]}")
        b.call("subscribe", events=["agent"])
        ev = b.wait_event("agent.state", 3)
        # the session ended when bridgectl disconnected
        check(ev and ev["data"]["active"] is False, "the session of a disconnected client ended")
        r = subprocess.run(["/usr/bin/python3", "-I", INSTALLED_CTL, "--socket", s.socket, "screenshot"], env=s.env(), capture_output=True, text=True, timeout=30)
        check(r.returncode == 0 and "path" in r.stdout, "python3 -I /usr/bin/kristall-bridgectl: privileged")
        copy = os.path.join(s.tmp, "kristall-bridgectl")
        shutil.copy(INSTALLED_CTL, copy)
        r = subprocess.run(["/usr/bin/python3", copy, "--socket", s.socket, "screenshot"], env=s.env(), capture_output=True, text=True, timeout=30)
        check(r.returncode != 0 and "denied" in r.stderr, "the same script copied outside /usr: denied")
        r = subprocess.run(["/usr/bin/python3", "-c", f"import sys; sys.argv=['{INSTALLED_CTL}','--socket','{s.socket}','screenshot']; "
                            f"exec(open('{INSTALLED_CTL}').read(), {{'__file__': '{INSTALLED_CTL}', '__name__': '__main__'}})"],
                           env=s.env(), capture_output=True, text=True, timeout=30)
        check(r.returncode != 0 and "denied" in r.stderr, "python3 -c running our code: denied (cannot be attributed)")
        # an ELF binary installed under /usr/lib/kristall/ is trusted by its executable path
        elf = "/usr/lib/kristall/bridge/test-peer"
        os.makedirs(os.path.dirname(elf), exist_ok=True)
        shutil.copy("/usr/bin/python3", elf)
        try:
            r = subprocess.run([elf, INSTALLED_CTL, "--socket", s.socket, "screenshot"], env=s.env(), capture_output=True, text=True, timeout=30)
            check(r.returncode == 0, "an executable under /usr/lib/kristall/ is privileged")
        finally:
            os.unlink(elf)
        # a Python virtual environment under /usr/lib/kristall/ (the assistant daemon's, for
        # instance) is a general interpreter: it must run an installed script to be trusted
        exec_ctl = (f"import sys; sys.argv=['{INSTALLED_CTL}','--socket','{s.socket}','screenshot']; "
                    f"exec(open('{INSTALLED_CTL}').read(), {{'__file__': '{INSTALLED_CTL}', '__name__': '__main__'}})")
        for kind, venv_args in (("copied", ["--copies"]), ("symlinked", [])):
            venv = f"/usr/lib/kristall/bridge/test-venv-{kind}"
            subprocess.run(["/usr/bin/python3", "-m", "venv", "--without-pip", *venv_args, venv], check=True, timeout=60)
            try:
                py = os.path.join(venv, "bin", "python3")
                r = subprocess.run([py, "-c", exec_ctl], env=s.env(), capture_output=True, text=True, timeout=30)
                check(r.returncode != 0 and "denied" in r.stderr, f"{kind} venv interpreter under /usr/lib/kristall running -c: denied")
                r = subprocess.run([py, "-I", INSTALLED_CTL, "--socket", s.socket, "screenshot"], env=s.env(),
                                   capture_output=True, text=True, timeout=30)
                check(r.returncode == 0 and "path" in r.stdout, f"{kind} venv interpreter running an installed script: privileged")
            finally:
                shutil.rmtree(venv, ignore_errors=True)
        # another uid: the socket and directory are 0600/0700; with them opened up, SO_PEERCRED still refuses
        os.chmod(s.tmp, 0o755)
        os.chmod(s.runtime, 0o755)
        os.chmod(os.path.dirname(s.socket), 0o755)
        st = oct(os.stat(s.socket).st_mode & 0o777)
        check(st == "0o600", f"socket mode {st}")
        os.chmod(s.socket, 0o666)
        code = ("import socket,sys; c=socket.socket(socket.AF_UNIX); c.connect(sys.argv[1]); "
                "c.sendall(b'{\"id\":1,\"method\":\"hello\"}\\n'); c.settimeout(3); print(repr(c.recv(100)))")
        r = subprocess.run(["setpriv", "--reuid=1000", "--regid=1000", "--clear-groups", "python3", "-c", code, s.socket],
                           capture_output=True, text=True, timeout=10)
        # closed before or after the client wrote: EOF, a reset, or a broken pipe; never a reply
        check(("b''" in r.stdout or "reset" in r.stderr.lower() or "broken pipe" in r.stderr.lower())
              and '"result"' not in r.stdout, f"uid 1000 is disconnected without a reply: {r.stdout.strip()} {r.stderr.strip()[-80:]}")
        os.chmod(s.socket, 0o600)
        ok, dt = alive(s)
        check(ok, "KWin alive")


@test
def test_lock_screen_denies():
    """while the screen is locked every privileged method is denied and a session is ended"""
    with Session(locked=True) as s:
        b = s.bridge()
        check(b.info["locked"] is True, "hello reports the lock")
        for method, params in (("agent.begin", {"label": "x"}), ("screenshot", {"target": "desktop"})):
            try:
                b.call(method, **params)
                check(False, f"{method} must be denied while locked")
            except BridgeError as e:
                check(e.code == "denied" and "locked" in e.message, f"locked: {method} denied ({e.message})")
        check("windows" in b.call("window.list"), "window.list still answers")
    with Session(lockscreen=True) as s:
        b = s.bridge()
        b.subscribe("agent")
        b.wait_event("agent.state", 3)
        token = b.call("agent.begin", label="busy")["session"]
        b.wait_event("agent.state", 3)
        p = s.wlprobe("--title", "victim", "--size", "300x200")
        w = window_by_title(b, "victim")
        cx, cy = content(w)
        b.call("agent.pointer", session=token, type="down", x=cx + 10, y=cy + 10)
        r = subprocess.run(["busctl", "--user", "call", "org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "Lock"],
                           env=s.env(), capture_output=True, text=True, timeout=10)
        check(r.returncode == 0, f"locked via org.freedesktop.ScreenSaver.Lock {r.stderr.strip()}")
        ev = b.wait_event(lambda e: e["event"] == "agent.state" and not e["data"]["active"], 5)
        check(ev is not None and ev["data"]["label"] == "locked", f"agent.state on lock: {ev and ev['data']}")
        check(p.wait(lambda e: e.get("ev") == "button" and e["state"] == 0, 2) is not None, "the held button was released on lock")
        try:
            b.call("agent.pointer", session=token, type="click", x=10, y=10)
            check(False, "denied")
        except BridgeError as e:
            check(e.code == "denied", "agent input after locking: denied")
        try:
            b.call("screenshot", target="desktop")
            check(False, "denied")
        except BridgeError as e:
            check(e.code == "denied", "screenshot after locking: denied")


@test
def test_malformed_input():
    """malformed lines get 'invalid' replies in order; the connection survives; >1 MiB lines close it"""
    with Session() as s:
        c = raw_client(s.socket)
        bad = [b"not json", b"[]", b"{}", b'{"id":1}', b'{"id":{},"method":"hello"}', b'{"id":2,"method":5}', b'{"id":3,"method":"hello","params":[]}',
               b'{"id":4,"method":"nope"}', b'{"id":5,"method":"window.setGeometry","params":{"id":"x","x":"1"}}', b'\xff\xfe\x00garbage',
               b'{"id":6,"method":"agent.pointer","params":{"session":"x","type":"click","x":1e400,"y":0}}', b'{"id":7' + b',"a":[' * 5000 + b"]" * 5000 + b"}",
               b'{"id":"' + b"x" * 300 + b'","method":"hello"}', b'{"id":8,"method":"hello"}']
        c.sendall(b"\n".join(bad) + b"\n")
        lines = read_lines(c, len(bad))
        check(len(lines) == len(bad), f"one reply per line ({len(lines)}/{len(bad)})")
        check(all("error" in l and l["error"]["code"] == "invalid" for l in lines[:-1]), f"all invalid: {[l.get('error', {}).get('code') for l in lines]}")
        check(lines[-1].get("id") == 8 and "result" in lines[-1], "the connection still works after garbage")
        c.sendall(b'{"id":9,"method":"hello","params":{"pad":"' + b"a" * (1 << 20) + b'"}}\n')
        lines = read_lines(c, 1, 5)
        check(lines and lines[0]["error"]["code"] == "invalid" and "1 MiB" in lines[0]["error"]["message"], "a line over 1 MiB is refused")
        time.sleep(0.3)
        c.settimeout(2)
        try:
            closed = c.recv(10) == b""
        except (ConnectionResetError, socket.timeout):
            closed = True
        check(closed, "and the connection is closed")
        ok, dt = alive(s)
        check(ok and dt < 0.5, f"KWin alive and responsive ({dt * 1000:.1f} ms)")


PROBE_CODE = r"""
import os, socket, sys, time, json
path, stop = sys.argv[1], sys.argv[2]
worst = 0.0
n = 0
c = socket.socket(socket.AF_UNIX); c.connect(path); f = c.makefile("rb")
while not os.path.exists(stop):
    t = time.monotonic()
    c.sendall(b'{"id":1,"method":"cursor.get"}\n'); f.readline()
    worst = max(worst, time.monotonic() - t); n += 1
    time.sleep(0.005)
print(json.dumps({"worst_ms": worst * 1000, "samples": n}), flush=True)
"""


class LatencyProbe:
    """Measures another client's round-trip latency from a separate process (no GIL effects)."""

    def __init__(self, s):
        self.stop_file = os.path.join(s.tmp, f"stop-{time.monotonic_ns()}")
        self.p = subprocess.Popen(["python3", "-c", PROBE_CODE, s.socket, self.stop_file], stdout=subprocess.PIPE, text=True)

    def finish(self):
        open(self.stop_file, "w").close()
        out, _ = self.p.communicate(timeout=10)
        return json.loads(out)


class RawCounter:
    """Raw connection that sends lines and counts reply lines (ids may repeat or be null)."""

    def __init__(self, path):
        import threading
        self.sock = raw_client(path)
        self.sock.settimeout(None)
        self.count = 0
        self.codes = {}
        self.closed = False
        self._t = threading.Thread(target=self._read, daemon=True)
        self._t.start()

    def _read(self):
        f = self.sock.makefile("rb")
        try:
            for line in f:
                msg = json.loads(line)
                if "event" in msg:
                    continue
                self.count += 1
                k = msg["error"]["code"] if "error" in msg else "ok"
                self.codes[k] = self.codes.get(k, 0) + 1
        except (OSError, ValueError):
            pass
        self.closed = True


def random_value(rnd, depth=0):
    k = rnd.randrange(10 if depth < 3 else 6)
    if k == 0:
        return None
    if k == 1:
        return rnd.choice([True, False])
    if k == 2:
        return rnd.choice([0, -1, 1, 2 ** 31, -2 ** 63, 1e308, -1e308, 0.5, 1e-300, rnd.uniform(-5000, 5000)])
    if k == 3:
        return "".join(rnd.choice(string.printable + "äöü€😀\u0000‮") for _ in range(rnd.randrange(0, 40)))
    if k == 4:
        return rnd.choice(["left", "right", "click", "down", "up", "move", "scroll", "desktop", "ctrl+shift+t", "return", "😀"])
    if k == 5:
        return rnd.randrange(-10, 3000)
    if k in (6, 7):
        return [random_value(rnd, depth + 1) for _ in range(rnd.randrange(0, 4))]
    return {rnd.choice(["x", "y", "id", "type", "session", "text", "keys", "target", "window", "region", "from", "to", "w", "h", "value",
                        "events", "label", "durationMs", "count", "dx", "dy", "button", "maxWidth", "hoverMs", "paths"]): random_value(rnd, depth + 1)
            for _ in range(rnd.randrange(0, 6))}


@test
def test_fuzz_parser_and_dispatcher():
    """20 000 random requests (valid methods, random parameters, random bytes): no crash, no stall"""
    with Session() as s:
        p = s.wlprobe("--title", "fuzzed", "--size", "300x200")
        b = s.bridge("setup")
        wid = window_by_title(b, "fuzzed")["id"]
        rc = RawCounter(s.socket)
        # random tokens exercise the session checks, the real one (held by another connection)
        # exercises the handlers
        tb = s.bridge("tokener")
        token = tb.call("agent.begin", label="fuzz")["session"]
        rnd = random.Random(1234)
        lines = []
        for i in range(20000):
            if rnd.random() < 0.05:
                lines.append(bytes(rnd.randrange(256) for _ in range(rnd.randrange(1, 200))).replace(b"\n", b" "))
                continue
            params = random_value(rnd)
            if isinstance(params, dict) and token and rnd.random() < 0.5:
                params["session"] = token
            if isinstance(params, dict) and rnd.random() < 0.3:
                params["id"] = wid
            method = rnd.choice(METHODS)
            if method in ("agent.end", "window.close") and rnd.random() < 0.9:
                method = "cursor.get"
            if isinstance(params, dict):
                if method == "agent.text":
                    params["text"] = str(params.get("text", ""))[:20]
                params.pop("durationMs", None) if rnd.random() < 0.9 else None
                params.pop("hoverMs", None) if rnd.random() < 0.9 else None
            req = {"id": i, "method": method}
            if rnd.random() < 0.95:
                req["params"] = params
            lines.append(json.dumps(req, ensure_ascii=rnd.random() < 0.5).encode())
        probe = LatencyProbe(s)
        t0 = time.monotonic()
        rc.sock.sendall(b"\n".join(lines) + b"\n")
        expected = sum(1 for l in lines if l.strip(b" \t\r\x0b\x0c"))
        ok = wait_until(lambda: rc.count >= expected or rc.closed, 120, 0.2)
        dt = time.monotonic() - t0
        lat = probe.finish()
        check(s.kwin.poll() is None, "KWin survived")
        check(rc.count == expected, f"{rc.count} replies to {expected} non-blank lines in {dt:.1f} s")
        note(f"reply codes: {rc.codes}")
        note(f"another client's worst round trip during the fuzz: {lat['worst_ms']:.1f} ms over {lat['samples']} samples "
             "(screenshots render on the compositor thread, ~40 ms each on llvmpipe)")
        ok, d = alive(s)
        check(ok, "still answering afterwards")


@test
def test_client_that_stops_reading():
    """a client that never reads is dropped once its backlog passes the cap; KWin stays responsive"""
    with Session() as s:
        for i in range(6):
            s.wlprobe("--title", f"w{i}", "--size", "200x100")
        time.sleep(1)
        c = raw_client(s.socket)
        c.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        req = b'{"id":1,"method":"window.list"}\n' * 200
        sent = 0
        probe = s.bridge("probe")
        worst = 0.0
        dropped = False
        c.settimeout(0.5)
        for _ in range(200):
            try:
                c.sendall(req)
                sent += 200
            except (BrokenPipeError, ConnectionResetError, socket.timeout):
                dropped = True
                break
            t1 = time.monotonic()
            probe.call("cursor.get")
            worst = max(worst, time.monotonic() - t1)
        check(dropped, f"the bridge dropped the non-reading client after ~{sent} requests")
        check(worst < 0.25, f"worst latency for another client meanwhile: {worst * 1000:.1f} ms")
        ok, dt = alive(s)
        check(ok, "KWin alive")
        log = s.log_text()
        check("stopped reading" in log or "closing client" in log, "the drop was logged")


@test
def test_flooding_client_does_not_stall():
    """a client firing 200 000 tiny requests is served in slices; others stay responsive"""
    with Session() as s:
        rc = RawCounter(s.socket)
        probe = LatencyProbe(s)
        time.sleep(0.2)
        t0 = time.monotonic()
        rc.sock.sendall(b'{"id":1,"method":"cursor.get"}\n' * 200000)
        wait_until(lambda: rc.count >= 200000, 60, 0.1)
        dt = time.monotonic() - t0
        lat = probe.finish()
        check(rc.count == 200000, f"200 000 requests answered in {dt:.1f} s ({200000 / dt:.0f}/s)")
        check(lat["worst_ms"] < 50, f"worst latency for another client during the flood: {lat['worst_ms']:.1f} ms ({lat['samples']} samples)")


@test
def test_client_crash_mid_session():
    """a client killed while holding a button: session ends, button released, hover restored"""
    with Session() as s:
        o = s.owner()
        b = s.bridge()
        b.subscribe("agent")
        b.wait_event("agent.state", 3)
        p = s.wlprobe("--title", "held", "--size", "300x200")
        under = s.wlprobe("--title", "under", "--size", "300x200")
        w = place(b, window_by_title(b, "held"), 50, 50, 300, 200)
        wu = place(b, window_by_title(b, "under"), 600, 400, 300, 200)
        o.move(wu["x"] + 100, wu["y"] + 100)
        code = ("import sys, time; sys.path.insert(0, sys.argv[2]); from kristall_bridge import Bridge; b = Bridge(sys.argv[1]); "
                "t = b.call('agent.begin', label='doomed')['session']; "
                f"b.call('agent.pointer', session=t, type='down', x={w['x'] + 30}, y={w['y'] + 30}); "
                "print('held', flush=True); time.sleep(60)")
        doomed = subprocess.Popen(["python3", "-c", code, s.socket, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "python")],
                                  env=s.env(), stdout=subprocess.PIPE, text=True)
        check(doomed.stdout.readline().strip() == "held", "client holds a button in the window")
        doomed.send_signal(signal.SIGKILL)
        doomed.wait()
        ev = b.wait_event(lambda e: e["event"] == "agent.state" and e["data"]["active"] is False, 5)
        check(ev is not None and ev["data"]["label"] == "disconnected", f"session ended: {ev and ev['data']}")
        check(p.wait(lambda e: e.get("ev") == "button" and e["state"] == 0, 3) is not None, "the window got the release")
        time.sleep(0.2)
        last = [e for e in under.snapshot() if e.get("ev") in ("enter", "leave")]
        check(last and last[-1]["ev"] == "enter", "the window under the owner's pointer is hovered again")
        token = b.call("agent.begin", label="next")["session"]
        check(bool(token), "a new session can start")


@test
def test_fail_soft_initialisation():
    """broken plugin, unusable socket path, or a live bridge on the path: KWin runs without the bridge"""
    s = Session(plugins=os.path.join(BUILD, "plugins-broken"))
    s.start(wait_bridge=False)
    try:
        p = s.wlprobe("--title", "still works")
        time.sleep(1.0)
        check(s.kwin.poll() is None and p.wait("mapped", 5) is not None, "KWin runs and maps windows with a plugin that fails to initialise")
        check(not os.path.exists(s.socket) and "disabled: built with KRISTALL_BRIDGE_TEST_BROKEN" in s.log_text(), "the bridge logged once that it is disabled")
    finally:
        s.stop()
    s = Session()
    with open(os.path.join(s.runtime, "kristall"), "w") as f:
        f.write("a file where the directory should be")
    s.start(wait_bridge=False)
    try:
        time.sleep(1.0)
        check(s.kwin.poll() is None, "KWin runs when the socket directory is unusable")
        check("disabled:" in s.log_text() and "not a directory" in s.log_text(), "logged: socket directory unusable")
    finally:
        s.stop()
    s = Session()
    os.makedirs(os.path.join(s.runtime, "kristall"), mode=0o700)
    squatter = socket.socket(socket.AF_UNIX)
    squatter.bind(os.path.join(s.runtime, "kristall", "bridge.sock"))
    squatter.listen(1)
    s.start(wait_bridge=False)
    try:
        time.sleep(1.0)
        check(s.kwin.poll() is None and "another bridge is already serving" in s.log_text(), "a live socket on the path is left alone")
    finally:
        squatter.close()
        s.stop()


def cpu_ticks(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return int(parts[11]) + int(parts[12])


@test
def test_idle_means_idle():
    """with nothing changing, KWin with the bridge (and an idle subscriber) uses no more CPU than without"""
    results = {}
    os.makedirs("/tmp/kristall-empty-plugins", exist_ok=True)
    for label, plugins, subscribe in (("without bridge", "/tmp/kristall-empty-plugins", False),
                                      ("bridge, no clients", None, False), ("bridge, idle subscriber", None, True)):
        s = Session(plugins=plugins)
        s.start(wait_bridge=plugins is None)
        try:
            sub = None
            if subscribe:
                sub = s.bridge("idle")
                sub.subscribe("windows", "active", "stacking", "outputs", "desktops", "agent", "menus")
                sub.drain_events(0.5)
            time.sleep(3)
            t0 = cpu_ticks(s.kwin.pid)
            time.sleep(10)
            results[label] = cpu_ticks(s.kwin.pid) - t0
            if sub:
                evs = sub.drain_events(0.2)
                check(evs == [], f"no events while idle: {evs[:2]}")
        finally:
            s.stop()
    note(f"KWin CPU ticks over 10 s idle (1 tick = 10 ms): {results}")
    base = results["without bridge"]
    check(results["bridge, no clients"] <= base + 3 and results["bridge, idle subscriber"] <= base + 3, "the bridge adds no measurable idle work")


@test
def test_plugin_unload_during_gesture():
    """unloading the plugin (KWin's D-Bus API) mid-gesture releases the button and removes the socket"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "u", "--size", "300x200")
        w = window_by_title(b, "u")
        cx, cy = content(w)
        token = b.call("agent.begin", label="u")["session"]
        b.call("agent.pointer", session=token, type="down", x=cx + 10, y=cy + 10)
        r = subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/Plugins", "org.kde.KWin.Plugins", "UnloadPlugin", "s", "kristall_bridge"],
                           env=s.env(), capture_output=True, text=True)
        check(r.returncode == 0, f"UnloadPlugin {r.stderr.strip()}")
        check(p.wait(lambda e: e.get("ev") == "button" and e["state"] == 0, 3) is not None, "the held button was released")
        check(wait_until(lambda: not os.path.exists(s.socket), 3), "the socket is gone")
        check(s.kwin.poll() is None, "KWin keeps running")
        r = subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/Plugins", "org.kde.KWin.Plugins", "LoadPlugin", "s", "kristall_bridge"],
                           env=s.env(), capture_output=True, text=True)
        check(wait_until(lambda: os.path.exists(s.socket), 5), "and it can be loaded again")
        b2 = s.bridge()
        check("agentInput" in b2.capabilities, "reloaded bridge answers")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
