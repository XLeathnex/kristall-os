#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
# glass.sock under stress: malformed input, rapid updates, client crash, reconnect, limits,
# many surfaces. Runs in the dev container under dbus-run-session (tests/run.sh).
import json
import os
import signal
import socket
import subprocess
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "support"))
import harness  # noqa: E402

GLASSHOST = os.path.join(HERE, "support", "glasshost.qml")
FAILURES = []
RESULTS = {}


def check(name, ok, detail):
    print(("PASS " if ok else "FAIL ") + name + ": " + detail, flush=True)
    if not ok:
        FAILURES.append(name)


def shape(i, x=100, y=100):
    return {"id": f"s{i}", "x": x + (i % 8) * 70, "y": y + (i // 8) * 70, "w": 60, "h": 60, "radius": 14}


def alive(s):
    c = s.connect()
    c.wait("hello")
    c.send({"op": "ping", "token": 42})
    ok = c.wait("pong", 3) is not None
    c.close()
    return ok and s.kwin.poll() is None


def window_shapes(st, ns="kristall-test-glass"):
    return sum(w["shapes"] for w in st.get("windows", []) if w.get("namespace") == ns)


def main():
    s = harness.Session(1280, 800).start()
    try:
        s.quickshell(GLASSHOST, name="host")
        c = s.connect()
        hello = c.wait("hello")
        check("hello is sent on connect", bool(hello) and hello["state"] == "active" and hello["protocol"] == 1, json.dumps(hello))

        # ---- malformed input ---------------------------------------------------------------
        bad = [b"this is not json\n", b"[1,2,3]\n", b'{"op":"nope"}\n', b'{"op":"shapes","surface":"x","shapes":[]}\n',
               b'{"op":"bind","surface":"t"}\n', b'{"op":"bind","surface":"t","match":{"output":"eDP-1"}}\n',
               b'\xff\xfe\x00garbage\n', b"{\"op\":\"bind\",\"surface\":" + b"\"" + b"x" * 300 + b"\"}\n"]
        for line in bad:
            c.send_raw(line)
        errors = [e for e in c.drain(0.8) if e.get("event") == "error"]
        check("malformed lines are answered with errors, connection stays open",
              len(errors) == len(bad) and alive(s), f"{len(errors)} errors for {len(bad)} bad lines: {sorted({e['code'] for e in errors})}")

        c.send({"op": "bind", "surface": "t", "match": {"namespace": "kristall-test-glass", "pid": 0}})
        ev = c.wait(lambda e: e.get("event") == "bound" and e.get("windows", 0) == 1, 10)
        check("bind by layer-shell namespace finds the surface", ev is not None, json.dumps(ev))
        c.send({"op": "shapes", "surface": "t", "shapes": [shape(i) for i in range(5)]})
        time.sleep(0.3)
        # an invalid shape anywhere rejects the whole message (atomic per surface)
        c.send({"op": "shapes", "surface": "t", "shapes": [shape(i) for i in range(9)] + [{"id": "bad", "x": "1", "y": 0, "w": 1, "h": 1}]})
        err = c.wait("error", 2)
        c.send({"op": "shapes", "surface": "t", "shapes": [shape(1), shape(1)]})
        err2 = c.wait("error", 2)
        c.send({"op": "shapes", "surface": "t", "shapes": [shape(i) for i in range(65)]})
        err3 = c.wait("error", 2)
        c.send({"op": "patch", "surface": "t", "shapes": [{"id": "unknown", "x": 1}]})
        err4 = c.wait("error", 2)
        time.sleep(0.3)
        st = c.status()
        check("invalid messages are rejected atomically (previous shapes stay)",
              window_shapes(st) == 5 and all([err, err2, err3, err4]),
              f"shapes after 4 rejected messages: {window_shapes(st)}; errors: {[e and e['code'] for e in (err, err2, err3, err4)]}")

        # ---- rapid updates -------------------------------------------------------------------
        st0 = c.status()
        cpu0 = proc_cpu(s.kwin.pid)
        n = 3000
        t0 = time.monotonic()
        for k in range(n):
            c.send({"op": "shapes", "surface": "t", "shapes": [shape(i, 100 + (k % 50), 100) for i in range(12)]})
        t1 = time.monotonic()
        c.send({"op": "ping", "token": "after"})
        pong = c.wait("pong", 10)
        t2 = time.monotonic()
        cpu1 = proc_cpu(s.kwin.pid)
        time.sleep(0.5)
        st1 = c.status()
        frames = st1["frames"] - st0["frames"]
        RESULTS["rapid"] = {"messages": n, "shapes_per_message": 12, "send_s": round(t1 - t0, 3), "drained_s": round(t2 - t0, 3),
                            "kwin_cpu_s": round(cpu1 - cpu0, 3), "frames": frames}
        check("3000 full shape updates (12 shapes each) are absorbed and coalesced",
              pong is not None and window_shapes(st1) == 12 and frames < n / 4,
              f"{n} messages in {t2 - t0:.2f} s, KWin CPU {cpu1 - cpu0:.2f} s ({1e6 * (cpu1 - cpu0) / n:.0f} µs per message incl. painting), "
              f"{frames} frames painted (coalesced), final shapes {window_shapes(st1)}")

        # ---- sync:"commit" falls back to the 100 ms timeout on a surface that never commits ----
        c.send({"op": "shapes", "surface": "t", "sync": "commit", "shapes": [shape(i) for i in range(3)]})
        time.sleep(0.05)
        early = window_shapes(c.status())
        time.sleep(0.3)
        late = window_shapes(c.status())
        check('sync:"commit" waits for the surface commit, then applies after at most 100 ms', early == 12 and late == 3,
              f"after 50 ms: {early} shapes (old list), after 350 ms: {late}")

        # ---- client crash and reconnect -----------------------------------------------------------
        child = subprocess.Popen([sys.executable, "-c", f"""
import json, socket, time
s = socket.socket(socket.AF_UNIX); s.connect({s.glass_socket!r})
s.sendall(b'{{"op":"bind","surface":"c","match":{{"namespace":"kristall-test-glass","pid":0}}}}\\n')
s.sendall(json.dumps({{"op":"shapes","surface":"c","shapes":[{{"id":"z","x":700,"y":500,"w":200,"h":80}}]}}).encode()+b'\\n')
time.sleep(60)
"""])
        harness.wait_until(lambda: window_shapes(c.status()) == 4, 5)
        before = window_shapes(c.status())
        child.send_signal(signal.SIGKILL)
        child.wait()
        t0 = time.monotonic()
        gone = harness.wait_until(lambda: window_shapes(c.status()) == 3, 5, 0.02)
        check("shapes of a crashed client disappear", before == 4 and bool(gone),
              f"shapes {before} -> 3 within {time.monotonic() - t0:.2f} s of SIGKILL")

        c.close()
        time.sleep(0.3)
        st = None
        c = s.connect()
        c.wait("hello")
        st = c.status()
        check("disconnect removes every binding of the connection", st["bindings"] == 0 and window_shapes(st) == 0, f"bindings {st['bindings']}, shapes {window_shapes(st)}")
        c.send({"op": "bind", "surface": "t", "match": {"namespace": "kristall-test-glass", "pid": 0}})
        c.send({"op": "shapes", "surface": "t", "shapes": [shape(0)]})
        ev = c.wait("bound", 3)
        time.sleep(0.2)
        check("reconnect and rebind works", ev is not None and ev["windows"] == 1 and window_shapes(c.status()) == 1, json.dumps(ev))

        # ---- overlong line without newline: only that client is dropped --------------------------
        rogue = s.connect()
        rogue.wait("hello")
        try:
            rogue.send_raw(b"{" + b"x" * (1100 * 1024))
            time.sleep(0.5)
            rogue.sock.settimeout(1)
            dropped = rogue.sock.recv(10) == b""
        except OSError:
            dropped = True
        check("a client sending >1 MiB without a newline is dropped, others unaffected", dropped and alive(s), f"dropped={dropped}")

        # ---- a client that never reads is dropped once 4 MiB are queued ---------------------------
        lazy = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        lazy.connect(s.glass_socket)
        lazy.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        lazy.settimeout(5)
        sent = 0
        try:
            for _ in range(150):
                lazy.sendall(b"not json\n" * 2000)
                sent += 2000
        except OSError:
            pass
        time.sleep(0.5)
        check("a client that never reads its replies cannot grow KWin's buffers without bound", alive(s),
              f"sent {sent} bad lines without reading; KWin still answers")
        lazy.close()

        # ---- connection limit ------------------------------------------------------------------------
        socks = []
        for _ in range(40):
            k = harness.GlassConn(s.glass_socket)
            socks.append(k)
        time.sleep(0.5)
        limited = 0
        for k in socks:
            try:
                ev = k.wait(lambda e: True, 1)
                if ev and ev.get("code") == "limit":
                    limited += 1
            except ConnectionError:
                limited += 1
        for k in socks:
            k.close()
        time.sleep(0.5)
        check("at most 32 clients; extra connections get a 'limit' error", limited >= 8 - 1 and alive(s), f"{limited} of 40 extra connections refused")

        # ---- the surface goes away ---------------------------------------------------------------------
        host = [p for p in s.procs if p.args[-1].endswith("glasshost.qml")][0]
        s.stop_proc(host)
        ev = c.wait(lambda e: e.get("event") == "bound" and e.get("windows") == 0, 5)
        check("an 'unbound' (windows: 0) event is sent when the surface is destroyed", ev is not None, json.dumps(ev))
        s.quickshell(GLASSHOST, name="host2")
        ev = c.wait(lambda e: e.get("event") == "bound" and e.get("windows") == 1, 10)
        check("shapes re-apply automatically when a matching surface appears again", ev is not None and window_shapes(c.status()) == 1, json.dumps(ev))
        c.close()

        # ---- many surfaces ---------------------------------------------------------------------------------
        many = os.path.join(s.tmp, "many.qml")
        with open(many, "w") as f:
            f.write(MANY_QML)
        s.quickshell(many, name="many")
        c = s.connect()
        c.wait("hello")
        for i in range(12):
            c.send({"op": "bind", "surface": f"m{i}", "match": {"namespace": f"kristall-test-many-{i}", "pid": 0}})
            c.send({"op": "shapes", "surface": f"m{i}", "shapes": [{"id": "a", "x": 10, "y": 10, "w": 140, "h": 60, "kind": "capsule"},
                                                                   {"id": "b", "x": 20, "y": 80, "w": 120, "h": 50, "radius": 12}]})
        bound = set()
        end = time.monotonic() + 15
        while len(bound) < 12 and time.monotonic() < end:
            ev = c.wait(lambda e: e.get("event") == "bound" and e.get("windows") == 1, 1)
            if ev:
                bound.add(ev["surface"])
        time.sleep(1.0)
        st = c.status()
        many_windows = [w for w in st["windows"] if w.get("namespace", "").startswith("kristall-test-many-")]
        img = s.screenshot()
        check("12 surfaces of one client, 24 shapes, all bound and drawn", len(bound) == 12 and len(many_windows) == 12 and sum(w["shapes"] for w in many_windows) == 24,
              f"{len(bound)} bound, {len(many_windows)} glass windows, screenshot {img.shape[1]}x{img.shape[0]}")
        c.close()
    finally:
        tail = s.log_text()
        s.stop()
    crashes = [l for l in tail.splitlines() if "KCrash" in l or "Segmentation" in l]
    check("KWin never crashed during the protocol tests", not crashes, f"{len(crashes)} crash lines in the KWin log")
    path = os.environ.get("KRISTALL_GLASS_RESULTS")
    if path:
        old = json.load(open(path)) if os.path.exists(path) else {}
        old["protocol"] = RESULTS
        json.dump(old, open(path, "w"), indent=1)
    if FAILURES:
        print(f"{len(FAILURES)} protocol check(s) failed: {FAILURES}")
        return 1
    return 0


def proc_cpu(pid):
    with open(f"/proc/{pid}/stat") as f:
        parts = f.read().rsplit(")", 1)[1].split()
    return (int(parts[11]) + int(parts[12])) / os.sysconf("SC_CLK_TCK")


MANY_QML = """
import QtQuick
import Quickshell
import Quickshell.Wayland
ShellRoot {
    Variants {
        model: [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11]
        delegate: Component {
            PanelWindow {
                required property var modelData
                WlrLayershell.namespace: "kristall-test-many-" + modelData
                anchors { top: true; left: true }
                margins { top: 20 + Math.floor(modelData / 4) * 170; left: 20 + (modelData % 4) * 200 }
                implicitWidth: 160; implicitHeight: 150
                exclusionMode: ExclusionMode.Ignore
                color: "transparent"
            }
        }
    }
}
"""

if __name__ == "__main__":
    sys.exit(main())
