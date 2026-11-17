# SPDX-License-Identifier: GPL-3.0-or-later
# Agent keyboard and text: chords on the owner's German layout, the German test sentence through
# every text path, focus handling and restoration, clipboard restoration, owner priority, Escape.
import os
import subprocess
import sys
import time

from common import *  # noqa: F403

SENTENCE = "Schöne Grüße, läuft's? @home €5 😀"
GTKPROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clients", "gtkprobe.py")
KEY_Y, KEY_Z = 21, 44


def typed(proc, mark=0):
    """Text a wlprobe produced from key presses (its own xkb state, so it is what the app sees)."""
    return "".join(e["utf8"] for e in proc.since(mark) if e.get("ev") == "key" and e["state"] == 1)


def committed(proc, mark=0):
    return "".join(e["text"] for e in proc.since(mark) if e.get("ev") == "ti_commit")


def last_line(proc, mark=0):
    lines = [e["text"] for e in proc.since(mark) if e.get("ev") == "line"]
    return lines[-1] if lines else None


def keymap_layout(proc):
    names = [e["layout"] for e in proc.snapshot() if e.get("ev") == "keymap"]
    return names[-1] if names else None


def clipboard(s):
    try:
        return subprocess.run(["wl-paste", "--no-newline"], env=s.env(), capture_output=True, timeout=5).stdout.decode("utf-8", "replace")
    except subprocess.TimeoutExpired:
        return None


def set_clipboard(s, text):
    # wl-copy forks a server that keeps serving the selection
    subprocess.run(["wl-copy", text], env=s.env(), timeout=5)


@test
def test_german_sentence_every_path():
    """the German sentence arrives byte-for-byte on a German layout through each text path"""
    with Session(layout="de", xwayland=True) as s:
        b = s.bridge()
        ti = s.wlprobe("--title", "ti", "--text-input", "--size", "400x200")
        plain = s.wlprobe("--title", "plain", "--size", "400x200")
        wti = place(b, window_by_title(b, "ti"), 20, 20, 400, 200)
        wpl = place(b, window_by_title(b, "plain"), 20, 300, 400, 200)
        time.sleep(0.3)
        check("German" in (keymap_layout(plain) or ""), f"clients got the German keymap: {keymap_layout(plain)}")
        with b.agent_session("german") as a:
            m = ti.mark()
            r = a.text(SENTENCE, window_id=wti["id"])
            check(r["paths"] == ["textInput"], f"text-input-v3 client: path {r['paths']}")
            time.sleep(0.3)
            check(committed(ti, m) == SENTENCE, f"committed text is exact: {committed(ti, m)!r}")

            m = plain.mark()
            r = a.text(SENTENCE, window_id=wpl["id"])
            check(set(r["paths"]) == {"keymap", "temporaryKeymap"}, f"plain client: paths {r['paths']} segments {r['segments']}")
            time.sleep(0.3)
            check(typed(plain, m) == SENTENCE, f"typed text is exact: {typed(plain, m)!r}")
            check("German" in (keymap_layout(plain) or ""), "the client has the German keymap again afterwards")
            others = [e for e in ti.since(m) if e.get("ev") == "keymap"]
            check(not others, "the temporary keymap was sent only to the target client")

            m = ti.mark()
            r = a.text(SENTENCE, window_id=wti["id"], paths=["keymap", "temporaryKeymap"])
            time.sleep(0.3)
            check(typed(ti, m) == SENTENCE and committed(ti, m) == "", f"forced key paths on a text-input client: {typed(ti, m)!r}")

            # Qt native Wayland
            q = s.qtprobe("qtde")
            lay = qt_layout(q)
            qw = place(b, window_by_title(b, "qtde"), 500, 20, window_by_title(b, "qtde")["w"], window_by_title(b, "qtde")["h"])
            qx, qy = content(qw)
            a.click(qx + lay["line"]["x"] + 20, qy + lay["line"]["y"] + lay["line"]["h"] / 2)
            time.sleep(0.2)
            m = q.mark()
            r = a.text(SENTENCE, window_id=qw["id"])
            line = wait_until(lambda: last_line(q, m) == SENTENCE and last_line(q, m), 3) or last_line(q, m)
            check(line == SENTENCE, f"Qt (Wayland) line edit holds the sentence via {r['paths']}: {line!r}")

            # Qt under XWayland: characters outside the layout go through the clipboard
            set_clipboard(s, "ORIGINAL ♥ clipboard")
            time.sleep(0.3)
            check(clipboard(s) == "ORIGINAL ♥ clipboard", "clipboard prepared")
            x = s.qtprobe("qtx", platform="xcb")
            layx = qt_layout(x)
            xw = window_by_title(b, "qtx")
            xx, xy = content(xw)
            a.click(xx + layx["line"]["x"] + 20, xy + layx["line"]["y"] + layx["line"]["h"] / 2)
            time.sleep(0.3)
            m = x.mark()
            r = a.text(SENTENCE, window_id=xw["id"])
            line = wait_until(lambda: last_line(x, m) == SENTENCE and last_line(x, m), 3) or last_line(x, m)
            check(line == SENTENCE, f"Qt (XWayland) line edit holds the sentence via {r['paths']}: {line!r}")
            check("clipboard" in r["paths"] and "keymap" in r["paths"], f"XWayland used keymap + clipboard: {r['segments']}")
            time.sleep(0.5)
            check(clipboard(s) == "ORIGINAL ♥ clipboard", f"the owner's clipboard was restored: {clipboard(s)!r}")

            # XWayland and the temporary keymap (no clipboard): reported, not required
            m = x.mark()
            try:
                r = a.text("😀", window_id=xw["id"], paths=["temporaryKeymap"])
                time.sleep(0.5)
                note(f"XWayland + temporary keymap: line now {last_line(x, m)!r}")
            except BridgeError as e:
                note(f"XWayland + temporary keymap: {e}")

            # GTK 3 on Wayland
            g = s.spawn(["python3", GTKPROBE, "gtkde"], "gtk", env={"GDK_BACKEND": "wayland"})
            lg = g.wait("layout", 10)
            gw = window_by_title(b, "gtkde")
            if lg and gw:
                gx, gy = content(gw)
                a.click(gx + lg["line"]["x"] + 20, gy + lg["line"]["y"] + lg["line"]["h"] / 2)
                time.sleep(0.3)
                m = g.mark()
                r = a.text(SENTENCE, window_id=gw["id"])
                line = wait_until(lambda: last_line(g, m) == SENTENCE and last_line(g, m), 3) or last_line(g, m)
                check(line == SENTENCE, f"GTK 3 (Wayland) entry holds the sentence via {r['paths']}: {line!r}")
            else:
                check(False, f"GTK probe did not start: {g.snapshot()[-3:]}")


LETTER = "Liebe Grüße,\nich komme um 18 Uhr – @Büro.\n\tBis später, Jörg 😀\nTschüß"


def stream(proc, mark=0):
    """What a raw Wayland client received, in wire order: text-input commits and key presses
    (Return/Tab as \\n/\\t)."""
    out = []
    for e in proc.since(mark):
        if e.get("ev") == "ti_commit":
            out.append(e["text"])
        elif e.get("ev") == "key" and e["state"] == 1:
            out.append({"Return": "\n", "Tab": "\t"}.get(e["sym"], e["utf8"]))
    return "".join(out)


def last_of(proc, ev, mark=0):
    texts = [e["text"] for e in proc.since(mark) if e.get("ev") == ev]
    return texts[-1] if texts else None


@test
def test_multiline_text_in_order():
    """a multi-line German letter arrives in order on every path and every mix of paths (Qt, GTK, raw, XWayland)"""
    with Session(layout="de", xwayland=True) as s:
        b = s.bridge()
        ti = s.wlprobe("--title", "ti", "--text-input", "--size", "400x200")
        plain = s.wlprobe("--title", "plain", "--size", "400x200")
        wti = place(b, window_by_title(b, "ti"), 20, 20, 400, 200)
        wpl = place(b, window_by_title(b, "plain"), 20, 300, 400, 200)
        time.sleep(0.3)
        check("orderedText" in b.capabilities, "capability orderedText advertised")
        with b.agent_session("letter") as a:
            # raw clients: the wire order itself (textInput + keymap; keymap + temporaryKeymap)
            m = ti.mark()
            r = a.text(LETTER, window_id=wti["id"])
            check(set(r["paths"]) == {"textInput", "keymap"}, f"text-input client mixes paths: {r['segments']}")
            time.sleep(0.3)
            check(stream(ti, m) == LETTER, f"raw text-input client, wire order: {stream(ti, m)!r}")
            m = plain.mark()
            r = a.text(LETTER, window_id=wpl["id"])
            check(set(r["paths"]) == {"keymap", "temporaryKeymap"}, f"plain client mixes paths: {r['paths']}")
            time.sleep(0.3)
            check(stream(plain, m) == LETTER, f"raw plain client, wire order: {stream(plain, m)!r}")

            # Qt Widgets (native Wayland): text-input commits and Return/Tab key presses
            q = s.qtprobe("qtletter")
            lay = qt_layout(q)
            qw0 = window_by_title(b, "qtletter")
            qw = place(b, qw0, 450, 20, qw0["w"], qw0["h"])
            qx, qy = content(qw)
            a.click(qx + lay["text"]["x"] + 20, qy + lay["text"]["y"] + 10)
            a.key("ctrl+a", window_id=qw["id"])
            time.sleep(0.2)
            m = q.mark()
            r = a.text(LETTER, window_id=qw["id"])
            got = wait_until(lambda: last_of(q, "textedit", m) == LETTER and LETTER, 3) or last_of(q, "textedit", m)
            check("textInput" in r["paths"], f"Qt (Wayland) used text-input for the letters: {r['segments']}")
            check(got == LETTER, f"Qt (Wayland) text edit holds the letter in order: {got!r}")

            # GTK 3 (native Wayland): text-input commits and key presses
            g = s.spawn(["python3", GTKPROBE, "gtkletter"], "gtk", env={"GDK_BACKEND": "wayland"})
            lg = g.wait("layout", 10)
            gw = window_by_title(b, "gtkletter")
            check(bool(lg and gw), "GTK probe started")
            gx, gy = content(gw)
            a.click(gx + lg["view"]["x"] + 20, gy + lg["view"]["y"] + 10)
            time.sleep(0.3)
            m = g.mark()
            r = a.text(LETTER, window_id=gw["id"])
            got = wait_until(lambda: last_of(g, "textview", m) == LETTER and LETTER, 3) or last_of(g, "textview", m)
            check(got == LETTER, f"GTK 3 (Wayland) text view holds the letter in order via {r['paths']}: {got!r}")

            # Qt under XWayland: keymap + clipboard (the emoji)
            x = s.qtprobe("qtxletter", platform="xcb")
            layx = qt_layout(x)
            xw = window_by_title(b, "qtxletter", 15)
            xx, xy = content(xw)
            a.click(xx + layx["text"]["x"] + 20, xy + layx["text"]["y"] + 10)
            a.key("ctrl+a", window_id=xw["id"])
            time.sleep(0.3)
            m = x.mark()
            r = a.text(LETTER, window_id=xw["id"])
            got = wait_until(lambda: last_of(x, "textedit", m) == LETTER and LETTER, 5) or last_of(x, "textedit", m)
            check("clipboard" in r["paths"], f"XWayland mixed keymap and clipboard: {r['segments']}")
            check(got == LETTER, f"Qt (XWayland) text edit holds the letter in order: {got!r}")


@test
def test_x11_keys_after_clipboard_text():
    """agent.key right after agent.text used the clipboard path in an X11 window, alternating with a
    native window: no key is lost (X focus hand-over is ordered with the keys)"""
    with Session(layout="de", xwayland=True) as s:
        b = s.bridge()
        nat = s.wlprobe("--title", "native", "--size", "300x200")
        wn = place(b, window_by_title(b, "native"), 20, 20, 300, 200)
        x = s.qtprobe("qtxkeys", platform="xcb")
        layx = qt_layout(x)
        xw = window_by_title(b, "qtxkeys", 15)
        xx, xy = content(xw)
        rounds = 6
        with b.agent_session("x11keys") as a:
            a.click(xx + layx["text"]["x"] + 20, xy + layx["text"]["y"] + 10)
            a.key("ctrl+a", window_id=xw["id"])
            a.key("delete", window_id=xw["id"])
            b.call("window.activate", id=wn["id"])
            time.sleep(0.3)
            mx, mn = x.mark(), nat.mark()
            want = ""
            paths = set()
            for i in range(rounds):
                r = a.text(f"{i}ö😀", window_id=xw["id"])
                paths.update(r["paths"])
                a.key("return", window_id=xw["id"])   # the key that used to be lost
                a.key("a", window_id=wn["id"])        # focus moves to a native window and back
                want += f"{i}ö😀\n"
            got = wait_until(lambda: last_of(x, "textedit", mx) == want and want, 5) or last_of(x, "textedit", mx)
            check("clipboard" in paths, f"the emoji went through the clipboard path: {sorted(paths)}")
            presses = [(e["text"], e["mods"]) for e in x.since(mx) if e.get("ev") == "keypress" and e.get("widget") == "QTextEdit"]
            check(got == want, f"X11 text edit got every text and every Return, in order: {got!r} (key presses: {presses})")
            wait_until(lambda: typed(nat, mn) == "a" * rounds, 3)   # the probe's log may lag behind the reply
            check(typed(nat, mn) == "a" * rounds, f"the native window got every key: {typed(nat, mn)!r} "
                  f"(events: {[(e.get('ev'), e.get('sym'), e.get('state'), e.get('mods', e.get('depressed'))) for e in nat.since(mn) if e.get('ev') in ('key', 'key_enter', 'key_leave', 'modifiers')]})")
            check(refresh(b, wn)["active"], "the native window is active again at the end")


@test
def test_key_chords_on_german_layout():
    """chords go to the target with the right modifiers; keysyms are found on the German layout"""
    with Session(layout="de") as s:
        b = s.bridge()
        p = s.wlprobe("--title", "keys", "--size", "300x200")
        w = place(b, window_by_title(b, "keys"), 50, 50, 300, 200)
        time.sleep(0.3)
        with b.agent_session("keys") as a:
            m = p.mark()
            a.key("ctrl+shift+t", window_id=w["id"])
            a.key("ctrl+z", window_id=w["id"])
            a.key("return", window_id=w["id"])
            a.key("f5", window_id=w["id"])
            time.sleep(0.3)
            keys = [e for e in p.since(m) if e.get("ev") == "key" and e["state"] == 1]
            syms = [e["sym"] for e in keys]
            check(syms == ["Control_L", "Shift_L", "T", "Control_L", "z", "Return", "F5"], f"key presses {syms}")
            t = next(e for e in keys if e["sym"] == "T")
            check(t["mods"] & 0x5 == 0x5, f"'t' pressed with ctrl+shift held (mods {t['mods']})")
            z = next(e for e in keys if e["sym"] == "z")
            check(z["key"] == KEY_Y, f"'z' is the QWERTZ key (evdev {z['key']} = KEY_Y)")
            releases = [e for e in p.since(m) if e.get("ev") == "key" and e["state"] == 0]
            check(len(releases) == len(keys), "every press has a release")
            mods = [e for e in p.since(m) if e.get("ev") == "modifiers"]
            check(mods and mods[-1]["depressed"] == 0, "modifiers are released at the end")
            for bad in ("hyper+x", "ctrl+", "nosuchkey", "a+b"):
                try:
                    a.key(bad, window_id=w["id"])
                    check(False, f"{bad!r} must be rejected")
                except BridgeError as e:
                    check(e.code == "invalid", f"{bad!r} rejected: {e.message}")


@test
def test_keyboard_focus_restored():
    """typing into a background window does not activate it and gives focus back afterwards"""
    with Session() as s:
        b = s.bridge()
        bg = s.wlprobe("--title", "background", "--size", "300x200")
        fg = s.wlprobe("--title", "foreground", "--size", "300x200")
        wbg = place(b, window_by_title(b, "background"), 50, 50, 300, 200)
        wfg = place(b, window_by_title(b, "foreground"), 500, 300, 300, 200)
        b.call("window.activate", id=wfg["id"])
        time.sleep(0.3)
        order_before = [v["id"] for v in b.call("window.list")["windows"]]
        mb, mf = bg.mark(), fg.mark()
        with b.agent_session("focus") as a:
            a.text("hello", window_id=wbg["id"])
            time.sleep(0.3)
            check(typed(bg, mb) == "hello", "the background window received the text")
            check(not [e for e in bg.since(mb) if e.get("ev") == "configure" and e["activated"]], "the background window was never activated")
            check([e["ev"] for e in fg.since(mf) if e.get("ev") in ("key_leave", "key_enter")] == ["key_leave", "key_enter"],
                  "the foreground window lost keyboard focus for the call and got it back")
            check(refresh(b, wfg)["active"], "the foreground window is still the active one")
            check([v["id"] for v in b.call("window.list")["windows"]] == order_before, "stacking order unchanged")
            mb = bg.mark()
            a.text("x", window_id=wbg["id"], restore_focus=False)
            check(wait_until(lambda: refresh(b, wbg)["active"], 3), "restoreFocus=false leaves the target active")


@test
def test_escape_by_owner_cancels_session():
    """the owner pressing Escape ends the agent session (agent.state cancelled)"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        watcher = s.bridge("watcher")
        watcher.subscribe("agent")
        check(watcher.wait_event("agent.state", 3)["data"]["active"] is False, "snapshot: no session")
        token = b.call("agent.begin", label="working")["session"]
        ev = watcher.wait_event("agent.state", 3)
        check(ev["data"] == {"active": True, "label": "working"}, f"session announced: {ev['data']}")
        o.key(KEY_ESC, True)
        o.key(KEY_ESC, False)
        ev = watcher.wait_event("agent.state", 3)
        check(ev is not None and ev["data"] == {"active": False, "label": "cancelled"}, f"cancelled: {ev and ev['data']}")
        try:
            b.call("agent.pointer", session=token, type="move", x=10, y=10)
            check(False, "the old token must not work")
        except BridgeError as e:
            check(e.code == "denied", f"old token refused: {e.code}")
        token = b.call("agent.begin", label="again")["session"]
        check(bool(token), "a new session can start")
        # the agent's own Escape (agent.key) does not cancel it
        p = s.wlprobe("--title", "esc", "--size", "200x100")
        w = window_by_title(b, "esc")
        watcher.drain_events(0.3)
        b.call("agent.key", session=token, keys="escape", windowId=w["id"])
        check(p.wait(lambda e: e.get("ev") == "key" and e["sym"] == "Escape", 2) is not None, "the window got the agent's Escape")
        check(watcher.wait_event("agent.state", 0.5) is None, "agent.key escape does not end the session")


@test
def test_owner_priority():
    """injection waits while the owner holds a button (busy after 1 s); owner motion interrupts a held gesture"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        p = s.wlprobe("--title", "prio", "--size", "400x300")
        w = place(b, window_by_title(b, "prio"), 400, 200, 400, 300)
        cx, cy = content(w)
        o.move(100, 100)
        with b.agent_session("prio") as a:
            o.button(BTN_LEFT, True)
            t0 = time.monotonic()
            try:
                a.click(cx + 10, cy + 10)
                check(False, "click while the owner holds a button must not go through")
            except BridgeError as e:
                waited = time.monotonic() - t0
                check(e.code == "busy" and 0.9 < waited < 2.0, f"busy after {waited:.2f} s")
            # owner releases while the agent waits: the click then proceeds
            m = p.mark()
            b.send({"id": "late", "method": "agent.pointer", "params": {"session": a.token, "type": "click", "x": cx + 20, "y": cy + 20}})
            time.sleep(0.3)
            o.button(BTN_LEFT, False)
            reply = None
            end = time.monotonic() + 3
            while reply is None and time.monotonic() < end:
                b._read_some(0.1)
                reply = b._replies.pop('"late"', None)
            check(reply is not None and "result" in reply, f"click proceeded once the owner let go: {reply}")
            check(p.wait("button", 2, since=m) is not None, "the window got that click")
            # the owner moves while the agent holds a button: the gesture ends at the agent's spot
            m = p.mark()
            a.down(cx + 50, cy + 50)
            o.move(150, 150)
            time.sleep(0.2)
            btns = [e["state"] for e in p.since(m) if e.get("ev") == "button"]
            check(btns == [1, 0], f"target got press and release (gesture completed): {btns}")
            try:
                a.up()
                check(False, "nothing is held any more")
            except BridgeError as e:
                check(e.code == "invalid", f"'up' after interruption: {e.code}")
            # a timed drag interrupted by the owner returns busy
            b.send({"id": "drag", "method": "agent.drag", "params": {"session": a.token, "from": {"x": cx + 10, "y": cy + 10},
                                                                      "to": {"x": cx + 300, "y": cy + 200}, "durationMs": 2000}})
            time.sleep(0.4)
            o.move(160, 160)
            reply = None
            end = time.monotonic() + 3
            while reply is None and time.monotonic() < end:
                b._read_some(0.1)
                reply = b._replies.pop('"drag"', None)
            check(reply is not None and reply.get("error", {}).get("code") == "busy", f"interrupted drag: {reply}")


@test
def test_owner_typing_interrupts_text():
    """the owner typing during a long agent.text takes the keyboard back at once: busy"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        p = s.wlprobe("--title", "long", "--size", "300x200")
        other = s.wlprobe("--title", "owner-app", "--size", "300x200")
        w = place(b, window_by_title(b, "long"), 50, 50, 300, 200)
        wo = place(b, window_by_title(b, "owner-app"), 600, 400, 300, 200)
        with b.agent_session("long") as a:
            b.send({"id": "long", "method": "agent.text", "params": {"session": a.token, "text": "x" * 20000, "windowId": w["id"]}})
            time.sleep(0.5)
            o.key(30, True)  # the owner types "a" into the window they are working in
            o.key(30, False)
            reply = None
            end = time.monotonic() + 10
            while reply is None and time.monotonic() < end:
                b._read_some(0.1)
                reply = b._replies.pop('"long"', None)
            time.sleep(0.3)
            got = len(typed(p))
            check(reply is not None and reply.get("error", {}).get("code") == "busy", f"agent.text returned busy: {reply}")
            check(0 < got < 20000, f"typing stopped after {got} characters")
            check(refresh(b, wo)["active"], "the owner's window is active and keeps it")
            check(typed(other) == "a", f"the owner's key reached the owner's window, nothing else did: {typed(other)!r} "
                  f"(owner-app saw {[e.get('ev') for e in other.snapshot()][-8:]}, target typed {typed(p)[-3:]!r})")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
