# SPDX-License-Identifier: GPL-3.0-or-later
"""Tier 1: direct actions.  Each one is a single call to a stable system interface (D-Bus
services of Plasma, NetworkManager, BlueZ, UPower, logind, systemd, MPRIS; our settings tool; the
bridge's window methods; WirePlumber's `wpctl`)."""
from __future__ import annotations

import datetime as dt
import json
import os
import re
import shutil
import subprocess
import time
import urllib.parse

from . import apps as appsmod
from . import dbus, log
from .bridge import BridgeError
from .core import Hands
from .safety import mask_secrets
from .tooling import Context, HandsError, Registry, Result

ALLOWED_SCHEMES = {"http", "https", "mailto", "file", "tel", "appstream", "steam", "magnet"}


def _run(cmd: list[str], timeout: float = 5.0, input_text: str | None = None, what: str = "") -> str:
    exe = shutil.which(cmd[0])
    if not exe:
        raise HandsError(f"{what or cmd[0]} is not available on this system.")
    try:
        r = subprocess.run([exe] + cmd[1:], capture_output=True, text=True, timeout=timeout, input=input_text)
    except subprocess.TimeoutExpired:
        raise HandsError(f"{what or cmd[0]} did not respond in time.")
    if r.returncode != 0:
        log.info("%s failed (%s): %s", cmd[0], r.returncode, r.stderr.strip()[:300])
        raise HandsError(f"{what or cmd[0]} reported an error: {r.stderr.strip()[:160] or r.returncode}")
    return r.stdout


def power_status() -> dict | None:
    """`kristall-power status --json` (docs/contracts/power.md §7.2), or None without it."""
    exe = shutil.which("kristall-power")
    if not exe:
        return None
    try:
        r = subprocess.run([exe, "status", "--json"], capture_output=True, text=True, timeout=8)
        d = json.loads(r.stdout or "null") if r.returncode == 0 else None
    except (OSError, ValueError, subprocess.SubprocessError) as e:
        log.info("kristall-power status failed: %s", e)
        return None
    return d if isinstance(d, dict) else None


def _dbus_err(what: str, e: dbus.DBusError) -> HandsError:
    if e.name in ("org.freedesktop.DBus.Error.ServiceUnknown", "org.freedesktop.DBus.Error.NameHasNoOwner",
                  "org.kristall.NoGio", "org.kristall.NoBus"):
        return HandsError(f"{what} is not available on this system right now.")
    if "NotAuthorized" in e.name or "AccessDenied" in e.name or "PermissionDenied" in e.name:
        return HandsError(f"{what}: the system needs an administrator password for this, so I can't do it. "
                          f"The owner can change it in System Settings.")
    return HandsError(f"{what} did not work: {e.message[:160]}")


def home() -> str:
    return os.path.expanduser("~")


def resolve_path(p: str) -> str:
    p = os.path.expanduser(p.strip())
    if p.startswith("file://"):
        p = urllib.parse.unquote(urllib.parse.urlparse(p).path)
    if not os.path.isabs(p):
        p = os.path.join(home(), p)
    return os.path.normpath(p)


FORBIDDEN = ("~/.claude", "~/.claude.json", "~/.config/claude", "~/.config/kristall/assistant")


def forbidden(path: str) -> bool:
    for f in FORBIDDEN:
        fp = os.path.expanduser(f)
        if path == fp or path.startswith(fp.rstrip("/") + "/") or path.startswith(fp + "."):
            return True
    return False


def register(reg: Registry, h: Hands) -> None:
    # ======================================================================== apps & files
    def window_matches(w: dict, app: appsmod.App, pids: list[int] | None = None) -> bool:
        aid = str(w.get("appId", "")).lower()
        if pids and w.get("pid") in pids:
            return True
        cands = {app.stem.lower(), app.stem.lower().split(".")[-1], (app.wm_class or "").lower(),
                 (app.exec_name or "").lower()}
        cands.discard("")
        return aid in cands

    def wait_for_window(ctx: Context, app: appsmod.App, pids: list[int], before: set, timeout: float = 10.0):
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            ctx.sleep(0.25)
            try:
                for w in h.windows():
                    if w.get("id") not in before and window_matches(w, app, pids):
                        return w
            except (HandsError, BridgeError):
                return None
        return None

    @reg.tool("open_app",
              "Open an app by its name in German or English (\"Rechner\", \"Dateien\", \"Firefox\", "
              "\"Blender\", \"Einstellungen\"). If it is already open, its window is brought to the front "
              "instead. Returns the window it opened. Use this, never clicks, to start apps.",
              {"name": {"type": "string", "description": "The app's name as the owner said it.", "maxLength": 200},
               "new_window": {"type": "boolean", "description": "Open another window even if the app is open."}},
              ["name"], risk="reversible", title="Open app")
    def open_app(ctx: Context, name: str, new_window: bool = False) -> Result:
        found = h.apps.find(name)
        if not found:
            raise HandsError(f"I can't find an app called “{name[:60]}” on this computer. It can be installed "
                             f"from the App Center if it exists for Linux.")
        score, app = found[0]
        if score < 100 and len(found) > 1 and found[1][0] >= score - 2 and found[1][1].stem != app.stem:
            opts = "; ".join(f"{a.title(h.lang())} (id {a.desktop_id})" for _, a in found[:4])
            return Result.text("Several apps match. Ask the owner which one, or call open_app again with "
                               "the exact id:", opts)
        if not app.installed:
            raise HandsError(f"{app.title(h.lang())} is not installed on this computer yet (it may still be "
                             f"downloading after setup). It can be installed from the App Center.")
        before: set = set()
        bridge_ok = h.bridge.ensure()
        if bridge_ok:
            try:
                wins = h.windows()
                before = {w.get("id") for w in wins}
                mine = [w for w in wins if window_matches(w, app)]
                if mine and not new_window:
                    w = next((x for x in mine if x.get("active")), mine[-1])
                    if w.get("minimized"):
                        h.bridge.request("window.setMinimized", {"id": w["id"], "value": False})
                    h.bridge.request("window.activate", {"id": w["id"]})
                    return Result.text(f"{app.title(h.lang())} was already open; its window is now in front.",
                                       h.describe_window(dict(w, active=True)))
            except (BridgeError, HandsError) as e:
                log.info("window check before launch failed: %s", e)
        if h.a11y is not None:
            h.a11y.prepare()
        try:
            pids = appsmod.launch(app)
        except OSError as e:
            raise HandsError(f"{app.title(h.lang())} could not be started ({str(e)[:120]}).")
        log.info("launched %s pids=%s", app.desktop_id, pids)
        if bridge_ok:
            w = wait_for_window(ctx, app, pids, before)
            if w:
                return Result.text(f"{app.title(h.lang())} is open and in front.", h.describe_window(w))
            return Result.text(f"{app.title(h.lang())} is starting; its window has not appeared yet. "
                               f"Check with list_windows in a moment if you need it.")
        ctx.sleep(1.0)
        return Result.text(f"{app.title(h.lang())} is starting.")

    @reg.tool("open",
              "Open a file, folder or web address in its default app (or in a named app). Paths may start "
              "with ~ or be relative to the home folder; web addresses need http(s)://.",
              {"target": {"type": "string", "description": "Path, file:// or https:// URL, mailto: …", "maxLength": 4000},
               "app": {"type": "string", "description": "Optional app name to open it with.", "maxLength": 200}},
              ["target"], risk="reversible", title="Open file or link")
    def open_target(ctx: Context, target: str, app: str | None = None) -> Result:
        t = target.strip()
        m = re.match(r"^([a-zA-Z][a-zA-Z0-9+.-]*):", t)
        if m and not t.startswith("file:") and len(m.group(1)) > 1:
            scheme = m.group(1).lower()
            if scheme not in ALLOWED_SCHEMES:
                raise HandsError(f"I don't open “{scheme}:” links. Only web, mail and file links.")
            uri, kind, value = t, "scheme", scheme
            label = urllib.parse.urlparse(t).hostname or t[:60]
        else:
            path = resolve_path(t)
            if forbidden(path):
                raise HandsError("That location belongs to the assistant itself and is off limits.")
            if not os.path.exists(path):
                raise HandsError(f"There is no file or folder at {path}.")
            if os.path.isfile(path) and (path.endswith(".desktop") or (os.access(path, os.X_OK) and not _looks_like_document(path))):
                raise HandsError("That is a program, not a document. I don't run programs this way; use open_app for apps.")
            uri = "file://" + urllib.parse.quote(path)
            kind, value = ("mime", "inode/directory") if os.path.isdir(path) else ("mime", _mime_of(path))
            label = os.path.basename(path) or path
        if app:
            found = h.apps.find(app)
            if not found or not found[0][1].installed:
                raise HandsError(f"I can't find the app “{app[:60]}”.")
            handler = found[0][1]
        else:
            did = h.apps.default_for(kind, value) if value else None
            handler = h.apps.apps().get(did) if did else None
            if handler is None:
                fallback = _gio_open(uri)
                if fallback:
                    return Result.text(f"Opened “{label}”.")
                raise HandsError(f"There is no app on this computer that opens “{label}”.")
        if h.a11y is not None:
            h.a11y.prepare()
        try:
            appsmod.launch(handler, [uri])
        except OSError as e:
            raise HandsError(f"Could not open “{label}” with {handler.title(h.lang())} ({str(e)[:100]}).")
        ctx.sleep(0.5)
        return Result.text(f"Opened “{label}” with {handler.title(h.lang())}.")

    @reg.tool("list_windows",
              "List the open windows (id like w3, title, app, size, which one is active). Window titles are "
              "screen content.", {}, risk="read", read_only=True, title="List windows")
    def list_windows(ctx: Context) -> Result:
        h.guard(ctx, acting=False)
        wins = h.windows()
        if not wins:
            return Result.text("No windows are open.")
        lines = [h.describe_window(w) for w in wins]
        return Result.text(f"{len(wins)} windows, back to front:", "\n".join(lines))

    @reg.tool("window",
              "Change a window: activate (bring to front), close, minimize, restore, maximize, unmaximize, "
              "fullscreen, left_half, right_half, center, move_resize (x,y,w,h in logical pixels), "
              "side_by_side (window left, other right). The window is an id from list_windows or an app "
              "name/title; default is the active window. Closing asks the app to close: it may ask to save.",
              {"action": {"type": "string", "enum": ["activate", "close", "minimize", "restore", "maximize",
                                                       "unmaximize", "fullscreen", "left_half", "right_half",
                                                       "center", "move_resize", "side_by_side"]},
               "window": {"type": "string", "description": "Window id (w3), app name or title."},
               "other": {"type": "string", "description": "Second window for side_by_side."},
               "x": {"type": "number"}, "y": {"type": "number"}, "w": {"type": "number"}, "h": {"type": "number"}},
              ["action"], risk="reversible", title="Arrange window")
    def window(ctx: Context, action: str, window: str | None = None, other: str | None = None,
               x: float | None = None, y: float | None = None, w: float | None = None, **kw) -> Result:
        hh = kw.get("h")
        h.guard(ctx, acting=True)
        b = h.need_bridge()
        win = h.resolve_window(window)
        wid = win["id"]
        area = _work_area(h, win)
        try:
            if action == "activate":
                if win.get("minimized"):
                    b.request("window.setMinimized", {"id": wid, "value": False})
                b.request("window.activate", {"id": wid})
            elif action == "close":
                b.request("window.close", {"id": wid})
            elif action == "minimize":
                b.request("window.setMinimized", {"id": wid, "value": True})
            elif action == "restore":
                b.request("window.setMinimized", {"id": wid, "value": False})
                if win.get("fullscreen"):
                    b.request("window.setFullscreen", {"id": wid, "value": False})
                b.request("window.activate", {"id": wid})
            elif action == "maximize":
                b.request("window.setMaximized", {"id": wid, "value": True})
            elif action == "unmaximize":
                b.request("window.setMaximized", {"id": wid, "value": False})
            elif action == "fullscreen":
                b.request("window.setFullscreen", {"id": wid, "value": not win.get("fullscreen")})
            elif action in ("left_half", "right_half", "center", "move_resize", "side_by_side"):
                ax, ay, aw, ah = area
                if action == "side_by_side":
                    if not other:
                        raise HandsError("side_by_side needs a second window in 'other'.")
                    win2 = h.resolve_window(other, default_active=False)
                    if win2["id"] == wid:
                        raise HandsError("side_by_side needs two different windows.")
                    _place(b, win, ax, ay, aw / 2, ah)
                    _place(b, win2, ax + aw / 2, ay, aw / 2, ah)
                    b.request("window.activate", {"id": wid})
                    return Result.text("Placed side by side.", h.describe_window(win) + "\n" + h.describe_window(win2))
                if action == "left_half":
                    geo = (ax, ay, aw / 2, ah)
                elif action == "right_half":
                    geo = (ax + aw / 2, ay, aw / 2, ah)
                elif action == "center":
                    ww, wh = min(win.get("w", aw * .6), aw), min(win.get("h", ah * .7), ah)
                    geo = (ax + (aw - ww) / 2, ay + (ah - wh) / 2, ww, wh)
                else:
                    if None in (x, y, w, hh):
                        raise HandsError("move_resize needs x, y, w and h.")
                    geo = (x, y, w, hh)
                _place(b, win, *geo)
        except BridgeError as e:
            if e.code == "not_found":
                raise HandsError("That window has just closed.")
            raise HandsError(f"The window could not be changed ({e.code}).")
        h.touch()
        after = h.window_by_id(wid)
        if action == "close":
            end = time.monotonic() + 1.5
            while after is not None and time.monotonic() < end:
                ctx.sleep(0.15)
                after = h.window_by_id(wid)
            if after is None:
                return Result.text("The window is closed.")
            return Result.text("The window is still open: the app is probably asking whether to save. Look at it "
                               "(ui_tree) and ask the owner before discarding anything.", h.describe_window(after))
        return Result.text(f"Done: {action}.", h.describe_window(after) if after else "(window closed)")

    # ======================================================================== sound & screen
    def wpctl_target(device: str) -> str:
        return "@DEFAULT_AUDIO_SOURCE@" if device == "microphone" else "@DEFAULT_AUDIO_SINK@"

    def read_volume(device: str) -> tuple[int, bool]:
        out = _run(["wpctl", "get-volume", wpctl_target(device)], what="Sound control")
        m = re.search(r"([0-9.]+)", out)
        return (round(float(m.group(1)) * 100) if m else 0), "MUTED" in out

    @reg.tool("volume",
              "Read or set the sound volume: level 0–100, or change by a step (+10 louder, -10 quieter), "
              "or mute/unmute. device: speakers (default) or microphone. Use for \"mach leiser\", \"lauter\", "
              "\"stumm\".",
              {"level": {"type": "integer", "minimum": 0, "maximum": 100},
               "change": {"type": "integer", "minimum": -100, "maximum": 100},
               "mute": {"type": "boolean"},
               "device": {"type": "string", "enum": ["speakers", "microphone"]}},
              risk="reversible", title="Volume")
    def volume(ctx: Context, level: int | None = None, change: int | None = None, mute: bool | None = None,
               device: str = "speakers") -> Result:
        tgt = wpctl_target(device)
        if level is not None or change is not None:
            cur, muted = read_volume(device)
            new = level if level is not None else cur + (change or 0)
            new = max(0, min(100, int(new)))
            _run(["wpctl", "set-volume", "-l", "1.0", tgt, f"{new / 100:.2f}"], what="Sound control")
            if muted and mute is None and new > 0:
                _run(["wpctl", "set-mute", tgt, "0"], what="Sound control")
        if mute is not None:
            _run(["wpctl", "set-mute", tgt, "1" if mute else "0"], what="Sound control")
        cur, muted = read_volume(device)
        return Result.text(f"{'Microphone' if device == 'microphone' else 'Volume'}: {cur}%" + (" (muted)" if muted else ""))

    def displays() -> list[tuple[str, dict]]:
        bus = dbus.session()
        names = bus.get("org.kde.ScreenBrightness", "/org/kde/ScreenBrightness", "org.kde.ScreenBrightness",
                        "DisplaysDBusNames")
        out = []
        for n in names:
            props = bus.get_all("org.kde.ScreenBrightness", f"/org/kde/ScreenBrightness/{n}",
                                "org.kde.ScreenBrightness.Display")
            out.append((n, props))
        out.sort(key=lambda t: not t[1].get("IsInternal", False))
        return out

    @reg.tool("brightness",
              "Read or set the screen brightness: level 0–100 or change by a step (+10 brighter, -10 darker).",
              {"level": {"type": "integer", "minimum": 0, "maximum": 100},
               "change": {"type": "integer", "minimum": -100, "maximum": 100},
               "all_displays": {"type": "boolean", "description": "Also external monitors (default: built-in screen)."}},
              risk="reversible", title="Brightness")
    def brightness(ctx: Context, level: int | None = None, change: int | None = None, all_displays: bool = False) -> Result:
        try:
            ds = displays()
        except dbus.DBusError as e:
            raise _dbus_err("Brightness control", e)
        if not ds:
            raise HandsError("No screen with adjustable brightness was found (external monitors often can't be "
                             "dimmed from the computer).")
        targets = ds if all_displays else ds[:1]
        report = []
        for name, p in targets:
            mx = int(p.get("MaxBrightness") or 1)
            cur = round(int(p.get("Brightness") or 0) * 100 / mx)
            if level is not None or change is not None:
                new = level if level is not None else cur + (change or 0)
                new = max(1, min(100, int(new)))      # never fully black: the owner must still see
                try:
                    dbus.session().call("org.kde.ScreenBrightness", f"/org/kde/ScreenBrightness/{name}",
                                        "org.kde.ScreenBrightness.Display", "SetBrightness", "iu",
                                        (round(new * mx / 100), 0))
                except dbus.DBusError as e:
                    raise _dbus_err("Brightness control", e)
                cur = new
            report.append(f"{p.get('Label') or name}: {cur}%")
        return Result.text("Brightness — " + ", ".join(report))

    # ======================================================================== network
    NM = "org.freedesktop.NetworkManager"

    def nm_wifi_device(bus):
        for dev in bus.call(NM, "/org/freedesktop/NetworkManager", NM, "GetDevices")[0]:
            if bus.get(NM, dev, f"{NM}.Device", "DeviceType") == 2:
                return dev
        return None

    def ssid_of(bus, ap) -> str:
        raw = bus.get(NM, ap, f"{NM}.AccessPoint", "Ssid")
        return bytes(raw).decode("utf-8", "replace")

    @reg.tool("wifi",
              "Wi-Fi: status, on, off, list (nearby networks, saved ones marked), connect to a network by "
              "name (only saved or open networks: new passwords are entered by the owner in the Wi-Fi menu), "
              "disconnect.",
              {"action": {"type": "string", "enum": ["status", "on", "off", "list", "connect", "disconnect"]},
               "network": {"type": "string", "maxLength": 64}},
              ["action"], risk="reversible", title="Wi-Fi")
    def wifi(ctx: Context, action: str, network: str | None = None) -> Result:
        bus = dbus.system()
        try:
            if action in ("on", "off"):
                bus.set(NM, "/org/freedesktop/NetworkManager", NM, "WirelessEnabled", "b", action == "on")
                ctx.sleep(0.3)
            if action in ("status", "on", "off"):
                en = bus.get(NM, "/org/freedesktop/NetworkManager", NM, "WirelessEnabled")
                hw = bus.get(NM, "/org/freedesktop/NetworkManager", NM, "WirelessHardwareEnabled")
                txt = "Wi-Fi is " + ("on" if en else "off") + ("" if hw else " (switched off by a hardware switch or airplane mode)")
                dev = nm_wifi_device(bus)
                content = ""
                if dev and en:
                    ap = bus.get(NM, dev, f"{NM}.Device.Wireless", "ActiveAccessPoint")
                    if ap and ap != "/":
                        content = f"connected to {ssid_of(bus, ap)} (signal {bus.get(NM, ap, f'{NM}.AccessPoint', 'Strength')}%)"
                    else:
                        content = "not connected to a network"
                return Result.text(txt + ".", content or None)
            dev = nm_wifi_device(bus)
            if not dev:
                raise HandsError("This computer has no Wi-Fi adapter that I can find.")
            saved = _saved_wifi(bus)
            if action == "list":
                try:
                    bus.call(NM, dev, f"{NM}.Device.Wireless", "RequestScan", "a{sv}", ({},))
                    ctx.sleep(1.5)
                except dbus.DBusError:
                    pass
                seen: dict[str, tuple[int, bool]] = {}
                for ap in bus.call(NM, dev, f"{NM}.Device.Wireless", "GetAllAccessPoints")[0]:
                    s = ssid_of(bus, ap)
                    if not s:
                        continue
                    st = int(bus.get(NM, ap, f"{NM}.AccessPoint", "Strength"))
                    secured = bool(bus.get(NM, ap, f"{NM}.AccessPoint", "RsnFlags") or bus.get(NM, ap, f"{NM}.AccessPoint", "WpaFlags")
                                   or (bus.get(NM, ap, f"{NM}.AccessPoint", "Flags") & 1))
                    if s not in seen or st > seen[s][0]:
                        seen[s] = (st, secured)
                rows = sorted(seen.items(), key=lambda kv: -kv[1][0])[:15]
                lines = [f"{s} — {st}%{' (saved)' if s in saved else ''}{'' if sec else ' (open, no password)'}"
                         for s, (st, sec) in rows]
                return Result.text(f"{len(seen)} networks nearby (strongest first):", "\n".join(lines) or "none")
            if action == "disconnect":
                bus.call(NM, dev, f"{NM}.Device", "Disconnect")
                return Result.text("Wi-Fi disconnected.")
            if action == "connect":
                if not network:
                    raise HandsError("Which network? Give its name in 'network'.")
                if network in saved:
                    bus.call(NM, "/org/freedesktop/NetworkManager", NM, "ActivateConnection", "ooo",
                             (saved[network], dev, "/"))
                    ctx.sleep(3.0)
                    return wifi(ctx, "status")
                for ap in bus.call(NM, dev, f"{NM}.Device.Wireless", "GetAllAccessPoints")[0]:
                    if ssid_of(bus, ap) == network:
                        secured = bus.get(NM, ap, f"{NM}.AccessPoint", "RsnFlags") or bus.get(NM, ap, f"{NM}.AccessPoint", "WpaFlags")
                        if secured:
                            raise HandsError(f"“{network}” needs a password. Passwords are entered by the owner: "
                                             f"open the Wi-Fi menu in the Control Center and choose the network.")
                        bus.call(NM, "/org/freedesktop/NetworkManager", NM, "AddAndActivateConnection", "a{sa{sv}}oo",
                                 ({}, dev, ap))
                        ctx.sleep(3.0)
                        return wifi(ctx, "status")
                raise HandsError(f"I can't see a network called “{network[:40]}” nearby.")
        except dbus.DBusError as e:
            raise _dbus_err("Wi-Fi control", e)
        raise HandsError("Unknown Wi-Fi action.")

    @reg.tool("bluetooth",
              "Bluetooth: status, on, off, list (paired devices), connect or disconnect a paired device by "
              "name. Pairing a new device is done by the owner in the Bluetooth settings.",
              {"action": {"type": "string", "enum": ["status", "on", "off", "list", "connect", "disconnect"]},
               "device": {"type": "string", "maxLength": 100}},
              ["action"], risk="reversible", title="Bluetooth")
    def bluetooth(ctx: Context, action: str, device: str | None = None) -> Result:
        bus = dbus.system()
        try:
            objs = bus.call("org.bluez", "/", "org.freedesktop.DBus.ObjectManager", "GetManagedObjects")[0]
        except dbus.DBusError as e:
            raise _dbus_err("Bluetooth", e)
        adapters = [p for p, ifs in objs.items() if "org.bluez.Adapter1" in ifs]
        if not adapters:
            raise HandsError("This computer has no Bluetooth adapter that I can find, or it is switched off by "
                             "airplane mode.")
        ad = adapters[0]
        devices = [(p, ifs["org.bluez.Device1"]) for p, ifs in objs.items()
                   if "org.bluez.Device1" in ifs and ifs["org.bluez.Device1"].get("Paired")]
        try:
            if action in ("on", "off"):
                bus.set("org.bluez", ad, "org.bluez.Adapter1", "Powered", "b", action == "on")
                return Result.text(f"Bluetooth is {action}.")
            powered = objs[ad]["org.bluez.Adapter1"].get("Powered")
            if action == "status" or action == "list":
                lines = [f"{d.get('Alias') or d.get('Name') or p} — {'connected' if d.get('Connected') else 'not connected'}"
                         for p, d in devices]
                return Result.text(f"Bluetooth is {'on' if powered else 'off'}; {len(devices)} paired devices.",
                                   "\n".join(lines) if lines else None)
            if not device:
                raise HandsError("Which device? Give its name in 'device'.")
            q = appsmod.fold(device)
            match = [(p, d) for p, d in devices if q and q in appsmod.fold(str(d.get("Alias") or d.get("Name") or ""))]
            if not match:
                raise HandsError(f"No paired device matches “{device[:40]}”. New devices are paired by the owner in "
                                 f"the Bluetooth settings.")
            p, d = match[0]
            if not powered:
                bus.set("org.bluez", ad, "org.bluez.Adapter1", "Powered", "b", True)
            bus.call("org.bluez", p, "org.bluez.Device1", "Connect" if action == "connect" else "Disconnect",
                     timeout_ms=20000)
            return Result.text(f"{'Connected' if action == 'connect' else 'Disconnected'}.", str(d.get("Alias") or d.get("Name")))
        except dbus.DBusError as e:
            raise _dbus_err("Bluetooth", e)

    # ======================================================================== look & feel
    @reg.tool("appearance",
              "Change the look: theme light, dark or auto; glass from 0.0 (ultra clear) to 1.0 (fully "
              "tinted); reduce_transparency on/off. Without arguments: report the current look.",
              {"theme": {"type": "string", "enum": ["light", "dark", "auto"]},
               "glass": {"type": "number", "minimum": 0, "maximum": 1},
               "reduce_transparency": {"type": "boolean"}},
              risk="reversible", title="Appearance")
    def appearance(ctx: Context, theme: str | None = None, glass: float | None = None,
                   reduce_transparency: bool | None = None) -> Result:
        try:
            if theme is not None:
                h.settings.set("appearance.theme", theme)
            if glass is not None:
                h.settings.set("appearance.glass", round(float(glass), 2))
            if reduce_transparency is not None:
                h.settings.set("appearance.reduceTransparency", bool(reduce_transparency))
        except OSError as e:
            raise HandsError(f"The appearance setting could not be saved ({str(e)[:100]}).")
        a = h.settings.get("appearance", {}) or {}
        return Result.text(f"Appearance: theme {a.get('theme', 'auto')}, glass {a.get('glass', 0.3)}, "
                           f"reduce transparency {'on' if a.get('reduceTransparency') else 'off'}.")

    @reg.tool("do_not_disturb",
              "Turn Do Not Disturb (no notification banners) on — optionally for some minutes — or off.",
              {"on": {"type": "boolean"}, "minutes": {"type": "integer", "minimum": 1, "maximum": 10080}},
              ["on"], risk="reversible", title="Do Not Disturb")
    def do_not_disturb(ctx: Context, on: bool, minutes: int | None = None) -> Result:
        # The one source of truth is the setting panels.focus.until, owned by the shell's
        # notifications module (shell/modules/panels/README.md): 0 off, -1 until switched off,
        # otherwise ms since the epoch. kristall-settings writes it whether or not the shell runs;
        # the shell watches the file and applies it live.
        if on:
            value = int((time.time() + minutes * 60) * 1000) if minutes else -1
        else:
            value = 0
        try:
            h.settings.set("panels.focus.until", value)
        except OSError as e:
            raise HandsError(f"Do Not Disturb could not be changed ({str(e)[:100]}).")
        if on:
            if minutes:
                end = dt.datetime.fromtimestamp(value / 1000).strftime("%H:%M")
                return Result.text(f"Do Not Disturb is on for {minutes} minutes (until {end}).")
            return Result.text("Do Not Disturb is on until turned off.")
        return Result.text("Do Not Disturb is off.")

    PPD = [("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles",
            "org.freedesktop.UPower.PowerProfiles"),
           ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")]
    MODES = {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}
    MODE_NAMES = {"power-saver": "Leise (quiet)", "balanced": "Ausgewogen (balanced)", "performance": "Leistung (performance)"}
    # kristall-power status --json names modes by the owner's words (power.md §7.2)
    STATUS_NAMES = {"quiet": "Leise (quiet)", "balanced": "Ausgewogen (balanced)", "performance": "Leistung (performance)"}
    REASONS = {"auto-game": "a game is running", "auto-heavy-app": "a heavy app is busy",
               "auto-low-battery": "the battery is low", "auto-battery": "on battery",
               "manual-performance-paused-on-battery": "Leistung is paused while on battery"}

    def describe_power(st: dict) -> str:
        """One line from `kristall-power status --json`: the effective mode and whether it is automatic."""
        mode = STATUS_NAMES.get(str(st.get("mode")), str(st.get("mode") or "unknown"))
        auto = st.get("automatic") or {}
        reason = str(auto.get("reason") or "")
        if auto.get("enabled") and not auto.get("manual"):
            why = REASONS.get(reason, "")
            return f"Power mode: Automatisch (automatic) — now {mode}" + (f", because {why}" if why else "") + "."
        if auto.get("manual"):
            extra = f" ({REASONS[reason]})" if reason in REASONS else ""
            return f"Power mode: {mode}, chosen manually{extra}. 'auto' hands the choice back to the system."
        return f"Power mode: {mode} (automatic switching is off in the settings)."

    def power_ppd(mode: str | None) -> Result:
        bus = dbus.system()
        last = None
        for name, path, iface in PPD:
            try:
                if mode:
                    bus.set(name, path, iface, "ActiveProfile", "s", MODES[mode])
                cur = bus.get(name, path, iface, "ActiveProfile")
                return Result.text(f"Power mode: {MODE_NAMES.get(cur, cur)}.")
            except dbus.DBusError as e:
                last = e
                if "ServiceUnknown" in e.name or "UnknownObject" in e.name or "NoGio" in e.name:
                    continue
                raise _dbus_err("Power mode", e)
        raise _dbus_err("Power mode", last or dbus.DBusError("org.freedesktop.DBus.Error.ServiceUnknown", ""))

    @reg.tool("power_mode",
              "Read or set the power mode: auto (Automatisch, the default: the system chooses — Leise on battery, "
              "Ausgewogen on mains, Leistung on mains while a game or a busy heavy app like Blender runs), "
              "quiet (Leise: cool, silent, longest battery), balanced (Ausgewogen) or performance (Leistung: "
              "full power). Choosing quiet/balanced/performance stays until the owner chooses auto again.",
              {"mode": {"type": "string", "enum": ["auto", "quiet", "balanced", "performance"]}},
              risk="reversible", title="Power mode")
    def power_mode(ctx: Context, mode: str | None = None) -> Result:
        # The power component's CLI is the one implementation (power.md §7.1): `mode auto` resumes
        # automatic switching through the session daemon, the others are the owner's manual choice.
        if shutil.which("kristall-power"):
            if mode:
                try:
                    _run(["kristall-power", "mode", mode], timeout=10, what="Power mode")
                except HandsError:
                    if mode == "auto":
                        raise HandsError("Automatic power mode is not available right now (the power service "
                                         "is not running).")
                    return power_ppd(mode)
            st = power_status()
            if st:
                return Result.text(describe_power(st))
        elif mode == "auto":
            raise HandsError("Automatic power mode is not available on this system.")
        return power_ppd(mode)

    @reg.tool("night_light",
              "Turn Night Light (warmer colours in the evening) on or off; without 'on' just report it.",
              {"on": {"type": "boolean"}}, risk="reversible", title="Night Light")
    def night_light(ctx: Context, on: bool | None = None) -> Result:
        bus = dbus.session()
        if on is not None:
            _run(["kwriteconfig6", "--file", "kwinrc", "--group", "NightColor", "--key", "Active", "--type", "bool",
                  "--notify", "true" if on else "false"], what="Night Light")
            try:
                bus.call("org.kde.KWin", "/KWin", "org.kde.KWin", "reconfigure")
            except dbus.DBusError as e:
                raise _dbus_err("Night Light", e)
            ctx.sleep(0.3)
        try:
            p = bus.get_all("org.kde.KWin", "/org/kde/KWin/NightLight", "org.kde.KWin.NightLight")
        except dbus.DBusError as e:
            if on is not None:
                return Result.text(f"Night Light turned {'on' if on else 'off'}.")
            raise _dbus_err("Night Light", e)
        if not p.get("available", True):
            raise HandsError("Night Light is not available on this screen.")
        state = "on" if p.get("enabled") else "off"
        extra = f", currently {p.get('currentTemperature')} K" if p.get("enabled") else ""
        return Result.text(f"Night Light is {state}{extra}.")

    # ======================================================================== media, session
    def players(bus) -> list[str]:
        return [n for n in bus.list_names() if n.startswith("org.mpris.MediaPlayer2.")]

    @reg.tool("media",
              "Control music and video players: play, pause, toggle, next, previous, stop, or status (what "
              "is playing).",
              {"action": {"type": "string", "enum": ["play", "pause", "toggle", "next", "previous", "stop", "status"]},
               "player": {"type": "string", "description": "Optional player app name.", "maxLength": 80}},
              ["action"], risk="reversible", title="Media")
    def media(ctx: Context, action: str, player: str | None = None) -> Result:
        bus = dbus.session()
        try:
            ps = players(bus)
        except dbus.DBusError as e:
            raise _dbus_err("Media control", e)
        if not ps:
            raise HandsError("No music or video player is running.")
        info = []
        for n in ps:
            try:
                st = bus.get(n, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "PlaybackStatus")
            except dbus.DBusError:
                st = "Unknown"
            info.append((n, st))
        if player:
            q = appsmod.fold(player)
            info = [t for t in info if q in appsmod.fold(t[0].split(".", 3)[-1])] or info
        info.sort(key=lambda t: {"Playing": 0, "Paused": 1}.get(t[1], 2))
        name, status = info[0]
        method = {"play": "Play", "pause": "Pause", "toggle": "PlayPause", "next": "Next", "previous": "Previous",
                  "stop": "Stop"}.get(action)
        try:
            if method:
                bus.call(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", method)
                ctx.sleep(0.3)
            meta = bus.get(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "Metadata") or {}
            status = bus.get(name, "/org/mpris/MediaPlayer2", "org.mpris.MediaPlayer2.Player", "PlaybackStatus")
        except dbus.DBusError as e:
            raise _dbus_err("Media control", e)
        title = meta.get("xesam:title") or ""
        artist = ", ".join(meta.get("xesam:artist") or [])
        app = name.split(".", 3)[-1].split(".")[0]
        return Result.text(f"{app}: {status}.", (f"{title} — {artist}" if artist else title) or None)

    @reg.tool("lock_or_sleep",
              "Lock the screen or put the computer to sleep. After this you can't see or do anything until "
              "the owner unlocks it, so say what you're doing first.",
              {"action": {"type": "string", "enum": ["lock", "sleep"]}}, ["action"],
              risk="reversible", title="Lock or sleep")
    def lock_or_sleep(ctx: Context, action: str) -> Result:
        h.finish_work()
        try:
            if action == "lock":
                dbus.session().call("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver", "Lock")
                return Result.text("The screen is locked.")
            can = dbus.system().call("org.freedesktop.login1", "/org/freedesktop/login1",
                                     "org.freedesktop.login1.Manager", "CanSuspend")[0]
            if can not in ("yes", "challenge"):
                raise HandsError("This computer can't go to sleep right now.")
            dbus.system().call("org.freedesktop.login1", "/org/freedesktop/login1", "org.freedesktop.login1.Manager",
                               "Suspend", "b", (False,))
            return Result.text("The computer is going to sleep.")
        except dbus.DBusError as e:
            raise _dbus_err("Lock" if action == "lock" else "Sleep", e)

    @reg.tool("system_status",
              "Battery (percent, charging, time left), power mode, volume, brightness, Wi-Fi, memory, disk "
              "space and uptime in one call.", {}, risk="read", read_only=True, title="System status")
    def system_status(ctx: Context) -> Result:
        lines = []
        st = power_status()
        bat = (st or {}).get("battery") if st else None
        if st and (bat or st.get("power_source") == "none"):
            # battery, draw and temperatures from the power component (power.md §7.2)
            if bat:
                status = str(bat.get("status") or "")
                src = st.get("power_source")
                state = {"Charging": "charging", "Discharging": "on battery", "Full": "full",
                         "Not charging": "not charging"}.get(status, "on battery" if src == "battery" else "plugged in")
                t = bat.get("time_to_empty_s") if src == "battery" else bat.get("time_to_full_s")
                t = int(t) if isinstance(t, (int, float)) and t > 0 else 0
                left = f", {t // 3600} h {t % 3600 // 60} min {'left' if src == 'battery' else 'until full'}" if t else ""
                line = f"Battery {round(float(bat.get('percent') or 0))}% ({state}{left})"
                if isinstance(bat.get("health_percent"), (int, float)):
                    line += f", health {round(bat['health_percent'])}%"
                lim = (st.get("charge_limit") or {}).get("value")
                if isinstance(lim, int) and lim < 100:
                    line += f", charging stops at {lim}%"
                lines.append(line)
            else:
                lines.append("No battery (mains power)")
            draw = (st.get("draw") or {}).get("watts")
            if isinstance(draw, (int, float)):
                lines.append(f"Power draw: {draw:.1f} W")
            temps = st.get("temperatures") or {}
            cpu = temps.get("cpu_package") if isinstance(temps.get("cpu_package"), (int, float)) else temps.get("cpu_core_max")
            if isinstance(cpu, (int, float)):
                lines.append(f"CPU temperature: {round(cpu)} °C")
            fans = [v for v in (st.get("fans") or {}).values() if isinstance(v, (int, float))]
            if fans:
                lines.append("Fans: " + ("off" if max(fans) == 0 else f"{max(fans)} rpm"))
        else:
            try:
                p = dbus.system().get_all("org.freedesktop.UPower", "/org/freedesktop/UPower/devices/DisplayDevice",
                                          "org.freedesktop.UPower.Device")
                if p.get("IsPresent"):
                    state = {1: "charging", 2: "on battery", 3: "empty", 4: "full", 5: "not charging", 6: "on battery"}.get(int(p.get("State", 0)), "")
                    t = int(p.get("TimeToEmpty") or 0) if p.get("State") in (2, 6) else int(p.get("TimeToFull") or 0)
                    left = f", {t // 3600} h {t % 3600 // 60} min {'left' if p.get('State') in (2, 6) else 'until full'}" if t else ""
                    lines.append(f"Battery {round(p.get('Percentage', 0))}% ({state}{left})")
                else:
                    lines.append("No battery (mains power)")
            except dbus.DBusError:
                lines.append("Battery: unknown")
        if st:
            lines.append(describe_power(st))
        parts = [lambda: volume(ctx), lambda: brightness(ctx), lambda: wifi(ctx, "status")]
        if not st:
            parts.insert(0, lambda: power_mode(ctx))
        for fn in parts:
            try:
                r = fn()
                lines.append(r.parts[0]["text"].replace("\n", " "))
            except (HandsError, Exception) as e:   # each part is optional
                log.debug("status part failed: %s", e)
        try:
            mem = {}
            with open("/proc/meminfo") as f:
                for line in f:
                    k, v = line.split(":", 1)
                    mem[k] = int(v.split()[0])
            lines.append(f"Memory: {round((mem['MemTotal'] - mem['MemAvailable']) / 1048576, 1)} of "
                         f"{round(mem['MemTotal'] / 1048576, 1)} GB in use")
            st = os.statvfs(home())
            lines.append(f"Disk: {round(st.f_bavail * st.f_frsize / 1e9)} GB free of {round(st.f_blocks * st.f_frsize / 1e9)} GB")
            with open("/proc/uptime") as f:
                up = float(f.read().split()[0])
            lines.append(f"Up for {int(up // 86400)} days {int(up % 86400 // 3600)} h {int(up % 3600 // 60)} min")
        except (OSError, KeyError, ValueError):
            pass
        return Result.text("\n".join(lines))

    # ======================================================================== clipboard, notifications, files
    @reg.tool("clipboard",
              "Read the clipboard text (get) or put text on it (set). Contents copied from password managers "
              "are never returned.",
              {"action": {"type": "string", "enum": ["get", "set"]}, "text": {"type": "string", "maxLength": 100000}},
              ["action"], risk="reversible", title="Clipboard")
    def clipboard(ctx: Context, action: str, text: str | None = None) -> Result:
        if action == "set":
            if text is None:
                raise HandsError("Give the text to copy in 'text'.")
            exe = shutil.which("wl-copy")
            if not exe:
                raise HandsError("The clipboard is not available on this system.")
            try:
                subprocess.run([exe, "--type", "text/plain;charset=utf-8"], input=text, text=True, timeout=5,
                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
            except (OSError, subprocess.SubprocessError):
                raise HandsError("The text could not be copied to the clipboard.")
            log.info("clipboard set (%d chars)", len(text))
            return Result.text(f"Copied {len(text)} characters to the clipboard.")
        types = _run(["wl-paste", "--list-types"], what="The clipboard").split()
        if not types:
            return Result.text("The clipboard is empty.")
        if any(t.startswith("x-kde-passwordManagerHint") for t in types):
            return Result.text("The clipboard holds something from a password manager; I don't read that.")
        if not any(t.startswith("text/") or t in ("UTF8_STRING", "STRING", "TEXT") for t in types):
            return Result.text(f"The clipboard holds no text (types: {', '.join(types[:5])}).")
        out = _run(["wl-paste", "--no-newline", "--type", "text"], what="The clipboard")
        out = mask_secrets(out)
        more = f"\n… ({len(out) - 20000} more characters)" if len(out) > 20000 else ""
        return Result.text(f"Clipboard text ({len(out)} characters):", out[:20000] + more)

    @reg.tool("notify",
              "Show a notification banner to the owner (title and optional text).",
              {"title": {"type": "string", "maxLength": 200}, "body": {"type": "string", "maxLength": 1000}},
              ["title"], risk="reversible", title="Notification")
    def notify(ctx: Context, title: str, body: str = "") -> Result:
        try:
            send_notification(title, body)
        except dbus.DBusError as e:
            raise _dbus_err("Notifications", e)
        return Result.text("Notification shown.")

    @reg.tool("reveal_in_files",
              "Show a file or folder in the Files app (opens the folder with the item selected).",
              {"path": {"type": "string", "maxLength": 4000}}, ["path"], risk="read", title="Show in Files")
    def reveal(ctx: Context, path: str) -> Result:
        p = resolve_path(path)
        if not os.path.exists(p):
            raise HandsError(f"There is no file or folder at {p}.")
        uri = "file://" + urllib.parse.quote(p)
        try:
            dbus.session().call("org.freedesktop.FileManager1", "/org/freedesktop/FileManager1",
                                "org.freedesktop.FileManager1", "ShowItems", "ass", ([uri], ""))
        except dbus.DBusError as e:
            raise _dbus_err("The Files app", e)
        return Result.text(f"Showing “{os.path.basename(p)}” in Files.")

    @reg.tool("move_to_trash",
              "Move files or folders to the trash (the owner can restore them). Use this instead of deleting.",
              {"paths": {"type": "array", "items": {"type": "string", "maxLength": 4000}, "maxItems": 500}},
              ["paths"], risk="reversible", title="Move to trash")
    def move_to_trash(ctx: Context, paths: list[str]) -> Result:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio, GLib
        except (ImportError, ValueError):
            raise HandsError("The trash is not available on this system.")
        done, failed = [], []
        for raw in paths:
            ctx.check()
            p = resolve_path(raw)
            if forbidden(p) or p in (home(), "/"):
                failed.append(f"{raw}: not allowed")
                continue
            if not os.path.lexists(p):
                failed.append(f"{raw}: does not exist")
                continue
            try:
                Gio.File.new_for_path(p).trash(None)
                done.append(os.path.basename(p))
            except GLib.Error as e:
                failed.append(f"{raw}: {e.message[:80]}")
        msg = f"Moved {len(done)} item(s) to the trash."
        if failed:
            msg += " Not moved: " + "; ".join(failed[:10])
        if not done and failed:
            return Result.error(msg)
        return Result.text(msg)


# ---------------------------------------------------------------------------- helpers

def send_notification(title: str, body: str = "", *, urgency: int = 1, sound: str | None = None,
                      icon: str = "kristall-assistant", app_name: str = "Kristall") -> int:
    hints = {"urgency": dbus.Var("y", urgency), "desktop-entry": dbus.Var("s", "kristall-assistant")}
    if sound:
        hints["sound-name"] = dbus.Var("s", sound)
    return dbus.session().call("org.freedesktop.Notifications", "/org/freedesktop/Notifications",
                               "org.freedesktop.Notifications", "Notify", "susssasa{sv}i",
                               (app_name, 0, icon, title, body, [], hints, -1))[0]


def _looks_like_document(path: str) -> bool:
    return os.path.splitext(path)[1].lower() in {".txt", ".md", ".pdf", ".png", ".jpg", ".jpeg", ".odt", ".docx",
                                                  ".xlsx", ".csv", ".html", ".mp3", ".mp4", ".mkv", ".py", ".json"}


def _mime_of(path: str) -> str:
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        info = Gio.File.new_for_path(path).query_info("standard::content-type", Gio.FileQueryInfoFlags.NONE, None)
        return info.get_content_type() or "application/octet-stream"
    except Exception:
        import mimetypes
        return mimetypes.guess_type(path)[0] or "application/octet-stream"


def _gio_open(uri: str) -> bool:
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio
        return bool(Gio.AppInfo.launch_default_for_uri(uri, None))
    except Exception:
        return False


def _saved_wifi(bus) -> dict[str, str]:
    out: dict[str, str] = {}
    NM = "org.freedesktop.NetworkManager"
    try:
        conns = bus.call(NM, "/org/freedesktop/NetworkManager/Settings", f"{NM}.Settings", "ListConnections")[0]
    except dbus.DBusError:
        return out
    for c in conns:
        try:
            s = bus.call(NM, c, f"{NM}.Settings.Connection", "GetSettings")[0]
        except dbus.DBusError:
            continue
        w = s.get("802-11-wireless") or {}
        ssid = w.get("ssid")
        if ssid:
            out[bytes(ssid).decode("utf-8", "replace")] = c
    return out


def _work_area(h: Hands, win: dict) -> tuple[float, float, float, float]:
    outs = h.bridge.outputs or []
    name = win.get("output")
    pick = next((o for o in outs if o.get("name") == name), outs[0] if outs else None)
    if pick:
        # The bridge contract has no work area (screen minus menu bar and Dock) yet; use it if a
        # later version adds `workArea`, else the whole output (KWin keeps windows off the bar).
        o = pick.get("workArea") if isinstance(pick.get("workArea"), dict) else pick
        return float(o["x"]), float(o["y"]), float(o["w"]), float(o["h"])
    return 0.0, 0.0, float(win.get("w", 1280)), float(win.get("h", 800))


def _place(b, win: dict, x: float, y: float, w: float, h: float) -> None:
    if win.get("maximized"):
        b.request("window.setMaximized", {"id": win["id"], "value": False})
    if win.get("minimized"):
        b.request("window.setMinimized", {"id": win["id"], "value": False})
    b.request("window.setGeometry", {"id": win["id"], "x": round(x), "y": round(y), "w": round(w), "h": round(h)})
