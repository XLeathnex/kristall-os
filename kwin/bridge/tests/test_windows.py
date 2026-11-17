# SPDX-License-Identifier: GPL-3.0-or-later
# Window model: events for open/move/minimise/activate/close, coalescing, stacking, outputs,
# desktops, application menus (Qt and GTK), minimise targets (icon geometry), window methods.
import os
import subprocess
import sys
import time

from common import *  # noqa: F403

GTKPROBE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "clients", "gtkprobe.py")


def events(watcher, name=None, since_all=None):
    evs = watcher.drain_events(0.3)
    return [e for e in evs if name is None or e["event"] == name]


@test
def test_window_events():
    """window.added / changed / removed, active.changed, stacking.changed with snapshots first"""
    with Session() as s:
        b = s.bridge()
        w0 = s.wlprobe("--title", "first", "--size", "300x200")
        first = window_by_title(b, "first")
        watcher = s.bridge("watcher")
        watcher.subscribe("windows", "active", "stacking", "outputs", "desktops")
        snap = [watcher.wait_event(n, 3) for n in ("windows.snapshot", "active.changed", "stacking.changed", "outputs.changed", "desktops.changed")]
        check(all(snap), "a snapshot event for every subscribed topic")
        check(any(w["id"] == first["id"] for w in snap[0]["data"]["windows"]), "windows.snapshot lists the open window")
        check(snap[1]["data"]["id"] == first["id"], "active.changed snapshot names the active window")
        out = snap[3]["data"]["outputs"][0]
        check(out["name"] == "Virtual-0" and out["w"] == 1280 and out["h"] == 800 and out["scale"] == 1 and out["primary"] is True,
              f"outputs snapshot: {out}")
        check(snap[4]["data"]["current"] == 1 and snap[4]["data"]["count"] >= 1, f"desktops snapshot: {snap[4]['data']}")
        watcher.drain_events(0.3)

        p = s.wlprobe("--title", "second", "--size", "320x240", "--app-id", "org.example.second")
        added = watcher.wait_event(lambda e: e["event"] == "window.added" and e["data"]["window"]["title"] == "second", 5)
        check(added is not None, "window.added for a new window")
        w = added["data"]["window"]
        check(w["appId"] == "org.example.second" and w["normal"] and w["w"] == 320 and w["pid"] > 0, f"window object: appId {w['appId']}, {w['w']}x{w['h']}")
        check(watcher.wait_event(lambda e: e["event"] == "active.changed" and e["data"]["id"] == w["id"], 3), "active.changed to the new window")
        st = watcher.wait_event("stacking.changed", 3)
        check(st and st["data"]["order"][-1] == w["id"], "stacking.changed puts it on top")
        watcher.drain_events(0.2)

        b.call("window.setGeometry", id=w["id"], x=200, y=150, w=320, h=240)
        ch = watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["id"] == w["id"] and "x" in e["data"]["changes"], 3)
        check(ch and ch["data"]["changes"]["x"] == 200 and ch["data"]["changes"]["y"] == 150 and "title" not in ch["data"]["changes"],
              f"window.changed carries only changed fields: {ch and ch['data']['changes']}")
        b.call("window.setMinimized", id=w["id"], value=True)
        ch = watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["changes"].get("minimized") is True, 3)
        check(ch is not None, "minimise reported")
        b.call("window.activate", id=w["id"])
        ch = watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["changes"].get("minimized") is False, 3)
        check(ch is not None and watcher.wait_event(lambda e: e["event"] == "active.changed" and e["data"]["id"] == w["id"], 3),
              "window.activate un-minimises and activates")
        b.call("window.setMaximized", id=w["id"], value=True)
        check(watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["changes"].get("maximized") is True, 3), "maximise reported")
        b.call("window.setFullscreen", id=w["id"], value=True)
        check(watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["changes"].get("fullscreen") is True, 3), "fullscreen reported")
        b.call("window.setFullscreen", id=w["id"], value=False)
        b.call("window.close", id=w["id"])
        check(watcher.wait_event(lambda e: e["event"] == "window.removed" and e["data"]["id"] == w["id"], 5), "window.removed after close")
        try:
            b.call("window.activate", id=w["id"])
            check(False, "a closed window's id must not resolve")
        except BridgeError as e:
            check(e.code == "not_found", "methods on a closed window: not_found")
        # a window that disappears on its own (client killed)
        s.stop_proc(w0)
        check(watcher.wait_event(lambda e: e["event"] == "window.removed" and e["data"]["id"] == first["id"], 5), "window.removed when the client dies")


@test
def test_geometry_coalescing():
    """geometry changes are coalesced: at most one window.changed per frame"""
    with Session() as s:
        b = s.bridge()
        p = s.wlprobe("--title", "mover", "--size", "200x150")
        w = window_by_title(b, "mover")
        watcher = s.bridge("watcher")
        watcher.subscribe("windows")
        watcher.drain_events(0.3)
        n = 300
        t0 = time.monotonic()
        for i in range(n):  # pipelined: 300 moves arrive in a burst
            b.send({"id": f"g{i}", "method": "window.setGeometry", "params": {"id": w["id"], "x": 10 + i, "y": 20 + i // 2, "w": 200, "h": 150}})
        while len(b._replies) < n and time.monotonic() - t0 < 10:
            b._read_some(0.2)
        b._replies.clear()
        span = time.monotonic() - t0
        time.sleep(0.3)
        moves = [e for e in watcher.drain_events(0.3) if e["event"] == "window.changed" and "x" in e["data"]["changes"]]
        frames = span * 60 + 2
        check(0 < len(moves) <= frames, f"{n} moves in {span * 1000:.0f} ms produced {len(moves)} events (<= {frames:.0f} frames)")
        check(moves[-1]["data"]["changes"]["x"] == 10 + n - 1, "the last event carries the final position")
        # an owner dragging the window by its title (interactive move with the real pointer)
        q = s.qtprobe("dragme")
        qt_layout(q)
        qw = place(b, window_by_title(b, "dragme"), 100, 100, window_by_title(b, "dragme")["w"], window_by_title(b, "dragme")["h"])
        title = qw["content"]["y"] - qw["y"]
        if title > 4:
            o = s.owner()
            o.move(qw["x"] + qw["w"] / 2 - 50, qw["y"] + title / 2)
            watcher.drain_events(0.2)
            o.button(BTN_LEFT, True)
            t0 = time.monotonic()
            for i in range(60):
                o.move(qw["x"] + qw["w"] / 2 - 50 + i * 4, qw["y"] + title / 2 + i * 2)
            o.button(BTN_LEFT, False)
            span = time.monotonic() - t0
            time.sleep(0.3)
            moves = [e for e in watcher.drain_events(0.3) if e["event"] == "window.changed" and e["data"]["id"] == qw["id"] and "x" in e["data"]["changes"]]
            check(0 < len(moves) <= span * 60 + 2, f"interactive move: {len(moves)} events over {span * 1000:.0f} ms")


def bus_owner(s, name):
    """the owning process's command name, or None when nobody owns `name`"""
    r = subprocess.run(["busctl", "--user", "status", name], env=s.env(), capture_output=True, text=True)
    if r.returncode != 0:
        return None
    return next((l[5:] for l in r.stdout.splitlines() if l.startswith("Comm=")), "?")


def dbusmenu(service, path):
    """(revision, layout) of a DBusMenu, layout as nested (id, props, children) with plain values"""
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    v = bus.call_sync(service, path, "com.canonical.dbusmenu", "GetLayout", GLib.Variant("(iias)", (0, -1, [])),
                      GLib.VariantType("(u(ia{sv}av))"), Gio.DBusCallFlags.NONE, 3000, None)
    return v.unpack()


def dbusmenu_items(layout, out=None):
    """{label without mnemonic: (id, props)} for every item"""
    out = {} if out is None else out
    item_id, props, children = layout
    if "label" in props:
        out[props["label"].replace("_", "")] = (item_id, props)
    for c in children:
        dbusmenu_items(c, out)
    return out


def dbusmenu_click(service, path, item_id):
    from gi.repository import Gio, GLib
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    bus.call_sync(service, path, "com.canonical.dbusmenu", "Event", GLib.Variant("(isvu)", (item_id, "clicked", GLib.Variant("i", 0), 0)),
                  None, Gio.DBusCallFlags.NONE, 3000, None)


@test
def test_application_menus():
    """menu service/path for Qt (Wayland and XWayland) and GTK 3 (XWayland) while the shell shows menus"""
    with Session(xwayland=True) as s:
        b = s.bridge()
        kded = s.spawn(["kded6"], "kded", merge_stderr=True)
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        gm = s.spawn(["gmenudbusmenuproxy"], "gmenu", env={"QT_QPA_PLATFORM": "xcb"}, merge_stderr=True)
        reg = wait_until(lambda: bus_owner(s, "com.canonical.AppMenu.Registrar"), 10)
        check(reg, "kded's appmenu module published the registrar (the bridge owns org.kde.kappmenuview)")
        qn = s.qtprobe("qt-menu", env={"QT_QPA_PLATFORMTHEME": "kde"})
        qx = s.qtprobe("qtx-menu", platform="xcb", env={"QT_QPA_PLATFORMTHEME": "kde"})
        g = s.spawn(["python3", GTKPROBE, "gtk-menu"], "gtk", env={"GDK_BACKEND": "x11", "GTK_MODULES": "unity-gtk-module"})
        for title, label in (("qt-menu", "Qt Wayland"), ("qtx-menu", "Qt XWayland"), ("gtk-menu", "GTK 3 XWayland")):
            w = find_window(b, lambda v: v["title"] == title and v["menu"], 10)
            check(w is not None, f"{label}: menu {w and w['menu']}")
            layout = subprocess.run(["busctl", "--user", "call", "--", w["menu"]["service"], w["menu"]["path"], "com.canonical.dbusmenu", "GetLayout",
                                     "iias", "0", "-1", "0"], env=s.env(), capture_output=True, text=True)
            check("ile" in layout.stdout and "File" in layout.stdout.replace("_", ""), f"{label}: the DBusMenu at that service/path has the File menu")
        # the shell goes away: only its "menu bar is showing app menus" name goes; the registrar stays
        # (apps decide once, at their first menu bar, whether to export)
        check(bus_owner(s, "org.kristall.AppMenuView") is not None, "org.kristall.AppMenuView owned while the shell is subscribed")
        shell.close()
        gone = wait_until(lambda: bus_owner(s, "org.kristall.AppMenuView") is None, 10)
        check(gone, "without a menu-displaying client org.kristall.AppMenuView is released (apps show their own menu bars)")
        check(bus_owner(s, "com.canonical.AppMenu.Registrar") is not None, "…and the registrar stays, so apps started now still export their menus")


@test
def test_menu_view_names():
    """org.kde.kappmenuview for KWin's whole life, also after a reconfigure; org.kristall.AppMenuView only while menus are shown"""
    with Session() as s:
        b = s.bridge()
        check(wait_until(lambda: bus_owner(s, "org.kde.kappmenuview"), 5), "org.kde.kappmenuview owned without any menu-displaying client")
        check(bus_owner(s, "org.kristall.AppMenuView") is None, "org.kristall.AppMenuView not owned without a `menus` subscriber")
        shell = s.bridge("shell")
        shell.subscribe("menus")
        check(wait_until(lambda: bus_owner(s, "org.kristall.AppMenuView"), 5), "org.kristall.AppMenuView owned while a client is subscribed to `menus`")
        # KWin's decoration settings release org.kde.kappmenuview on KWin's own D-Bus connection at
        # every reconfigure (no title-bar menu button): the bridge's claim must not depend on it
        for _ in range(2):
            r = subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure"], env=s.env(),
                               capture_output=True, text=True)
            check(r.returncode == 0, f"KWin reconfigure {r.stderr.strip()}")
            time.sleep(1.0)
            check(bus_owner(s, "org.kde.kappmenuview") is not None, "org.kde.kappmenuview still owned after a KWin reconfigure")
        shell.close()
        check(wait_until(lambda: bus_owner(s, "org.kristall.AppMenuView") is None, 5), "org.kristall.AppMenuView released with the last subscriber")
        check(bus_owner(s, "org.kde.kappmenuview") is not None, "org.kde.kappmenuview kept")


@test
def test_menus_of_apps_started_before_the_shell():
    """a Qt app started before any menu bar exists (login, shell restart) still exports its menus"""
    with Session() as s:
        b = s.bridge()
        kded = s.spawn(["kded6"], "kded", merge_stderr=True)
        check(wait_until(lambda: bus_owner(s, "com.canonical.AppMenu.Registrar"), 10), "the registrar exists with no shell running")
        q = s.qtprobe("early", env={"QT_QPA_PLATFORMTHEME": "kde"})
        lay = q.wait("layout", 8)
        check(lay is not None and lay["nativeMenuBar"], f"the early app's menu bar is native (exported) {lay}")
        w = find_window(b, lambda v: v["title"] == "early" and v["menu"], 10)
        check(w is not None, "KWin knows its DBusMenu")
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        items = dbusmenu_items(dbusmenu(w["menu"]["service"], w["menu"]["path"])[1])
        check("File" in items and "New" in items, f"its menus can be read once the shell is there: {sorted(items)[:6]}")
        m = q.mark()
        dbusmenu_click(w["menu"]["service"], w["menu"]["path"], items["New"][0])
        check(q.wait(lambda e: e.get("ev") == "action" and e.get("name") == "New", 5, since=m), "File > New activates the app's action")


@test
def test_qt_menu_bar_fallback():
    """Qt apps with the kristall platform theme: own menu bar while no menu bar shows app menus, exported again after"""
    with Session() as s:
        b = s.bridge()
        kded = s.spawn(["kded6"], "kded", merge_stderr=True)
        check(wait_until(lambda: bus_owner(s, "com.canonical.AppMenu.Registrar"), 10), "registrar")
        env = {"QT_QPA_PLATFORMTHEME": "kristall", "KRISTALL_APPMENU_FALLBACK_MS": "400"}
        # 1. an app started while no shell runs: native first, then its own menu bar after the grace period
        q1 = s.qtprobe("alone", env=env, name="qt-alone")
        lay = q1.wait("layout", 8)
        check(lay is not None and "nativeMenuBar" in lay, f"the kristall theme loads (the app runs) {lay}")
        ev = q1.wait(lambda e: e.get("ev") == "menubar" and e["visible"] and not e["native"] and e["h"] > 0, 6)
        check(ev is not None, f"no menu bar shows app menus: the app shows its own menu bar {ev}")
        # 2. the shell starts: both apps export, nothing in the windows
        m1 = q1.mark()
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        ev = q1.wait(lambda e: e.get("ev") == "menubar" and not e["visible"] and e["native"], 6, since=m1)
        check(ev is not None, "the shell arrives: the menu bar is exported again and hidden in the window")
        w1 = find_window(b, lambda v: v["title"] == "alone" and v["menu"], 8)
        check(w1 is not None, f"KWin knows the app's DBusMenu again {w1 and w1['menu']}")
        q2 = s.qtprobe("guarded", env=env, name="qt-guarded")
        lay = q2.wait("layout", 8)
        check(lay is not None and lay["nativeMenuBar"] and not lay["menubarVisible"], f"app started with the shell: exported, not in the window {lay}")
        w2 = find_window(b, lambda v: v["title"] == "guarded" and v["menu"], 8)
        check(w2 is not None, "…and KWin knows its DBusMenu")
        # 3. the shell crashes: after the grace period both show their own menu bars
        m1, m2 = q1.mark(), q2.mark()
        shell.close()
        for q, m, name in ((q1, m1, "alone"), (q2, m2, "guarded")):
            ev = q.wait(lambda e: e.get("ev") == "menubar" and e["visible"] and not e["native"] and e["h"] > 0, 6, since=m)
            check(ev is not None, f"shell gone: '{name}' shows its own menu bar ({ev})")
        # 4. the shell is back: exported again, the menus work through DBusMenu
        m2 = q2.mark()
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        ev = q2.wait(lambda e: e.get("ev") == "menubar" and not e["visible"] and e["native"], 6, since=m2)
        check(ev is not None, "shell back: hidden in the window, exported again")
        w = find_window(b, lambda v: v["title"] == "guarded" and v["menu"] and v["menu"]["path"] != w2["menu"]["path"], 8)
        check(w is not None, f"KWin knows the new DBusMenu {w and w['menu']}")
        items = dbusmenu_items(dbusmenu(w["menu"]["service"], w["menu"]["path"])[1])
        check(all(k in items for k in ("File", "New", "Open", "Quit", "Edit", "Copy")), f"the exported menu is complete again: {sorted(items)}")
        m2 = q2.mark()
        dbusmenu_click(w["menu"]["service"], w["menu"]["path"], items["Open"][0])
        check(q2.wait(lambda e: e.get("ev") == "action" and e.get("name") == "Open", 5, since=m2), "File > Open from the exported menu runs the app's action")
        check(q1.alive() and q2.alive(), "both apps still run")


GTKMODULE = os.path.join(BUILD, "gtkmodules", "libkristall-appmenu-gtk-module.so")


@test
def test_gtk_wayland_menus():
    """GTK 3 on native Wayland (kristall-appmenu-gtk-module): menus in the menu bar, own menu bar as fallback"""
    check(os.path.exists(GTKMODULE), f"the GTK module was built (needs gtk3-devel): {GTKMODULE}")
    with Session() as s:
        b = s.bridge()
        env = {"GDK_BACKEND": "wayland", "GTK_MODULES": GTKMODULE, "KRISTALL_APPMENU_FALLBACK_MS": "400"}
        # as on the OS: Plasma's gmenudbusmenuproxy wrote gtk-shell-shows-menubar=1 (meant for X11)
        os.makedirs(os.path.join(s.config, "gtk-3.0"), exist_ok=True)
        with open(os.path.join(s.config, "gtk-3.0", "settings.ini"), "w") as f:
            f.write("[Settings]\ngtk-shell-shows-menubar=1\n")
        plain = s.spawn(["python3", GTKPROBE, "gtk-plain"], "gtkplain", env={"GDK_BACKEND": "wayland"})
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        check(wait_until(lambda: bus_owner(s, "org.kristall.AppMenuView"), 5), "a menu bar shows app menus")
        g = s.spawn(["python3", GTKPROBE, "gtk-wl"], "gtkwl", env=env)
        w = find_window(b, lambda v: v["title"] == "gtk-wl" and v["menu"], 10)
        check(w is not None, f"KWin knows the GTK window's DBusMenu {w and w['menu']}")
        lay = g.wait("layout", 8)
        bars = [e for e in g.snapshot() if e.get("ev") == "menubar"]
        check(lay is not None and lay["menubar"]["h"] == 0 and lay["line"]["y"] == 0 and bars and not bars[-1]["mapped"],
              f"its own menu bar takes no space and is not shown in the window {lay} {bars[-3:]}")
        lay = plain.wait("layout", 8)
        check(lay is not None and lay["menubar"]["h"] > 0, "control: without the module the menu bar stays in the window")
        check(find_window(b, lambda v: v["title"] == "gtk-plain", 3)["menu"] is None, "…and nothing is exported")
        items = dbusmenu_items(dbusmenu(w["menu"]["service"], w["menu"]["path"])[1])
        check(all(k in items for k in ("File", "Open", "Wrap")), f"File menu with its items {sorted(items)}")
        check(items["Open"][1].get("shortcut") == [["Control", "O"]], f"accelerator exported as shortcut {items['Open'][1]}")
        check(items["Wrap"][1].get("toggle-type") == "checkmark" and items["Wrap"][1].get("toggle-state") == 0, f"check item {items['Wrap'][1]}")
        m = g.mark()
        dbusmenu_click(w["menu"]["service"], w["menu"]["path"], items["Open"][0])
        check(g.wait(lambda e: e.get("ev") == "action" and e.get("name") == "Open", 5, since=m), "clicking Open runs the app's handler")
        dbusmenu_click(w["menu"]["service"], w["menu"]["path"], items["Wrap"][0])
        check(g.wait(lambda e: e.get("ev") == "toggled" and e.get("active") is True, 5, since=m), "clicking Wrap toggles it")
        state = wait_until(lambda: dbusmenu_items(dbusmenu(w["menu"]["service"], w["menu"]["path"])[1])["Wrap"][1].get("toggle-state") == 1, 3)
        check(state, "the exported check state follows")
        # the shell crashes: after the grace period the menu bar is back in the window
        m = g.mark()
        shell.close()
        ev = g.wait(lambda e: e.get("ev") == "menubar" and e.get("mapped") and e.get("h", 0) >= 10, 6, since=m)
        check(ev is not None, f"no menu bar shows app menus: the GTK app shows its own {ev}")
        m = g.mark()
        shell = s.bridge("shell")
        shell.subscribe("windows", "menus")
        ev = g.wait(lambda e: e.get("ev") == "menubar" and not e.get("mapped"), 6, since=m)
        check(ev is not None, "shell back: hidden in the window again")
        # GtkApplication menu bar (GMenu model), with gtk-shell-shows-menubar=1 in settings.ini
        ga = s.spawn(["python3", GTKPROBE, "gtk-app", "--app"], "gtkapp", env=env)
        w = find_window(b, lambda v: v["title"] == "gtk-app" and v["menu"], 10)
        check(w is not None, f"GtkApplicationWindow: its menu bar is created and exported {w and w['menu']}")
        items = dbusmenu_items(dbusmenu(w["menu"]["service"], w["menu"]["path"])[1])
        check("File" in items and "Open" in items and items["Open"][1].get("shortcut") == [["Control", "O"]], f"GMenu items {items}")
        m = ga.mark()
        dbusmenu_click(w["menu"]["service"], w["menu"]["path"], items["Open"][0])
        check(ga.wait(lambda e: e.get("ev") == "action" and e.get("name") == "Open", 5, since=m), "app.open runs")
        lay = ga.wait("layout", 5)
        check(lay is not None and lay["content_y"] == 0, f"…and its menu bar takes no space in the window {lay}")
        m = ga.mark()
        shell.close()
        ev = ga.wait(lambda e: e.get("ev") == "content" and e.get("y", 0) > 0, 6, since=m)
        check(ev is not None, f"shell gone: the GtkApplicationWindow shows its menu bar {ev}")


ICON_SCRIPT = r"""
for (const w of workspace.windowList()) {
    if (w.caption === "iconwin") {
        const g = w.iconGeometry;
        console.warn("ICONGEOM " + g.x + " " + g.y + " " + g.width + " " + g.height);
    }
}
"""


def kwin_script(s, source, tag):
    path = os.path.join(s.tmp, f"{tag}.js")
    with open(path, "w") as f:
        f.write(source)
    r = subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "loadScript", "ss", path, tag],
                       env=s.env(), capture_output=True, text=True)
    sid = r.stdout.split()[-1] if r.returncode == 0 else None
    if sid is None:
        return None
    subprocess.run(["busctl", "--user", "call", "org.kde.KWin", f"/Scripting/Script{sid}", "org.kde.kwin.Script", "run"], env=s.env(), capture_output=True)
    time.sleep(0.5)
    subprocess.run(["busctl", "--user", "call", "org.kde.KWin", "/Scripting", "org.kde.kwin.Scripting", "unloadScript", "s", tag], env=s.env(), capture_output=True)
    return True


@test
def test_icon_geometry():
    """window.setIconGeometry becomes the window's iconGeometry (what minimise animations fly to)"""
    for scale, outputs in ((1.0, 1), (1.6, 2)):
        with Session(scale=scale, outputs=outputs) as s:
            b = s.bridge()
            check("iconGeometry" in b.capabilities, "capability advertised")
            p = s.wlprobe("--title", "iconwin", "--size", "300x200")
            w = window_by_title(b, "iconwin")
            b.call("subscribe", events=["outputs"])
            outs = b.wait_event("outputs.changed", 3)["data"]["outputs"]
            last = outs[-1]
            rect = (last["x"] + 300, last["y"] + last["h"] - 70, 64, 64)
            b.call("window.setIconGeometry", id=w["id"], x=rect[0], y=rect[1], w=rect[2], h=rect[3])
            time.sleep(0.3)
            kwin_script(s, ICON_SCRIPT, f"icon{outputs}")
            lines = [l for l in s.log_text().splitlines() if "ICONGEOM" in l]
            got = tuple(float(v) for v in lines[-1].split("ICONGEOM")[1].split()) if lines else None
            check(got is not None and all(abs(a - b_) <= 1 for a, b_ in zip(got, rect)),
                  f"[scale {scale}, {outputs} outputs] KWin's iconGeometry {got} == requested {rect}")
            # bridge-internal anchor surfaces never show up as windows
            check(not [v for v in b.call("window.list")["windows"] if (v.get("namespace") or "").startswith("kristall-bridge")],
                  "the helper's anchor surfaces are not reported")
            b.call("window.setIconGeometry", id=w["id"], x=0, y=0, w=0, h=0)
            time.sleep(0.3)
            kwin_script(s, ICON_SCRIPT, f"icon{outputs}b")
            lines = [l for l in s.log_text().splitlines() if "ICONGEOM" in l]
            check(lines and lines[-1].split("ICONGEOM")[1].split() == ["0", "0", "0", "0"], "an empty rectangle clears it")


@test
def test_desktops_outputs_and_misc_methods():
    """desktop.set, window.toDesktop, window.toOutput, showDesktop, effect.toggle, cursor.get, validation"""
    with Session(outputs=2, kwinrc_extra="[Desktops]\nNumber=3\nRows=1\n") as s:
        b = s.bridge()
        p = s.wlprobe("--title", "mover", "--size", "200x150")
        w = window_by_title(b, "mover")
        b.subscribe("desktops", "outputs")
        d = b.wait_event("desktops.changed", 3)["data"]
        o = b.wait_event("outputs.changed", 3)["data"]["outputs"]
        check(d["count"] == 3 and len(d["names"]) == 3, f"three desktops: {d}")
        check(len(o) == 2 and o[0]["x"] != o[1]["x"], f"two outputs side by side: {[(x['name'], x['x']) for x in o]}")
        b.call("window.toDesktop", id=w["id"], desktop=2)
        check(wait_until(lambda: refresh(b, w)["desktops"] == [2], 3), "window.toDesktop")
        b.call("desktop.set", index=2)
        check(b.wait_event(lambda e: e["event"] == "desktops.changed" and e["data"]["current"] == 2, 3), "desktop.set emits desktops.changed")
        b.call("window.toOutput", id=w["id"], output=o[1]["name"])
        check(wait_until(lambda: refresh(b, w)["output"] == o[1]["name"], 3), "window.toOutput")
        b.call("workspace.showDesktop", value=True)
        b.call("workspace.showDesktop", value=False)
        try:
            r = b.call("effect.toggle", name="overview")
            note(f"effect.toggle overview: {r}")
        except BridgeError as e:
            note(f"effect.toggle overview: {e.code} ({e.message}) -- the overview effect needs org.kde.milou, absent here")
        for bad, params in (("desktop.set", {"index": 9}), ("window.toOutput", {"id": w["id"], "output": "nope"}),
                            ("window.setGeometry", {"id": w["id"], "x": "a", "y": 0, "w": 1, "h": 1}),
                            ("window.setGeometry", {"id": w["id"], "x": 1e300, "y": 0, "w": 1, "h": 1}),
                            ("effect.toggle", {"name": "explode"}), ("window.close", {"id": "nope"})):
            try:
                b.call(bad, **params)
                check(False, f"{bad} {params} must fail")
            except BridgeError as e:
                check(e.code in ("invalid", "not_found"), f"{bad} {params}: {e.code}")
        cur = b.call("cursor.get")
        check(set(cur) == {"x", "y"}, f"cursor.get {cur}")


BARS_QML = r"""
import QtQuick
import Quickshell
import Quickshell.Wayland
ShellRoot {
    PanelWindow {
        screen: Quickshell.screens[0]
        WlrLayershell.namespace: "kristall-bar"
        anchors { top: true; left: true; right: true }
        implicitHeight: 30
        exclusiveZone: 30
        color: "#202020"
    }
    PanelWindow {
        screen: Quickshell.screens[0]
        WlrLayershell.namespace: "kristall-dock"
        anchors { bottom: true; left: true; right: true }
        implicitHeight: 60
        exclusiveZone: 66
        color: "#3050ff"
    }
}
"""


@test
def test_work_area():
    """outputs carry workArea: the output minus the menu bar's and Dock's exclusive zones, kept current"""
    with Session(outputs=2) as s:
        b = s.bridge()
        check("workArea" in b.capabilities, f"capability advertised: {sorted(b.capabilities)}")
        b.subscribe("outputs")
        o = b.wait_event("outputs.changed", 3)["data"]["outputs"]
        check(all(x["workArea"] == {"x": x["x"], "y": x["y"], "w": x["w"], "h": x["h"]} for x in o),
              f"without reservations workArea is the whole output: {[x['workArea'] for x in o]}")
        path = os.path.join(s.tmp, "bars.qml")
        with open(path, "w") as f:
            f.write(BARS_QML)
        shell = s.spawn(["quickshell", "-p", path], "shell", env={"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "software"}, merge_stderr=True)
        ev = b.wait_event(lambda e: e["event"] == "outputs.changed" and any(x["workArea"]["h"] == x["h"] - 96 for x in e["data"]["outputs"]), 10)
        check(ev is not None, f"outputs.changed when the bar and Dock reserve space: {ev and ev['data']}")
        o = ev["data"]["outputs"]
        bar_out = next(x for x in o if x["workArea"]["h"] != x["h"])
        other = next(x for x in o if x is not bar_out)
        check(bar_out["workArea"] == {"x": bar_out["x"], "y": bar_out["y"] + 30, "w": bar_out["w"], "h": bar_out["h"] - 96},
              f"workArea excludes 30 px at the top and 66 px at the bottom: {bar_out['workArea']} of {bar_out['w']}x{bar_out['h']}")
        check(other["workArea"] == {"x": other["x"], "y": other["y"], "w": other["w"], "h": other["h"]},
              f"the other output is unaffected: {other['workArea']}")
        snap = s.bridge("late")
        snap.subscribe("outputs")
        late = snap.wait_event("outputs.changed", 3)["data"]["outputs"]
        check(late == o, "a new subscriber's snapshot has the same workArea")
        # a maximised window fills exactly the work area
        s.qtprobe("max")  # a client that follows the size the compositor configures
        w = window_by_title(b, "max")
        b.call("window.toOutput", id=w["id"], output=bar_out["name"])
        b.call("window.setMaximized", id=w["id"], value=True)
        wa = bar_out["workArea"]
        got = wait_until(lambda: (lambda v: v["maximized"] and (v["x"], v["y"], v["w"], v["h"]) == (wa["x"], wa["y"], wa["w"], wa["h"]) and v)(refresh(b, w)), 5)
        check(bool(got), f"a maximised window covers exactly the work area: {refresh(b, w)}")
        b.drain_events(0.3)
        s.stop_proc(shell)
        ev = b.wait_event(lambda e: e["event"] == "outputs.changed" and all(x["workArea"]["h"] == x["h"] for x in e["data"]["outputs"]), 10)
        check(ev is not None, "outputs.changed when the reservations go away")
        b.drain_events(0.5)
        b.call("window.setMaximized", id=w["id"], value=False)
        check(b.wait_event("outputs.changed", 1.0) is None, "no outputs.changed when nothing about the outputs changed")


@test
def test_pointer_constraint_fields():
    """pointerLocked / pointerConstrained: a game-style pointer lock or confinement is reported, and changes live"""
    with Session() as s:
        b = s.bridge()
        o = s.owner()                    # a pointer device, so clients create wl_pointer
        o.move(400, 300)
        s.wlprobe("--title", "plain", "--size", "300x200")
        s.wlprobe("--title", "locked", "--size", "300x200", "--lock")
        s.wlprobe("--title", "confined", "--size", "300x200", "--confine")
        tog = s.wlprobe("--title", "toggle", "--size", "300x200", "--lock-on-key")
        for title, lk, cf in (("plain", False, False), ("locked", True, False), ("confined", False, True), ("toggle", False, False)):
            w = wait_until(lambda: (lambda x: x if x.get("pointerLocked") == lk and x.get("pointerConstrained") == cf else None)(window_by_title(b, title)), 3) \
                or window_by_title(b, title)
            check(w.get("pointerLocked") == lk and w.get("pointerConstrained") == cf,
                  f"{title}: pointerLocked={w.get('pointerLocked')} pointerConstrained={w.get('pointerConstrained')} (want {lk}, {cf})")
        wt = window_by_title(b, "toggle")
        watcher = s.bridge("watcher")
        watcher.subscribe("windows")
        watcher.wait_event("windows.snapshot", 3)
        with b.agent_session("lock") as a:
            m = tog.mark()
            a.key("l", window_id=wt["id"])
            check(tog.wait(lambda e: e.get("ev") == "lock" and e.get("on") is True, 3, since=m) is not None, "the toggle window requested a lock")
            ev = watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["id"] == wt["id"]
                                    and e["data"]["changes"].get("pointerLocked") is True, 3)
            check(ev is not None, "window.changed carries pointerLocked: true when the lock is requested")
            m = tog.mark()
            a.key("l", window_id=wt["id"])
            check(tog.wait(lambda e: e.get("ev") == "lock" and e.get("on") is False, 3, since=m) is not None, "the toggle window released the lock")
            ev = watcher.wait_event(lambda e: e["event"] == "window.changed" and e["data"]["id"] == wt["id"]
                                    and e["data"]["changes"].get("pointerLocked") is False, 3)
            check(ev is not None, "window.changed carries pointerLocked: false when the lock is destroyed")


if __name__ == "__main__":
    sys.exit(run(sys.argv[1:]))
