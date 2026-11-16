# SPDX-License-Identifier: GPL-3.0-or-later
"""Thin synchronous D-Bus access through GLib's GDBus (python3-gobject).

Every system interface hands uses goes through ``Bus`` so tests can replace it with a fake.
Values for ``v`` slots are passed as ``Var(signature, value)``.
"""
from __future__ import annotations

import threading
from typing import Any


class DBusError(Exception):
    def __init__(self, name: str, message: str):
        super().__init__(f"{name}: {message}")
        self.name = name
        self.message = message


class Var:
    """A value for a D-Bus variant slot."""

    def __init__(self, sig: str, value: Any):
        self.sig, self.value = sig, value

    def __repr__(self):
        return f"Var({self.sig!r}, {self.value!r})"


def _to_variant(GLib, v):
    if isinstance(v, Var):
        return GLib.Variant("v", GLib.Variant(v.sig, _plain(GLib, v.value)))
    return v


def _plain(GLib, v):
    """Recursively turn Var objects into GLib.Variant for 'v' positions."""
    if isinstance(v, Var):
        return GLib.Variant(v.sig, _plain(GLib, v.value))
    if isinstance(v, tuple):
        return tuple(_plain(GLib, x) for x in v)
    if isinstance(v, list):
        return [_plain(GLib, x) for x in v]
    if isinstance(v, dict):
        return {k: _plain(GLib, x) for k, x in v.items()}
    return v


class Bus:
    """One connection (session or system), created lazily."""

    def __init__(self, kind: str = "session"):
        self.kind = kind
        self._conn = None
        self._lock = threading.Lock()

    def _connection(self):
        if self._conn is None:
            with self._lock:
                if self._conn is None:
                    try:
                        import gi
                        gi.require_version("Gio", "2.0")
                        from gi.repository import Gio
                    except (ImportError, ValueError) as e:
                        raise DBusError("org.kristall.NoGio", f"python3-gobject is not available: {e}")
                    try:
                        self._conn = Gio.bus_get_sync(Gio.BusType.SESSION if self.kind == "session" else Gio.BusType.SYSTEM, None)
                    except Exception as e:  # GLib.Error
                        raise DBusError("org.kristall.NoBus", str(e))
        return self._conn

    def call(self, name: str, path: str, iface: str, method: str, sig: str | None = None,
             args: tuple = (), reply_sig: str | None = None, timeout_ms: int = 5000):
        from gi.repository import GLib, Gio
        conn = self._connection()
        params = GLib.Variant(f"({sig})", _plain(GLib, tuple(args))) if sig else None
        try:
            res = conn.call_sync(name, path, iface, method, params,
                                 GLib.VariantType(f"({reply_sig})") if reply_sig else None,
                                 Gio.DBusCallFlags.NONE, timeout_ms, None)
        except GLib.Error as e:
            remote = Gio.DBusError.get_remote_error(e) or "org.freedesktop.DBus.Error.Failed"
            msg = e.message
            if Gio.DBusError.is_remote_error(e):
                msg = msg.split(": ", 1)[-1] if ": " in msg else msg
            raise DBusError(remote, msg)
        return res.unpack() if res is not None else ()

    def get(self, name: str, path: str, iface: str, prop: str):
        return self.call(name, path, "org.freedesktop.DBus.Properties", "Get", "ss", (iface, prop))[0]

    def get_all(self, name: str, path: str, iface: str) -> dict:
        return self.call(name, path, "org.freedesktop.DBus.Properties", "GetAll", "s", (iface,))[0]

    def set(self, name: str, path: str, iface: str, prop: str, sig: str, value: Any) -> None:
        self.call(name, path, "org.freedesktop.DBus.Properties", "Set", "ssv", (iface, prop, Var(sig, value)))

    def has_owner(self, name: str) -> bool:
        try:
            return bool(self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                                  "NameHasOwner", "s", (name,))[0])
        except DBusError:
            return False

    def list_names(self) -> list[str]:
        return list(self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListNames")[0])

    def activatable(self, name: str) -> bool:
        try:
            names = self.call("org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus",
                              "ListActivatableNames")[0]
        except DBusError:
            return False
        return name in names

    def emit(self, path: str, iface: str, signal: str, sig: str, args: tuple) -> None:
        from gi.repository import GLib
        conn = self._connection()
        try:
            conn.emit_signal(None, path, iface, signal, GLib.Variant(f"({sig})", _plain(GLib, tuple(args))))
        except GLib.Error as e:
            raise DBusError("org.freedesktop.DBus.Error.Failed", e.message)


_buses: dict[str, Bus] = {}


def session() -> Bus:
    return _buses.setdefault("session", Bus("session"))


def system() -> Bus:
    return _buses.setdefault("system", Bus("system"))


def install(kind: str, bus) -> None:
    """Tests: replace a bus with a fake."""
    _buses[kind] = bus
