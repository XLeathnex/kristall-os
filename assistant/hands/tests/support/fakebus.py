# SPDX-License-Identifier: GPL-3.0-or-later
"""In-memory D-Bus stand-in: services are dicts of objects with properties and method handlers."""
from __future__ import annotations

from kristall_hands.dbus import DBusError, Var


def plain(v):
    if isinstance(v, Var):
        return plain(v.value)
    if isinstance(v, (list, tuple)):
        return type(v)(plain(x) for x in v)
    if isinstance(v, dict):
        return {k: plain(x) for k, x in v.items()}
    return v


class FakeBus:
    def __init__(self):
        # (name, path, iface) -> {"props": {...}, "methods": {name: fn(*args)}}
        self.objects: dict[tuple, dict] = {}
        self.calls: list[tuple] = []

    def add(self, name, path, iface, props=None, **methods):
        self.objects[(name, path, iface)] = {"props": dict(props or {}), "methods": methods}
        return self.objects[(name, path, iface)]

    def _obj(self, name, path, iface):
        if not any(k[0] == name for k in self.objects):
            raise DBusError("org.freedesktop.DBus.Error.ServiceUnknown", f"The name {name} was not provided")
        o = self.objects.get((name, path, iface))
        if o is None:
            raise DBusError("org.freedesktop.DBus.Error.UnknownObject", f"{path} {iface}")
        return o

    def call(self, name, path, iface, method, sig=None, args=(), reply_sig=None, timeout_ms=5000):
        args = tuple(plain(a) for a in args)
        self.calls.append((name, path, iface, method, args))
        if iface == "org.freedesktop.DBus.Properties":
            o = self._obj(name, path, args[0])
            if method == "Get":
                if args[1] not in o["props"]:
                    raise DBusError("org.freedesktop.DBus.Error.InvalidArgs", "no such property")
                return (o["props"][args[1]],)
            if method == "GetAll":
                return (dict(o["props"]),)
            if method == "Set":
                hook = o["methods"].get("_set")
                if hook:
                    hook(args[1], args[2])
                o["props"][args[1]] = args[2]
                return ()
        o = self._obj(name, path, iface)
        fn = o["methods"].get(method)
        if fn is None:
            raise DBusError("org.freedesktop.DBus.Error.UnknownMethod", method)
        r = fn(*args)
        return r if isinstance(r, tuple) else ((r,) if r is not None else ())

    def get(self, name, path, iface, prop):
        return self.call(name, path, "org.freedesktop.DBus.Properties", "Get", "ss", (iface, prop))[0]

    def get_all(self, name, path, iface):
        return self.call(name, path, "org.freedesktop.DBus.Properties", "GetAll", "s", (iface,))[0]

    def set(self, name, path, iface, prop, sig, value):
        self.call(name, path, "org.freedesktop.DBus.Properties", "Set", "ssv", (iface, prop, value))

    def has_owner(self, name):
        return any(k[0] == name for k in self.objects)

    def list_names(self):
        return sorted({k[0] for k in self.objects})

    def activatable(self, name):
        return False

    def emit(self, *a):
        self.calls.append(("signal",) + a)

    def methods(self, method=None):
        return [c for c in self.calls if method is None or c[3] == method]
