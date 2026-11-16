# SPDX-License-Identifier: GPL-3.0-or-later
"""hands against the real kristall-bridge plugin in a headless KWin, through the installed
/usr/bin/kristall-hands (so the bridge's peer check runs for real: KRISTALL_BRIDGE_DEV is off).

Dev container only.  Prerequisites (tests/run.sh does both when the bridge sources exist):
  KRISTALL_BRIDGE_BUILD=/tmp/kb kwin/bridge/tests/build.sh      (the bridge team's build script)
  KRISTALL_SKIP_SYSTEM_PACKAGES=1 assistant/hands/image/install.sh   (into the container's /usr)
Uses the bridge team's test harness (kwin/bridge/tests/support/harness.py) read-only."""
import base64
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
BUILD = os.environ.setdefault("KRISTALL_BRIDGE_BUILD", "/tmp/kb")
HARNESS = os.path.join(REPO, "kwin/bridge/tests/support")
HAVE = (os.path.exists(os.path.join(BUILD, "plugins/kwin/plugins/kristall_bridge.so")) and os.path.exists(HARNESS)
        and os.path.exists("/usr/bin/kristall-hands") and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")))
if HAVE:
    sys.path.insert(0, HARNESS)
    import harness  # noqa: E402
from support.mock_daemon import MockDaemon  # noqa: E402
from support import png  # noqa: E402

REPORT = []


class Mcp:
    def __init__(self, env):
        self.p = subprocess.Popen(["/usr/bin/kristall-hands"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(os.path.join(env["XDG_RUNTIME_DIR"], "hands.log"), "w"), env=env)
        self.n = 0
        self.lock = threading.Lock()

    def rpc(self, method, params=None, timeout=60):
        with self.lock:
            self.n += 1
            self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode())
            self.p.stdin.flush()
            line = self.p.stdout.readline()
        return json.loads(line)

    def call(self, tool, **args):
        t0 = time.monotonic()
        r = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        txt = "\n".join(c["text"] for c in r["content"] if c["type"] == "text")
        imgs = [base64.b64decode(c["data"]) for c in r["content"] if c["type"] == "image"]
        REPORT.append(f"{tool} {json.dumps(args, ensure_ascii=False)[:80]} -> {'ERROR ' if r.get('isError') else ''}"
                      f"{txt.splitlines()[0][:110] if txt else ''} ({(time.monotonic() - t0) * 1000:.0f} ms)")
        return txt, imgs, bool(r.get("isError"))

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)


def editor_text(name):
    import gi
    gi.require_version("Atspi", "2.0")
    from gi.repository import Atspi
    d = Atspi.get_desktop(0)

    def find(a, depth=0):
        if depth > 40:
            return None
        if a.get_role_name() == "text" and name in (a.get_name() or ""):
            return a
        for i in range(a.get_child_count()):
            c = a.get_child_at_index(i)
            if c is not None:
                r = find(c, depth + 1)
                if r is not None:
                    return r
        return None
    for i in range(d.get_child_count()):
        app = d.get_child_at_index(i)
        if app.get_name() == "kate":
            ed = find(app)
            if ed is not None:
                return Atspi.Text.get_text(ed, 0, Atspi.Text.get_character_count(ed))
    return None


@unittest.skipUnless(HAVE, "needs the built bridge, the installed kristall-hands and dbus-run-session")
class RealBridge(unittest.TestCase):
    def test_hands_on_real_bridge(self):
        tmp = tempfile.mkdtemp(prefix="kristall-rb-")
        doc = os.path.join(tmp, "liste.txt")
        with open(doc, "w") as f:
            f.write("")
        s = harness.Session(dev=False, scale=float(os.environ.get("KRISTALL_TEST_SCALE", "1.0")), name="hands-rb").start()
        try:
            os.environ["XDG_RUNTIME_DIR"] = s.runtime
            os.environ["WAYLAND_DISPLAY"] = s.wayland
            subprocess.run(["gdbus", "call", "--session", "-d", "org.a11y.Bus", "-o", "/org/a11y/bus", "-m",
                            "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", "IsEnabled", "<false>"], capture_output=True)
            daemon = MockDaemon(os.path.join(s.runtime, "kristall", "assistant.sock")).start()
            env = s.env()
            env.update({"KRISTALL_HANDS_LOG_STDERR": "1", "KRISTALL_SETTINGS_BIN": "/nonexistent", "QT_QPA_PLATFORM": "wayland"})
            env.pop("KRISTALL_BRIDGE_DEV", None)
            # the app is started by hands' own launcher path would need desktop files; start it directly
            s.spawn(["kate", "-n", doc], "kate", env={"QT_QPA_PLATFORM": "wayland"})
            b = s.bridge("observer")
            w = harness.find_window(b, lambda w: "liste.txt" in w["title"], 15)
            self.assertIsNotNone(w, "Kate did not open")
            before_ptr = b.call("cursor.get")
            m = Mcp(env)
            r = m.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
            self.assertEqual(r["result"]["serverInfo"]["name"], "kristall-hands")
            txt, _, err = m.call("list_windows")
            self.assertFalse(err, txt)
            self.assertIn("liste.txt", txt)
            # tier 3: a window screenshot through the bridge, with the real scale metadata
            txt, imgs, err = m.call("screenshot", window="Kate")
            self.assertFalse(err, txt)
            img = png.decode(imgs[0])
            REPORT.append(f"   screenshot image {img[0]}x{img[1]}; text: {txt.splitlines()[0]}")
            # tier 2 needs accessibility, which hands switches on itself; Kate (Qt) follows live
            txt, _, err = m.call("ui_tree", window="Kate")
            self.assertFalse(err, txt)
            ed = next(l.split()[0] for l in txt.splitlines() if l.strip().startswith("e") and ' text "liste.txt"' in l)
            ed = ed.strip()
            new_btn = next(l.split()[0] for l in txt.splitlines() if 'button "New"' in l).strip()
            # keyboard: focus the editor via a real click on it (tier 3 with a ref), then type
            txt, _, err = m.call("click", ref=ed, intent="Klicke in den Text")
            self.assertFalse(err, txt)
            text = "Einkaufsliste:\n- Äpfel\n- Käse — 5 € 🙂 @markt"
            txt, _, err = m.call("type_text", text=text, intent="Schreibe die Liste")
            self.assertFalse(err, txt)
            time.sleep(0.5)
            got = editor_text("liste.txt")
            REPORT.append(f"   editor after type_text: {got!r}")
            self.assertEqual(got, text)
            txt, _, err = m.call("press_keys", keys="ctrl+a")
            self.assertFalse(err, txt)
            txt, _, err = m.call("type_text", text="Neu")
            time.sleep(0.4)
            got2 = editor_text("liste.txt")
            REPORT.append(f"   editor after ctrl+a + type: {got2!r}")
            self.assertEqual(got2, "Neu")
            # a real pointer click on a toolbar button found through ui_tree
            txt, _, err = m.call("click", ref=new_btn, intent="Neues Dokument")
            self.assertFalse(err, txt)
            ok = harness.wait_until(lambda: any("Untitled" in x["title"] for x in b.call("window.list")["windows"]), 5)
            REPORT.append(f"   click on 'New' opened a new document: {bool(ok)}; result: {txt.splitlines()[0]}")
            self.assertTrue(ok)
            # windows
            txt, _, err = m.call("window", action="maximize", window="Kate")
            self.assertFalse(err, txt)
            # zoom into the last screenshot
            txt, imgs, err = m.call("screenshot", target="screen")
            self.assertFalse(err, txt)
            txt, imgs, err = m.call("zoom", x0=0, y0=0, x1=200, y1=100)
            self.assertFalse(err, txt)
            REPORT.append(f"   zoom image {png.decode(imgs[0])[:2]}")
            # the owner's pointer never moved
            after_ptr = b.call("cursor.get")
            REPORT.append(f"   owner pointer before {before_ptr} after {after_ptr}")
            self.assertEqual(before_ptr, after_ptr)
            # Escape by the owner ends the session; hands tells the model to stop
            owner = s.owner()
            owner.key(harness.KEY_ESC, True)
            owner.key(harness.KEY_ESC, False)
            time.sleep(0.5)
            txt, _, err = m.call("click", x=10, y=10)
            REPORT.append(f"   after owner Escape: {txt[:90]}")
            self.assertIn("Escape", txt)
            m.close()
            ev = daemon.cursor_events()
            REPORT.append(f"   agent_cursor events published: {len(ev)}; first {ev[0][1] if ev else None}")
            self.assertTrue(ev)
            # an untrusted peer (plain python3 -c) is refused by the bridge
            r = subprocess.run([sys.executable, "-c", (
                "import socket,json,os;s=socket.socket(socket.AF_UNIX);s.connect(os.environ['P']);"
                "s.sendall(b'{\"id\":1,\"method\":\"screenshot\",\"params\":{\"target\":\"desktop\"}}\\n');"
                "print(s.recv(4096).decode())")], env=dict(os.environ, P=s.socket), capture_output=True, text=True, timeout=10)
            REPORT.append(f"   untrusted python3 peer: {r.stdout.strip()[:120]}")
            self.assertIn("denied", r.stdout)
        finally:
            print("\n   real bridge session:\n   " + "\n   ".join(REPORT))
            log = os.path.join(s.runtime, "hands.log")
            if os.path.exists(log):
                print("   hands log (tail):\n" + "".join(open(log).readlines()[-15:]))
            s.stop()


if __name__ == "__main__":
    unittest.main()
