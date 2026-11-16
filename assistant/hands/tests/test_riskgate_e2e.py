# SPDX-License-Identifier: GPL-3.0-or-later
"""The risky-target gate end to end (hands.md §10): the installed /usr/bin/kristall-hands over MCP
against the real kristall-bridge in a headless KWin, a real GTK 3 window (tests/support/riskwin.py)
read through AT-SPI, and the assistant daemon's real permission policy deciding each call the way
the daemon does (assistant/core/kristall_assistant/policy, with the installed mcp.d drop-in).

The "owner" in this test answers every permission prompt with "allow once" and records it, so the
log shows the whole flow: the model's call without risk is allowed by the policy and refused by
hands with the guiding error; the retry with the named risk makes the policy ask the owner; only
then does the click reach the app.

Dev container only, same prerequisites as test_real_bridge.py (tests/run.sh prepares them)."""
import base64
import json
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

HERE = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, HERE)
BUILD = os.environ.setdefault("KRISTALL_BRIDGE_BUILD", "/tmp/kb")
HARNESS = os.path.join(REPO, "kwin/bridge/tests/support")
CORE = os.path.join(REPO, "assistant/core")
DROPIN = "/usr/share/kristall/assistant/mcp.d/50-hands.json"
HAVE = (os.path.exists(os.path.join(BUILD, "plugins/kwin/plugins/kristall_bridge.so")) and os.path.exists(HARNESS)
        and os.path.exists("/usr/bin/kristall-hands") and os.path.exists(DROPIN)
        and os.path.isdir(os.path.join(CORE, "kristall_assistant")) and bool(os.environ.get("DBUS_SESSION_BUS_ADDRESS")))
if HAVE:
    sys.path.insert(0, HARNESS)
    import harness  # noqa: E402
    sys.path.insert(0, CORE)
    from kristall_assistant.brain import mcp_config  # noqa: E402
    from kristall_assistant.policy.policy import GrantStore, Policy, PolicyPaths  # noqa: E402
from support.mock_daemon import MockDaemon  # noqa: E402
from support import png  # noqa: E402

LOG = []
TITLE = "Neue Nachricht – Testpost"


class Mcp:
    def __init__(self, env, logfile):
        self.p = subprocess.Popen(["/usr/bin/kristall-hands"], stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                  stderr=open(logfile, "w"), env=env)
        self.n = 0
        self.lock = threading.Lock()

    def rpc(self, method, params=None):
        with self.lock:
            self.n += 1
            self.p.stdin.write((json.dumps({"jsonrpc": "2.0", "id": self.n, "method": method, "params": params or {}}) + "\n").encode())
            self.p.stdin.flush()
            return json.loads(self.p.stdout.readline())

    def call(self, tool, args):
        r = self.rpc("tools/call", {"name": tool, "arguments": args})["result"]
        txt = "\n".join(c["text"] for c in r["content"] if c["type"] == "text")
        imgs = [c["data"] for c in r["content"] if c["type"] == "image"]
        return txt, imgs, bool(r.get("isError"))

    def close(self):
        self.p.stdin.close()
        self.p.wait(10)


class Daemon:
    """What the assistant daemon does for each tool call: policy first, the owner when it asks."""

    def __init__(self, mcp, workspace):
        setup = mcp_config.load([Path(os.path.dirname(DROPIN))])
        self.policy = Policy(PolicyPaths(workspace, []), GrantStore(None), setup.decls)
        self.mcp = mcp
        self.prompts = []

    def call(self, tool, **args):
        d = self.policy.evaluate("mcp__hands__" + tool, args)
        shown = {k: v for k, v in args.items() if k not in ("intent",)}
        if d.verdict == "deny":
            LOG.append(f"{tool} {json.dumps(shown, ensure_ascii=False)} -> policy deny")
            return "", [], True, d
        if d.verdict == "ask":
            self.prompts.append(d)
            LOG.append(f"   policy: ask {d.category} (can_always={d.can_always}) „{d.question['de']}“ -> owner: allow_once")
        elif d.granted:
            LOG.append(f"   policy: allow ({d.category}, granted earlier with 'always')")
        t0 = time.monotonic()
        txt, imgs, err = self.mcp.call(tool, args)
        first = txt.splitlines()[0] if txt else ""
        LOG.append(f"{tool} {json.dumps(shown, ensure_ascii=False)[:90]} -> policy {d.verdict}/{d.category}; hands "
                   f"{'ERROR ' if err else ''}{first[:260]} ({(time.monotonic() - t0) * 1000:.0f} ms)")
        return txt, imgs, err, d


def build_qt():
    """Compiles tests/support/riskwin_qt.cpp once (dev container: qt6-qtbase-devel); None without Qt."""
    out = os.path.join(os.environ.get("KRISTALL_BRIDGE_BUILD", "/tmp"), "riskwin_qt")
    if os.path.exists(out):
        return out
    try:
        flags = subprocess.run(["pkg-config", "--cflags", "--libs", "Qt6Widgets"], capture_output=True, text=True,
                               check=True).stdout.split()
        subprocess.run(["g++", "-std=c++17", "-O1", "-fPIC", os.path.join(HERE, "support", "riskwin_qt.cpp"), *flags,
                        "-o", out], check=True, capture_output=True, timeout=300)
    except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired):
        return None
    return out


def bounds(tree, needle):
    """(ref, x, y, w, h) of the first line of a ui_tree that contains needle."""
    for line in tree.splitlines():
        if needle in line:
            ref = line.split()[0]
            m = re.search(r"@(-?\d+),(-?\d+) (\d+)x(\d+)", line)
            if m:
                return (ref,) + tuple(int(v) for v in m.groups())
            return (ref, None, None, None, None)
    raise AssertionError(f"{needle!r} not in ui_tree:\n{tree}")


@unittest.skipUnless(HAVE, "needs the built bridge, the installed kristall-hands and its drop-in, assistant/core "
                           "and dbus-run-session")
class RiskGateEndToEnd(unittest.TestCase):
    def test_gtk3_window(self):
        self.flow("GTK 3", [sys.executable, os.path.join(HERE, "support", "riskwin.py"), TITLE], {"GDK_BACKEND": "wayland"})

    def test_qt_window(self):
        exe = build_qt()
        if exe is None:
            self.skipTest("no Qt 6 Widgets development files to build tests/support/riskwin_qt.cpp")
        self.flow("Qt 6", [exe, TITLE], {"QT_QPA_PLATFORM": "wayland", "QT_LINUX_ACCESSIBILITY_ALWAYS_ON": "1"})

    def flow(self, toolkit, cmd, app_env):
        scale = float(os.environ.get("KRISTALL_TEST_SCALE", "1.0"))
        LOG.append(f"--- {toolkit} window, output scale {scale}")
        tmp = tempfile.mkdtemp(prefix="kristall-riskgate-")
        s = harness.Session(dev=False, scale=scale, name="hands-riskgate").start()
        hands_log = os.path.join(s.runtime, "hands.log")
        m = None
        try:
            os.environ["XDG_RUNTIME_DIR"] = s.runtime
            os.environ["WAYLAND_DISPLAY"] = s.wayland
            MockDaemon(os.path.join(s.runtime, "kristall", "assistant.sock")).start()
            env = s.env()
            env.update({"KRISTALL_HANDS_LOG_STDERR": "1", "KRISTALL_HANDS_DEBUG": "1",
                        "KRISTALL_SETTINGS_BIN": "/nonexistent", "QT_QPA_PLATFORM": "wayland"})
            env.pop("KRISTALL_BRIDGE_DEV", None)
            app = s.spawn(cmd, "riskwin", env=app_env)
            b = s.bridge("observer")
            w = harness.find_window(b, lambda w: w["title"] == TITLE, 15)
            self.assertIsNotNone(w, "the GTK window did not open")
            m = Mcp(env, hands_log)
            m.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
            d = Daemon(m, tmp)

            def clicks(name, since):
                return [e for e in app.since(since) if e.get("ev") == "clicked" and e.get("name") == name]

            def settle(pred, timeout=3.0):
                return harness.wait_until(pred, timeout)

            def tree(**kw):
                txt, _, err, _ = d.call("ui_tree", **kw)
                self.assertFalse(err, txt)
                return txt

            def win_by_title(title):
                return next(x for x in b.call("window.list")["windows"] if x["title"] == title)

            t = tree(window=TITLE)
            send, abort, trash, clear = (bounds(t, f'button "{n}"') for n in ("Senden", "Abbrechen", "In den Papierkorb", "Text löschen"))
            tidy = bounds(t, 'button "Aufräumen')
            entry = bounds(t, " text =\"Hallo Oma")

            # 1. click and ui_act on "Senden" without risk: refused with the guiding error, nothing clicked
            mark = app.mark()
            txt, _, err, dec = d.call("click", ref=send[0], intent="Klicke auf „Senden“")
            self.assertTrue(err)
            self.assertEqual(dec.verdict, "allow")             # the policy alone would have let it through
            # (the Qt twin's window is a QDialog, so it is described as a dialog with its label)
            self.assertRegex(txt, '^This looks like a "send" action \\(button "Senden" in (the dialog )?"' + re.escape(TITLE)
                             + '( · Nachricht an Oma:)?"\\)\\. If the owner asked for this, call click again with the '
                             'same arguments plus risk:"send"; the owner will be asked to confirm\\.')
            txt, _, err, _ = d.call("ui_act", ref=send[0], action="press")
            self.assertTrue(err)
            self.assertIn('call ui_act again with the same arguments plus risk:"send"', txt)
            time.sleep(0.5)
            self.assertEqual(clicks("Senden", mark), [], "Senden was activated without risk")

            # ... and with risk:"send" the policy asks the owner (no "always"), then it goes through
            n_prompts = len(d.prompts)
            txt, _, err, dec = d.call("click", ref=send[0], risk="send", intent="Klicke auf „Senden“")
            self.assertFalse(err, txt)
            self.assertEqual((dec.verdict, dec.category, dec.can_always), ("ask", "send", False))
            self.assertEqual(len(d.prompts), n_prompts + 1)
            self.assertTrue(settle(lambda: clicks("Senden", mark)), "click with risk did not reach the app")
            mark = app.mark()
            txt, _, err, dec = d.call("ui_act", ref=send[0], action="press", risk="send")
            self.assertFalse(err, txt)
            self.assertEqual((dec.verdict, dec.category), ("ask", "send"))
            self.assertTrue(settle(lambda: clicks("Senden", mark)), "ui_act with risk did not reach the app")

            # 2. harmless and reversible targets go through without risk and without a prompt
            n_prompts = len(d.prompts)
            for ref, name in ((abort[0], "Abbrechen"), (trash[0], "In den Papierkorb")):
                mark = app.mark()
                txt, _, err, _ = d.call("ui_act", ref=ref, action="press")
                self.assertFalse(err, txt)
                self.assertTrue(settle(lambda: clicks(name, mark)), name)
                mark = app.mark()
                txt, _, err, _ = d.call("click", ref=ref)
                self.assertFalse(err, txt)
                self.assertIn(f'target: button "{name}"', txt)
                self.assertTrue(settle(lambda: clicks(name, mark)), name)
            mark = app.mark()
            txt, _, err, _ = d.call("click", ref=clear[0], intent="Text löschen")
            self.assertFalse(err, txt)
            self.assertTrue(settle(lambda: clicks("Text löschen", mark)))
            self.assertEqual(len(d.prompts), n_prompts)

            # 3. coordinate clicks resolve the same way (AT-SPI point query on the window under the point)
            txt, imgs, err, _ = d.call("screenshot", target="screen")
            self.assertFalse(err, txt)
            iw, ih = png.decode(base64.b64decode(imgs[0]))[:2]
            sx = iw / (s.width / scale)                       # image px per logical px (output at 0,0)
            c = win_by_title(TITLE)["content"]

            def px(bx):
                _, x, y, ww, hh = bx
                return round((c["x"] + x + ww / 2) * sx), round((c["y"] + y + hh / 2) * sx)
            sx_, sy_ = px(send)
            mark = app.mark()
            txt, _, err, _ = d.call("click", x=sx_, y=sy_)
            self.assertTrue(err)
            self.assertRegex(txt, '^This looks like a "send" action \\(button "Senden" in (the dialog )?"' + re.escape(TITLE))
            self.assertIn('call click again with the same arguments plus risk:"send"', txt)
            time.sleep(0.4)
            self.assertEqual(clicks("Senden", mark), [])
            txt, _, err, dec = d.call("click", x=sx_, y=sy_, risk="send")
            self.assertFalse(err, txt)
            self.assertEqual((dec.verdict, dec.category, dec.can_always), ("ask", "send", False))
            self.assertIn('target: button "Senden" (send; risk send declared)', txt)
            self.assertTrue(settle(lambda: clicks("Senden", mark)))
            for bx, name in ((abort, "Abbrechen"), (trash, "In den Papierkorb")):
                mark = app.mark()
                x, y = px(bx)
                txt, _, err, _ = d.call("click", x=x, y=y)
                self.assertFalse(err, txt)
                self.assertIn(f'target: button "{name}"', txt)
                self.assertTrue(settle(lambda: clicks(name, mark)), name)
            # a drag that starts on "Senden" is a press on it
            x, y = px(send)
            txt, _, err, _ = d.call("drag", x=x, y=y, x2=x + 3, y2=y)
            self.assertTrue(err)
            self.assertIn('call drag again with the same arguments plus risk:"send"', txt)
            # nothing accessible at the point (the empty desktop): not blocked, recorded as unknown
            ex, ey = round((s.width / scale - 4) * sx), round((s.height / scale - 4) * sx)
            if not any(x["x"] <= ex / sx <= x["x"] + x["w"] and x["y"] <= ey / sx <= x["y"] + x["h"]
                       for x in b.call("window.list")["windows"]):
                txt, _, err, _ = d.call("click", x=ex, y=ey)
                self.assertFalse(err, txt)
                self.assertIn("target: unknown", txt)

            # 4. Return in the entry presses the window's default button "Senden"
            txt, _, err, _ = d.call("ui_act", ref=entry[0], action="focus")
            self.assertFalse(err, txt)
            mark = app.mark()
            txt, _, err, _ = d.call("press_keys", keys="Enter", window=TITLE)
            self.assertTrue(err)
            self.assertIn('Return would press the default button "Senden"', txt)
            txt, _, err, _ = d.call("type_text", text="Bis bald", enter=True, window=TITLE)
            self.assertTrue(err)
            self.assertIn('call type_text again with the same arguments plus risk:"send"', txt)
            time.sleep(0.4)
            self.assertEqual(clicks("Senden", mark), [])
            txt, _, err, dec = d.call("press_keys", keys="Enter", window=TITLE, risk="send")
            self.assertFalse(err, txt)
            self.assertEqual(dec.category, "send")
            self.assertTrue(settle(lambda: clicks("Senden", mark)), "Return with risk did not send")

            # 5. the dialog "Möchtest du 3 Dateien endgültig löschen?": its OK is gated as files.delete
            mark = app.mark()
            txt, _, err, _ = d.call("ui_act", ref=tidy[0], action="press")
            self.assertFalse(err, txt)
            self.assertTrue(settle(lambda: [e for e in app.since(mark) if e.get("ev") == "dialog_open"]))
            self.assertTrue(settle(lambda: any(x["title"] == "Aufräumen" for x in b.call("window.list")["windows"]), 5))
            time.sleep(0.5)
            t = tree(window="Aufräumen")
            ok, cancel = bounds(t, 'button "OK"'), bounds(t, 'button "Abbrechen"')
            txt, _, err, dec = d.call("click", ref=ok[0], intent="Bestätigen")
            self.assertTrue(err)
            self.assertEqual(dec.verdict, "allow")
            self.assertIn('This looks like a "delete" action (button "OK" in the dialog "', txt)
            self.assertIn("Möchtest du 3 Dateien endgültig löschen?", txt)
            self.assertIn('plus risk:"files.delete"', txt)
            txt, _, err, _ = d.call("ui_act", ref=ok[0], action="press")
            self.assertTrue(err)
            self.assertIn('risk:"files.delete"', txt)
            dc = win_by_title("Aufräumen")["content"]
            okx, oky = round((dc["x"] + ok[1] + ok[3] / 2) * sx), round((dc["y"] + ok[2] + ok[4] / 2) * sx)
            txt, _, err, _ = d.call("click", x=okx, y=oky)
            self.assertTrue(err)
            self.assertIn('"delete" action (button "OK" in the dialog', txt)
            txt, _, err, _ = d.call("press_keys", keys="Return", window="Aufräumen")
            self.assertTrue(err)
            self.assertRegex(txt, r'Return would press the (default|focused) button "OK" in the dialog')
            # a weaker declared risk is not enough
            txt, _, err, dec = d.call("click", ref=ok[0], risk="files.modify")
            self.assertTrue(err)
            self.assertIn('The declared risk:"files.modify" is not enough', txt)
            time.sleep(0.3)
            self.assertEqual([e for e in app.since(mark) if e.get("ev") == "dialog"], [])
            # "Abbrechen" in the same dialog is never gated
            txt, _, err, _ = d.call("click", ref=cancel[0])
            self.assertFalse(err, txt)
            self.assertTrue(settle(lambda: [e for e in app.since(mark) if e.get("response") == "cancel"]))

            # with risk:"files.delete" the owner is asked ("always" may be offered), then it runs;
            # after the owner granted "always" for deleting, the same call runs without a prompt
            for always in (False, True):
                mark = app.mark()
                txt, _, err, _ = d.call("ui_act", ref=tidy[0], action="press")
                self.assertTrue(settle(lambda: any(x["title"] == "Aufräumen" for x in b.call("window.list")["windows"]), 5))
                time.sleep(0.5)
                ok = bounds(tree(window="Aufräumen"), 'button "OK"')
                n_prompts = len(d.prompts)
                if always:
                    d.policy.grants.add("files.delete", "Löschen")
                    dc = win_by_title("Aufräumen")["content"]
                    okx, oky = round((dc["x"] + ok[1] + ok[3] / 2) * sx), round((dc["y"] + ok[2] + ok[4] / 2) * sx)
                    txt, _, err, dec = d.call("click", x=okx, y=oky, risk="files.delete")
                    self.assertEqual((dec.verdict, dec.granted), ("allow", True))
                    self.assertEqual(len(d.prompts), n_prompts)
                else:
                    txt, _, err, dec = d.call("click", ref=ok[0], risk="files.delete")
                    self.assertEqual((dec.verdict, dec.category, dec.can_always), ("ask", "files.delete", True))
                    self.assertEqual(len(d.prompts), n_prompts + 1)
                self.assertFalse(err, txt)
                self.assertTrue(settle(lambda: [e for e in app.since(mark) if e.get("response") == "ok"]),
                                f"OK with risk did not reach the dialog (always={always})")

            # the gate's timing, from hands' own log
            m.close()
            m = None
            lines = [ln.strip() for ln in open(hands_log, encoding="utf-8") if "riskgate" in ln]
            times = [float(x) for ln in lines for x in re.findall(r"\((\d+(?:\.\d+)?) ms\)", ln)]
            LOG.append(f"   hands log: {len(lines)} riskgate lines; lookup time max {max(times):.0f} ms, "
                       f"median {sorted(times)[len(times) // 2]:.0f} ms")
            LOG.extend("   " + ln[:230] for ln in lines[:6])
            self.assertTrue(times and max(times) < 1000)
        finally:
            if m is not None:
                m.close()
            print(f"\n   risky-target gate end to end ({toolkit}, scale {scale}):\n   " + "\n   ".join(LOG), flush=True)
            LOG.clear()
            if os.path.exists(hands_log):
                tail = [ln for ln in open(hands_log, encoding="utf-8").readlines() if "Traceback" in ln or "ERROR" in ln]
                if tail:
                    print("   hands log errors:\n" + "".join(tail[-10:]))
            s.stop()

    @unittest.skipUnless(os.path.exists("/usr/bin/firefox"), "needs Firefox")
    def test_web_page_in_firefox(self):
        """Web content: Firefox exposes the page through AT-SPI (accessibility is on from login), so a
        coordinate click on a page's "Jetzt kaufen" resolves to that button."""
        from support import firefox
        scale = float(os.environ.get("KRISTALL_TEST_SCALE", "1.0"))
        tmp = tempfile.mkdtemp(prefix="kristall-riskgate-ff-")
        s = harness.Session(dev=False, scale=scale, name="hands-riskgate-ff").start()
        hands_log = os.path.join(s.runtime, "hands.log")
        m = None
        log = []
        try:
            os.environ["XDG_RUNTIME_DIR"] = s.runtime
            os.environ["WAYLAND_DISPLAY"] = s.wayland
            subprocess.run(["gdbus", "call", "--session", "-d", "org.a11y.Bus", "-o", "/org/a11y/bus", "-m",
                            "org.freedesktop.DBus.Properties.Set", "org.a11y.Status", "IsEnabled", "<true>"],
                           capture_output=True)
            MockDaemon(os.path.join(s.runtime, "kristall", "assistant.sock")).start()
            page = os.path.join(tmp, "kasse.html")
            with open(page, "w", encoding="utf-8") as f:
                f.write(SHOP)
            profile = os.path.join(tmp, "profile")
            os.makedirs(profile)
            with open(os.path.join(profile, "user.js"), "w") as f:
                for k, v in firefox.PREFS.items():
                    f.write(f'user_pref("{k}", {json.dumps(v)});\n')
            s.spawn(["firefox", "--no-remote", "--new-instance", "--profile", profile, "file://" + page], "firefox",
                    env={"MOZ_ENABLE_WAYLAND": "1", "MOZ_CRASHREPORTER_DISABLE": "1", "HOME": tmp,
                         "GNOME_ACCESSIBILITY": "1"})
            b = s.bridge("observer")
            w = harness.find_window(b, lambda w: "Kasse" in w["title"], 60)
            self.assertIsNotNone(w, "Firefox did not open the page")
            env = s.env()
            env.update({"KRISTALL_HANDS_LOG_STDERR": "1", "KRISTALL_HANDS_DEBUG": "1", "KRISTALL_SETTINGS_BIN": "/nonexistent"})
            env.pop("KRISTALL_BRIDGE_DEV", None)
            m = Mcp(env, hands_log)
            m.rpc("initialize", {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": {"name": "t", "version": "1"}})
            d = Daemon(m, tmp)
            txt = ""
            end = time.monotonic() + 40
            while time.monotonic() < end and 'button "Jetzt kaufen"' not in txt:
                txt, _, _, _ = d.call("ui_tree", window="Firefox", find="kaufen")
                time.sleep(1)
            self.assertIn('button "Jetzt kaufen"', txt)
            buy = bounds(txt, 'button "Jetzt kaufen"')
            cart = bounds(d.call("ui_tree", window="Firefox", find="Warenkorb")[0], 'button "In den Warenkorb"')
            ok = bounds(d.call("ui_tree", window="Firefox", find="OK")[0], 'button "OK"')
            txt, imgs, err, _ = d.call("screenshot", target="screen")
            iw = png.decode(base64.b64decode(imgs[0]))[0]
            sx = iw / (s.width / scale)
            c = next(x for x in b.call("window.list")["windows"] if "Kasse" in x["title"])["content"]

            def px(bx):
                _, x, y, ww, hh = bx
                return round((c["x"] + x + ww / 2) * sx), round((c["y"] + y + hh / 2) * sx)

            def title():
                return next(x for x in b.call("window.list")["windows"] if x.get("appId", "").endswith("firefox")
                            or "Kasse" in x["title"] or "geklickt" in x["title"])["title"]
            x, y = px(buy)
            txt, _, err, _ = d.call("click", x=x, y=y)
            self.assertTrue(err, txt + "\n" + json.dumps(c) + str(buy))
            self.assertIn('This looks like a "purchase" action (button "Jetzt kaufen"', txt)
            self.assertIn('plus risk:"purchase"', txt)
            time.sleep(0.5)
            self.assertNotIn("geklickt", title())
            x, y = px(cart)
            txt, _, err, _ = d.call("click", x=x, y=y)
            self.assertFalse(err, txt)
            self.assertIn('target: button "In den Warenkorb"', txt)
            self.assertTrue(harness.wait_until(lambda: "In den Warenkorb geklickt" in title(), 5), title())
            x, y = px(ok)
            txt, _, err, _ = d.call("click", x=x, y=y)
            self.assertTrue(err, f"{txt}\n{ok} {c} {title()}")
            self.assertIn('"purchase" action (button "OK" in the dialog', txt)
            x, y = px(buy)
            txt, _, err, dec = d.call("click", x=x, y=y, risk="purchase")
            self.assertFalse(err, txt)
            self.assertEqual((dec.verdict, dec.category, dec.can_always), ("ask", "purchase", False))
            self.assertTrue(harness.wait_until(lambda: "Jetzt kaufen geklickt" in title(), 5), title())
            log.extend(LOG[-12:])
        finally:
            if m is not None:
                m.close()
            print(f"\n   Firefox page (scale {scale}):\n   " + "\n   ".join(log or LOG[-12:]), flush=True)
            LOG.clear()
            s.stop()


SHOP = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Kasse – Testladen</title>
<style>button{font-size:20px;margin:12px;padding:8px 16px}</style></head><body><h1>Dein Warenkorb</h1>
<p>Äpfel, 2 kg – 5,98 €</p>
<button onclick="document.title='Jetzt kaufen geklickt'">Jetzt kaufen</button>
<button onclick="document.title='In den Warenkorb geklickt'">In den Warenkorb</button>
<div role="dialog" aria-labelledby="q" style="border:1px solid #888;padding:8px;margin-top:20px">
<p id="q">Möchtest du jetzt zahlungspflichtig bestellen?</p>
<button onclick="document.title='OK geklickt'">OK</button></div></body></html>"""


if __name__ == "__main__":
    unittest.main()
