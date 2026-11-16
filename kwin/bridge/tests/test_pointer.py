# SPDX-License-Identifier: GPL-3.0-or-later
# Agent pointer input: coordinates, owner pointer and hover invariance, frames, popups, context
# menus, multi-click, drags, title-bar drags, scroll, stacking, XWayland, shell surfaces.
import json
import os
import sys
import time

from common import *  # noqa: F403


def final_focus(proc, mark=0):
    """Last pointer focus state a wlprobe saw: (inside, surface, x, y)."""
    inside, surface, x, y = False, None, None, None
    for e in proc.since(mark):
        ev = e.get("ev")
        if ev == "enter":
            inside, surface, x, y = True, e["surface"], e["x"], e["y"]
        elif ev == "leave":
            inside, surface = False, None
        elif ev == "motion" and inside:
            x, y = e["x"], e["y"]
    return inside, surface, x, y


def qt_hover(proc, mark=0):
    state = None
    for e in proc.since(mark):
        if e.get("ev") == "hover":
            state = e["in"]
    return state


# --------------------------------------------------------------------------------------- tests

@test
def test_click_coordinates_scale_1_and_1_6():
    """a click arrives at the intended surface-local coordinates (wlprobe and Qt, scale 1.0 and 1.6)"""
    for scale in (1.0, 1.6):
        with Session(scale=scale) as s:
            b = s.bridge()
            b.subscribe("outputs")
            out = b.wait_event("outputs.changed", 3)["data"]["outputs"][0]
            check(abs(out["scale"] - scale) < 1e-6, f"[{scale}] output scale {out['scale']}, logical {out['w']}x{out['h']}")
            o = s.owner()
            o.move(5, 5)
            p = s.wlprobe("--title", "probe", "--size", "300x200")
            w = place(b, window_by_title(b, "probe"), 10.0, 10.0, 300, 200)
            cx, cy = content(w)
            q = s.qtprobe("qtwin")
            lay = qt_layout(q)
            qw = place(b, window_by_title(b, "qtwin"), 330.0, 0.0, 450, 480)
            lay = q.wait("layout", 3, since=q.mark()) or lay
            qx, qy = content(qw)
            check(lay is not None, f"[{scale}] Qt probe reported its layout ({lay and lay['platform']}, dpr {lay and lay['dpr']})")
            with b.agent_session("coords") as a:
                for lx, ly in ((123.5, 77.25), (10.0, 190.0), (299.0, 0.5), (0.25, 0.625)):
                    m = p.mark()
                    r = a.click(cx + lx, cy + ly)
                    check(r["target"]["windowId"] == w["id"], f"[{scale}] target is the probe window")
                    btn = p.wait(lambda e: e.get("ev") == "button" and e["state"] == 1, 3, since=m)
                    check(btn is not None and near(btn["x"], lx) and near(btn["y"], ly),
                          f"[{scale}] wlprobe press at local ({lx}, {ly}): got ({btn and btn['x']}, {btn and btn['y']})")
                pad = lay["pad"]
                for lx, ly in ((50.5, 40.25), (200.0, 100.0)):
                    m = q.mark()
                    a.click(qx + pad["x"] + lx, qy + pad["y"] + ly)
                    ev = q.wait("press", 3, since=m)
                    check(ev is not None and near(ev["x"], lx, 0.02) and near(ev["y"], ly, 0.02),
                          f"[{scale}] Qt pad press at ({lx}, {ly}): got ({ev and ev['x']}, {ev and ev['y']})")
            dpr = q.snapshot()
            cur = b.call("cursor.get")
            check(near(cur["x"], 5) and near(cur["y"], 5), f"[{scale}] owner pointer still at (5, 5): {cur}")


@test
def test_owner_pointer_and_hover_restored():
    """the owner's pointer never moves and the client under it ends in the hover state it started in"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        under = s.wlprobe("--title", "under", "--size", "300x200")
        target = s.wlprobe("--title", "target", "--size", "300x200")
        wu = place(b, window_by_title(b, "under"), 50, 50, 300, 200)
        wt = place(b, window_by_title(b, "target"), 600, 300, 300, 200)
        q = s.qtprobe("qthover")
        lay = qt_layout(q)
        wq = place(b, window_by_title(b, "qthover"), 380, 420, window_by_title(b, "qthover")["w"], window_by_title(b, "qthover")["h"])
        ux, uy = content(wu)
        o.move(ux + 120.25, uy + 80.5)
        time.sleep(0.2)
        inside, surf, x, y = final_focus(under)
        check(inside and near(x, 120.25) and near(y, 80.5), f"owner hovers 'under' at (120.25, 80.5) before: {inside} {x} {y}")
        mark_u = under.mark()
        tx, ty = content(wt)
        calls = 0
        with b.agent_session("hover") as a:
            for kind in ("click", "move", "scroll", "down_up", "drag", "rightclick"):
                before = b.call("cursor.get")
                if kind == "click":
                    a.click(tx + 30, ty + 40)
                elif kind == "move":
                    a.move(tx + 60, ty + 60)
                elif kind == "scroll":
                    a.scroll(tx + 60, ty + 60, dy=1)
                elif kind == "down_up":
                    a.down(tx + 20, ty + 20)
                    a.move(tx + 80, ty + 90)
                    a.up()
                elif kind == "drag":
                    a.drag((tx + 10, ty + 10), (tx + 200, ty + 150), duration_ms=200)
                elif kind == "rightclick":
                    a.click(tx + 50, ty + 50, button="right")
                calls += 1
                after = b.call("cursor.get")
                check(before == after, f"{kind}: owner pointer unchanged {after}")
                inside, surf, x, y = final_focus(under)
                check(inside and near(x, 120.25) and near(y, 80.5), f"{kind}: 'under' is hovered again at the owner's position ({x}, {y})")
                tin, _, _, _ = final_focus(target)
                check(not tin, f"{kind}: the agent's target does not keep pointer focus")
        # hover state for a Qt client under the owner's pointer
        qx, qy = content(wq)
        pad = lay["pad"]
        o.move(qx + pad["x"] + 30, qy + pad["y"] + 30)
        time.sleep(0.3)
        check(qt_hover(q) is True, "owner hovers the Qt pad")
        mark_q = q.mark()
        with b.agent_session("hover-qt") as a:
            a.click(tx + 30, ty + 40)
            a.drag((tx + 10, ty + 10), (tx + 100, ty + 100), duration_ms=100)
        time.sleep(0.3)
        check(qt_hover(q) is True, f"Qt pad still hovered after agent input (events: {[e for e in q.since(mark_q) if e.get('ev') == 'hover']})")
        # KWin's own view and the seat agree again: real motion reaches the hovered client normally
        m = under.mark()
        o.move(ux + 125, uy + 85)
        ev = under.wait(lambda e: e.get("ev") in ("motion", "enter"), 3, since=m)
        check(ev is not None and near(ev["x"], 125) and near(ev["y"], 85), f"owner motion after agent input reaches 'under' at (125, 85): {ev}")
        dbg = b.call("debug.trace", enable=False)
        check(dbg["cursorMovesDuringAgent"] == 0, f"the cursor never moved during {calls + 2} agent calls")


@test
def test_no_frame_with_displaced_cursor():
    """every frame presented during agent input shows the owner's cursor where the owner left it"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        anim = s.wlprobe("--title", "anim", "--size", "400x300", "--animate")
        tgt = s.wlprobe("--title", "tgt", "--size", "400x300")
        wa = place(b, window_by_title(b, "anim"), 20, 20, 400, 300)
        wt = place(b, window_by_title(b, "tgt"), 700, 300, 400, 300)
        ax, ay = content(wa)
        o.move(ax + 200, ay + 150)
        owner = b.call("cursor.get")
        b.call("debug.trace", enable=True)
        tx, ty = content(wt)
        with b.agent_session("frames") as a:
            for i in range(20):
                a.click(tx + 10 + i * 15, ty + 50)
            a.drag((tx + 20, ty + 20), (tx + 350, ty + 250), duration_ms=500)
            a.move(tx + 100, ty + 100, hoverMs=300)
            a.down(tx + 50, ty + 50)
            for i in range(10):
                a.move(tx + 50 + i * 20, ty + 60)
                time.sleep(0.02)
            a.up()
        time.sleep(0.2)
        t = b.call("debug.trace", enable=False)
        frames = t["frames"]
        agent_frames = [f for f in frames if f["agent"]]
        check(len(frames) > 30, f"KWin presented {len(frames)} frames while traced ({len(agent_frames)} during agent input)")
        check(len(agent_frames) > 5, "frames were presented while agent gestures were in progress")
        bad = [f for f in frames if not (near(f["cursorX"], owner["x"]) and near(f["cursorY"], owner["y"]))]
        check(not bad, f"no frame had the cursor away from the owner's position {owner} (bad: {bad[:3]})")
        items = {(round(f["itemX"], 3), round(f["itemY"], 3)) for f in frames}
        check(len(items) == 1, f"the rendered cursor item stayed at one position: {items}")
        check(t["cursorMovesDuringAgent"] == 0, "Cursor::posChanged never fired during agent input")


@test
def test_popup_menu_two_calls():
    """open a menu with one call, pick an item with a second (wlprobe, Qt native, Qt XWayland)"""
    with Session(xwayland=True) as s:
        b = s.bridge()
        o = s.owner()
        o.move(1270, 790)
        p = s.wlprobe("--title", "menus", "--popup", "--size", "400x300")
        w = place(b, window_by_title(b, "menus"), 100, 100, 400, 300)
        cx, cy = content(w)
        with b.agent_session("popup") as a:
            m = p.mark()
            a.click(cx + 50, cy + 45)
            check(p.wait("popup_open", 3, since=m) is not None, "wlprobe opened its grabbing popup on the agent's press")
            popup = find_window(b, lambda v: v["type"] == "popup" and v["pid"] == w["pid"], 5)
            check(popup is not None and popup["normal"] is False, f"the popup is reported as a non-normal window: {popup and popup['type']}")
            a.click(popup["x"] + 75, popup["y"] + 45)
            item = p.wait("item", 3, since=m)
            check(item is not None and item["index"] == 1, f"second call activated item 1: {item}")
        for platform in ("wayland", "xcb"):
            q = s.qtprobe(f"qtmenu-{platform}", platform=platform)
            lay = qt_layout(q)
            qw = window_by_title(b, f"qtmenu-{platform}")
            qx, qy = content(qw)
            mb = lay["menubar"]
            with b.agent_session("qtmenu") as a:
                m = q.mark()
                a.click(qx + mb["x"] + 18, qy + mb["y"] + mb["h"] / 2)
                check(q.wait("menu_shown", 3, since=m) is not None, f"[{platform}] File menu opened")
                popup = find_window(b, lambda v: v["pid"] == qw["pid"] and v["id"] != qw["id"] and v["type"] in ("popup", "menu"), 5)
                check(popup is not None, f"[{platform}] menu popup listed ({popup and popup['type']}, {popup and popup['h']} px high)")
                a.click(popup["x"] + popup["w"] / 2, popup["y"] + popup["h"] / 2)
                act = q.wait("action", 3, since=m)
                check(act is not None and act["name"] == "Open", f"[{platform}] middle item 'Open' triggered: {act}")


@test
def test_popup_dismissed_by_click_elsewhere():
    """a click outside an open grabbing popup closes it and is not delivered (KWin semantics)"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "menus", "--popup", "--size", "300x300")
        other = s.wlprobe("--title", "other", "--size", "300x300")
        w = place(b, window_by_title(b, "menus"), 50, 50, 300, 300)
        wo = place(b, window_by_title(b, "other"), 700, 300, 300, 300)
        cx, cy = content(w)
        ox, oy = content(wo)
        with b.agent_session("dismiss") as a:
            a.click(cx + 50, cy + 45)
            check(p.wait("popup_open", 3) is not None, "popup open")
            check(find_window(b, lambda v: v["type"] == "popup", 3) is not None, f"popup mapped (client log: {[e.get('ev') for e in p.snapshot()][-12:]})")
            m = other.mark()
            r = a.click(ox + 100, oy + 100)
            check(r.get("dismissedPopups") is True, "the reply says the click dismissed the popup")
            check(p.wait("popup_done", 3) is not None, "the client received popup_done")
            time.sleep(0.2)
            check(not [e for e in other.since(m) if e.get("ev") == "button"], "the dismissing press was not delivered to the other window")
            r = a.click(ox + 100, oy + 100)
            check(other.wait("button", 3, since=m) is not None, "the next click reaches the other window")


@test
def test_context_menu():
    """right-click opens a context menu; a second call picks an item (Qt native and XWayland)"""
    with Session(xwayland=True) as s:
        b = s.bridge()
        for platform in ("wayland", "xcb"):
            q = s.qtprobe(f"ctx-{platform}", platform=platform)
            lay = qt_layout(q)
            qw = window_by_title(b, f"ctx-{platform}")
            qx, qy = content(qw)
            pad = lay["pad"]
            with b.agent_session("ctx") as a:
                m = q.mark()
                a.click(qx + pad["x"] + 40, qy + pad["y"] + 40, button="right")
                check(q.wait("context_shown", 3, since=m) is not None, f"[{platform}] context menu shown")
                popup = find_window(b, lambda v: v["pid"] == qw["pid"] and v["id"] != qw["id"] and v["type"] in ("popup", "menu"), 5)
                check(popup is not None, f"[{platform}] context menu listed")
                a.click(popup["x"] + popup["w"] / 2, popup["y"] + popup["h"] / 2)
                act = q.wait("context_action", 3, since=m)
                check(act is not None and act["name"] == "Beta", f"[{platform}] 'Beta' chosen: {act}")


@test
def test_multi_click():
    """count=2 is a double-click for Qt; count=3 gives three press/release pairs with rising times"""
    with Session() as s:
        b = s.bridge()
        q = s.qtprobe("dbl")
        lay = qt_layout(q)
        qw = window_by_title(b, "dbl")
        qx, qy = content(qw)
        p = s.wlprobe("--title", "triple", "--size", "300x200")
        w = place(b, window_by_title(b, "triple"), 960, 560, 300, 200)
        with b.agent_session("multi") as a:
            m = q.mark()
            a.click(qx + lay["pad"]["x"] + 60, qy + lay["pad"]["y"] + 60, count=2)
            check(q.wait("dblclick", 3, since=m) is not None, "Qt recognised a double-click")
            m = p.mark()
            cx, cy = content(w)
            a.click(cx + 10, cy + 10, count=3)
            time.sleep(0.3)
            btns = [e for e in p.since(m) if e.get("ev") == "button"]
            check([e["state"] for e in btns] == [1, 0, 1, 0, 1, 0], f"three press/release pairs: {[e['state'] for e in btns]}")
            times = [e["time"] for e in btns]
            check(all(t2 >= t1 for t1, t2 in zip(times, times[1:])), f"event times never go backwards: {times}")


@test
def test_drags_inside_windows():
    """press-move-release: Qt slider, Qt text selection, and down/move/up as separate calls"""
    with Session() as s:
        b = s.bridge()
        q = s.qtprobe("drags")
        lay = qt_layout(q)
        qw = window_by_title(b, "drags")
        qx, qy = content(qw)
        sl = lay["slider"]
        te = lay["text"]
        with b.agent_session("drag") as a:
            m = q.mark()
            a.drag((qx + sl["x"] + 6, qy + sl["y"] + sl["h"] / 2), (qx + sl["x"] + sl["w"] + 40, qy + sl["y"] + sl["h"] / 2), duration_ms=300)
            time.sleep(0.2)
            vals = [e["value"] for e in q.since(m) if e.get("ev") == "slider"]
            check(vals and vals[-1] == 100, f"slider dragged to its maximum: {vals[-5:]}")
            m = q.mark()
            a.drag((qx + te["x"] + 6, qy + te["y"] + 14), (qx + te["x"] + 120, qy + te["y"] + 14), duration_ms=250)
            time.sleep(0.2)
            sels = [e["text"] for e in q.since(m) if e.get("ev") == "selection"]
            check(sels and len(sels[-1]) >= 5, f"text selected by dragging: {sels[-1:]!r}")
            # separate calls: the slider follows each move while the button is held
            m = q.mark()
            y = qy + sl["y"] + sl["h"] / 2
            handle = qx + sl["x"] + sl["w"] - 6
            a.down(handle, y)
            a.move(qx + sl["x"] + sl["w"] / 2, y)
            mid = wait_until(lambda: [e["value"] for e in q.since(m) if e.get("ev") == "slider"], 2)
            a.move(qx + sl["x"] - 50, y)
            a.up()
            time.sleep(0.2)
            vals = [e["value"] for e in q.since(m) if e.get("ev") == "slider"]
            check(mid and 30 < mid[-1] < 70 and vals and vals[-1] == 0, f"down/move/up calls moved the slider ~50 then 0: mid {mid[-1:]} end {vals[-1:]}")
        p = s.wlprobe("--title", "grab", "--size", "300x200")
        w = place(b, window_by_title(b, "grab"), 100, 100, 300, 200)
        cx, cy = content(w)
        with b.agent_session("grab") as a:
            m = p.mark()
            a.down(cx + 50, cy + 50)
            a.move(cx + 500, cy + 400)  # outside the surface: the implicit grab keeps it
            a.up()
            wait_until(lambda: len([e for e in p.since(m) if e.get("ev") == "button"]) >= 2, 2)
            ev = [e for e in p.since(m) if e.get("ev") in ("motion", "button")]
            outside = [e for e in ev if e["ev"] == "motion" and near(e["x"], 500) and near(e["y"], 400)]
            check(outside, "motion outside the surface is delivered during the implicit grab (local 500, 400)")
            check([e["state"] for e in ev if e["ev"] == "button"] == [1, 0], "press and release both reached the pressed surface")


@test
def test_title_bar_drags():
    """server-side title-bar drag, client-side (xdg_toplevel.move) drag and title double-click"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()
        o.move(1270, 10)
        q = s.qtprobe("ssd")
        qt_layout(q)
        qw = place(b, window_by_title(b, "ssd"), 100, 100, window_by_title(b, "ssd")["w"], window_by_title(b, "ssd")["h"])
        title_h = qw["content"]["y"] - qw["y"]
        note(f"Qt window decoration: title bar {title_h} px")
        with b.agent_session("title") as a:
            if title_h > 4:
                start = (qw["x"] + qw["w"] / 2 - 40, qw["y"] + title_h / 2)
                r = a.drag(start, (start[0] + 200, start[1] + 120), duration_ms=300)
                check(r["target"].get("decoration") is True, "drag started on the server-side decoration")
                moved = wait_until(lambda: (lambda v: near(v["x"], 300, 1.5) and near(v["y"], 220, 1.5) and v)(refresh(b, qw)), 3)
                check(moved, f"SSD window moved by (200, 120): now at ({refresh(b, qw)['x']}, {refresh(b, qw)['y']})")
                v = refresh(b, qw)
                a.click(v["x"] + v["w"] / 2 - 40, v["y"] + title_h / 2, count=2)
                check(wait_until(lambda: refresh(b, qw)["maximized"], 3), "double-click on the title bar maximised the window")
            else:
                note("no server-side decoration in this environment; SSD drag not exercised")
        p = s.wlprobe("--title", "csd", "--csd-move", "--size", "400x300")
        w = place(b, window_by_title(b, "csd"), 300, 300, 400, 300)
        cx, cy = content(w)
        with b.agent_session("csd") as a:
            m = p.mark()
            a.drag((cx + 200, cy + 15), (cx + 350, cy + 95), duration_ms=300)
            check(p.wait("move_request", 3, since=m) is not None, "the client asked for an interactive move")
            moved = wait_until(lambda: (lambda v: near(v["x"], 450, 1.5) and near(v["y"], 380, 1.5) and v)(refresh(b, w)), 3)
            check(moved, f"CSD window moved by (150, 80): now at ({refresh(b, w)['x']}, {refresh(b, w)['y']})")
        before = refresh(b, w)
        o.move(600, 600)
        o.move(700, 650)
        time.sleep(0.2)
        after = refresh(b, w)
        check(before["x"] == after["x"] and before["y"] == after["y"], "the owner's pointer does not drag the window afterwards")
        cur = b.call("cursor.get")
        check(near(cur["x"], 700) and near(cur["y"], 650), "owner pointer where the owner put it")


@test
def test_scroll():
    """scroll notches arrive as axis 15/notch with value120 120/notch; Qt sees wheel angle deltas"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "scroll", "--size", "300x200")
        w = place(b, window_by_title(b, "scroll"), 100, 100, 300, 200)
        cx, cy = content(w)
        q = s.qtprobe("qtscroll")
        lay = qt_layout(q)
        qw = window_by_title(b, "qtscroll")
        qx, qy = content(qw)
        with b.agent_session("scroll") as a:
            m = p.mark()
            a.scroll(cx + 100, cy + 100, dy=2)
            a.scroll(cx + 100, cy + 100, dx=-1)
            time.sleep(0.2)
            axes = [(e["axis"], e["value"]) for e in p.since(m) if e.get("ev") == "axis"]
            v120 = [(e["axis"], e["value"]) for e in p.since(m) if e.get("ev") == "axis_value120"]
            check(axes == [(0, 30.0), (1, -15.0)], f"axis values {axes}")
            check(v120 == [(0, 240), (1, -120)], f"value120 {v120}")
            m = q.mark()
            a.scroll(qx + lay["pad"]["x"] + 50, qy + lay["pad"]["y"] + 50, dy=1)
            wh = q.wait("wheel", 3, since=m)
            check(wh is not None and wh["dy"] == -120, f"Qt wheel angleDelta.y = -120 (scroll down): {wh}")


@test
def test_window_not_on_top():
    """a click on the visible part of a lower window raises it; windowId raises a covered target"""
    with Session() as s:
        b = s.bridge()
        pa = s.wlprobe("--title", "A", "--size", "400x300")
        wa = place(b, window_by_title(b, "A"), 100, 100, 400, 300)
        pb = s.wlprobe("--title", "B", "--size", "400x300")
        wb = place(b, window_by_title(b, "B"), 300, 200, 400, 300)
        b.call("window.activate", id=wb["id"])
        time.sleep(0.2)
        order = b.call("window.list")["windows"]
        with b.agent_session("stack") as a:
            m = pa.mark()
            r = a.click(150, 150)  # only A is there
            check(r["target"]["windowId"] == wa["id"], "the visible part of A is A")
            check(pa.wait("button", 3, since=m) is not None, "A received the click")
            check(wait_until(lambda: refresh(b, wa)["active"], 3), "A was activated (click to focus)")
            top = [v["id"] for v in b.call("window.list")["windows"] if v["normal"]]
            check(top[-1] == wa["id"], "A was raised to the top")
            # (350, 250) is covered by A now; aimed at B it raises B first
            mb = pb.mark()
            r = a.click(350, 250, windowId=wb["id"])
            check(r["target"]["windowId"] == wb["id"], "windowId targeted B under A")
            ev = pb.wait("button", 3, since=mb)
            check(ev is not None and near(ev["x"], 50) and near(ev["y"], 50), f"B got the click at local (50, 50): {ev}")
            try:
                a.click(5, 5, windowId=wb["id"])
                check(False, "a point outside the window must be refused")
            except BridgeError as e:
                check(e.code == "not_found", f"point outside the target window: {e.code}")


@test
def test_xwayland_clicks_and_hover():
    """XWayland client: click coordinates and hover restoration"""
    with Session(xwayland=True) as s:
        b = s.bridge()
        o = s.owner()
        check(s.display is not None, f"XWayland display {s.display}")
        q = s.qtprobe("x11probe", platform="xcb")
        lay = qt_layout(q)
        check(lay and lay["platform"] == "xcb", "Qt probe runs on xcb (XWayland)")
        qw = window_by_title(b, "x11probe")
        check(qw["xwayland"] is True, "the window is reported as XWayland")
        qw = place(b, qw, 100, 100, qw["w"], qw["h"])
        qx, qy = content(qw)
        pad = lay["pad"]
        o.move(qx + pad["x"] + 20, qy + pad["y"] + 20)
        time.sleep(0.3)
        check(qt_hover(q) is True, "owner hovers the X11 pad")
        p = s.wlprobe("--title", "native", "--size", "300x200")
        wn = place(b, window_by_title(b, "native"), 900, 500, 300, 200)
        with b.agent_session("x11") as a:
            m = q.mark()
            a.click(qx + pad["x"] + 77, qy + pad["y"] + 33)
            ev = q.wait("press", 3, since=m)
            check(ev is not None and near(ev["x"], 77, 0.6) and near(ev["y"], 33, 0.6), f"X11 press at (77, 33): {ev}")
            # the owner stays over the X11 pad; the agent clicks a native window
            cx, cy = content(wn)
            a.click(cx + 10, cy + 10)
            a.drag((cx + 20, cy + 20), (cx + 100, cy + 100), duration_ms=100)
        time.sleep(0.4)
        check(qt_hover(q) is True, "X11 pad hovered again after agent input elsewhere")
        m = q.mark()
        o.move(qx + pad["x"] + 25, qy + pad["y"] + 26)
        ev = q.wait("move", 3, since=m)
        check(ev is not None and near(ev["x"], 25, 0.6) and near(ev["y"], 26, 0.6), f"owner motion reaches the X11 client normally: {ev}")


@test
def test_clicks_on_shell_surfaces():
    """our Dock receives agent clicks; the assistant's own overlay is transparent to them"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "under-glow", "--size", "300x200")
        w = place(b, window_by_title(b, "under-glow"), 50, 50, 300, 200)
        sh = start_shell(s)
        dock = find_window(b, lambda v: v.get("namespace") == "kristall-dock", 15)
        glow = find_window(b, lambda v: v.get("namespace") == "kristall-assistant-glow", 5)
        check(dock is not None and glow is not None, "shell surfaces are listed with their namespaces")
        check(dock["normal"] is False and glow["normal"] is False and dock["type"] == "layer", "shell surfaces are not normal windows")
        with b.agent_session("shell") as a:
            m = sh.mark()
            r = a.click(dock["x"] + 100, dock["y"] + 30)
            check(r["target"].get("namespace") == "kristall-dock", "the Dock is the target")
            ev = sh.wait(lambda e: "DOCK_PRESS" in e.get("raw", ""), 3, since=m)
            check(ev is not None and "100 30" in ev["raw"], f"the Dock received the press at (100, 30): {ev}")
            cx, cy = content(w)
            m = p.mark()
            r = a.click(cx + 40, cy + 40)  # inside the glow overlay's area
            check(r["target"]["windowId"] == w["id"], "the click went through the assistant overlay to the window")
            check(p.wait("button", 3, since=m) is not None, "the window under the overlay got the press")
            check(sh.wait(lambda e: "GLOW_PRESS" in e.get("raw", ""), 0.5, since=m) is None, "the overlay itself got nothing")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
