# SPDX-License-Identifier: GPL-3.0-or-later
"""Installed applications: index of desktop entries + the Kristall app manifest, fuzzy lookup
by German or English name, and launching each app in its own systemd scope (so restarting the
assistant never takes the owner's apps with it)."""
from __future__ import annotations

import difflib
import json
import os
import re
import threading
import unicodedata
import uuid
from dataclasses import dataclass, field

from . import dbus, log

MANIFEST = "/usr/share/kristall/apps/apps.json"

FILLER = {
    "öffne", "öffnen", "oeffne", "offne", "mach", "mache", "machen", "auf", "starte", "starten", "start",
    "open", "launch", "run", "bitte", "please", "den", "die", "das", "dem", "der", "des", "ein", "eine",
    "einen", "the", "a", "an", "app", "apps", "programm", "program", "anwendung", "application", "mal",
    "doch", "mir", "me", "my", "mein", "meine", "meinen", "up", "kurz", "schnell", "zeig", "zeige",
    "show", "hol", "hole", "bring", "nach", "vorne", "front", "wieder", "again", "for", "für", "fuer",
}

# Generic words for an app role → how to find the app that plays it.
ROLES: dict[str, tuple[str, str]] = {
    # word: (kind, value) kind "mime"/"scheme" → default handler; "id" → manifest id
    "browser": ("scheme", "https"), "webbrowser": ("scheme", "https"), "internet": ("scheme", "https"),
    "web": ("scheme", "https"), "internetbrowser": ("scheme", "https"),
    "mail": ("scheme", "mailto"), "email": ("scheme", "mailto"), "e-mail": ("scheme", "mailto"),
    "emails": ("scheme", "mailto"), "mails": ("scheme", "mailto"),
    "dateien": ("id", "files"), "dateimanager": ("id", "files"), "explorer": ("id", "files"),
    "finder": ("id", "files"), "files": ("id", "files"), "ordner": ("id", "files"), "file manager": ("id", "files"),
    "rechner": ("id", "calculator"), "taschenrechner": ("id", "calculator"), "calculator": ("id", "calculator"),
    "einstellungen": ("id", "settings"), "systemeinstellungen": ("id", "settings"), "settings": ("id", "settings"),
    "system settings": ("id", "settings"),
    "terminal": ("id", "terminal"), "konsole": ("id", "terminal"), "kommandozeile": ("id", "terminal"),
    "editor": ("id", "text-editor"), "texteditor": ("id", "text-editor"), "text editor": ("id", "text-editor"),
    "musik": ("id", "music"), "music": ("id", "music"),
    "video": ("id", "video"), "videos": ("id", "video"), "filme": ("id", "video"), "film": ("id", "video"),
    "bilder": ("id", "images"), "fotos": ("id", "images"), "photos": ("id", "images"), "bildbetrachter": ("id", "images"),
    "pdf": ("id", "documents"), "pdfs": ("id", "documents"),
    "vscode": ("id", "code"), "vs code": ("id", "code"), "visual studio": ("id", "code"),
    "app store": ("id", "app-center"), "appstore": ("id", "app-center"), "app center": ("id", "app-center"),
    "app-center": ("id", "app-center"), "software": ("id", "app-center"),
    "bildschirmfoto": ("id", "screenshot"), "screenshot": ("id", "screenshot"),
    "systemmonitor": ("id", "system-monitor"), "taskmanager": ("id", "system-monitor"),
    "task manager": ("id", "system-monitor"), "aktivitätsanzeige": ("id", "system-monitor"),
}


def fold(s: str) -> str:
    s = s.lower().replace("ß", "ss")
    s = s.replace("ä", "a").replace("ö", "o").replace("ü", "u")
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = re.sub(r"[^a-z0-9+]+", " ", s)
    return " ".join(s.split())


FILLER_FOLDED = {fold(w) for w in FILLER}
ROLES_FOLDED = {fold(k): v for k, v in ROLES.items()}


def clean_query(q: str) -> str:
    toks = [t for t in fold(q).split() if t not in FILLER_FOLDED]
    return " ".join(toks)


@dataclass
class App:
    desktop_id: str                    # "org.kde.kate.desktop"
    path: str = ""
    name: str = ""
    names: list[str] = field(default_factory=list)       # all names (Name, Name[de], manifest names)
    generic: list[str] = field(default_factory=list)     # GenericName, Keywords
    no_display: bool = False
    manifest_id: str | None = None
    installed: bool = True
    wm_class: str = ""
    exec_name: str = ""
    display: dict = field(default_factory=dict)          # {"de": "...", "en": "..."}

    @property
    def stem(self) -> str:
        return self.desktop_id[:-8] if self.desktop_id.endswith(".desktop") else self.desktop_id

    def title(self, lang: str = "de") -> str:
        return self.display.get(lang) or self.display.get("en") or self.name or self.stem


def data_dirs() -> list[str]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    dirs = [home] + [d for d in (os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share").split(":") if d]
    for extra in (os.path.join(home, "flatpak/exports/share"), "/var/lib/flatpak/exports/share"):
        if extra not in dirs:
            dirs.append(extra)
    return dirs


def parse_desktop(path: str) -> dict[str, str] | None:
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read(256 * 1024)
    except OSError:
        return None
    out: dict[str, str] = {}
    section = None
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("["):
            section = line
            continue
        if section != "[Desktop Entry]" or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out.setdefault(k.strip(), v.strip())
    return out


def _loc(d: dict, key: str, langs: tuple[str, ...] = ("de_DE", "de", "en_US", "en_GB", "en")) -> list[str]:
    vals = []
    for k in [key] + [f"{key}[{l}]" for l in langs]:
        if d.get(k):
            vals.append(d[k])
    return vals


class AppIndex:
    def __init__(self, manifest_path: str | None = None, dirs: list[str] | None = None):
        self.manifest_path = manifest_path or os.environ.get("KRISTALL_APPS_MANIFEST") or MANIFEST
        self._dirs = dirs
        self._apps: dict[str, App] | None = None
        self._stamp: tuple = ()
        self.default_for = self._gio_default    # (kind, value) -> desktop id or None; tests replace

    # ------------------------------------------------------------------ index
    def dirs(self) -> list[str]:
        return [os.path.join(d, "applications") for d in (self._dirs or data_dirs())]

    def _stamp_now(self) -> tuple:
        st = []
        for d in self.dirs() + [self.manifest_path]:
            try:
                st.append(os.stat(d).st_mtime_ns)
            except OSError:
                st.append(0)
        return tuple(st)

    def apps(self) -> dict[str, App]:
        stamp = self._stamp_now()
        if self._apps is not None and stamp == self._stamp:
            return self._apps
        apps: dict[str, App] = {}
        for base in self.dirs():
            if not os.path.isdir(base):
                continue
            for root, _dirs, files in os.walk(base):
                for fn in files:
                    if not fn.endswith(".desktop"):
                        continue
                    path = os.path.join(root, fn)
                    did = os.path.relpath(path, base).replace("/", "-")
                    if did in apps:
                        continue                     # earlier directories win
                    d = parse_desktop(path)
                    if d is None or d.get("Type", "Application") != "Application":
                        continue
                    if d.get("Hidden", "").lower() == "true":
                        apps[did] = App(did, path, installed=False)   # masks lower entries
                        continue
                    names = _loc(d, "Name")
                    generic = _loc(d, "GenericName") + [k for kw in _loc(d, "Keywords") for k in kw.split(";") if k]
                    exec_name = os.path.basename((d.get("Exec") or "").split(" ")[0]) if d.get("Exec") else ""
                    apps[did] = App(did, path, names[0] if names else did, names, generic,
                                    d.get("NoDisplay", "").lower() == "true", wm_class=d.get("StartupWMClass", ""),
                                    exec_name=exec_name)
        apps = {k: v for k, v in apps.items() if v.installed}
        # Manifest: our own display names; also lists default apps that are not installed (yet).
        try:
            with open(self.manifest_path, encoding="utf-8") as f:
                manifest = json.load(f)
        except (OSError, ValueError):
            manifest = {}
        for m in manifest.get("apps") or []:
            did = m.get("desktop_id")
            if not did:
                continue
            names = [n for n in (m.get("name") or {}).values() if n]
            a = apps.get(did)
            if a is None:
                a = App(did, "", names[0] if names else did, [], [], installed=False)
                apps[did] = a
            a.manifest_id = m.get("id")
            a.display = dict(m.get("name") or {})
            a.names = names + [n for n in a.names if n not in names]
            if m.get("show_in_apps") is False:
                a.no_display = True
        self._apps, self._stamp = apps, stamp
        return apps

    def by_manifest(self, mid: str) -> App | None:
        for a in self.apps().values():
            if a.manifest_id == mid:
                return a
        return None

    # ------------------------------------------------------------------ lookup
    def find(self, query: str, limit: int = 5) -> list[tuple[float, App]]:
        q = clean_query(query)
        if not q:
            return []
        apps = self.apps()
        if q.endswith(".desktop") and q in apps:
            return [(200.0, apps[q])]
        raw = query.strip()
        if raw in apps:
            return [(200.0, apps[raw])]
        if raw + ".desktop" in apps:
            return [(200.0, apps[raw + ".desktop"])]

        scored: list[tuple[float, App]] = []
        role = ROLES_FOLDED.get(q)
        role_app: App | None = None
        if role:
            kind, value = role
            if kind == "id":
                role_app = self.by_manifest(value)
            else:
                did = self.default_for(kind, value)
                role_app = apps.get(did) if did else None
        for a in apps.values():
            s = self._score(q, a)
            if role_app is a:
                s = max(s, 95.0)
            if s > 0:
                scored.append((s, a))
        scored.sort(key=lambda t: (-t[0], t[1].no_display, t[1].desktop_id))
        return scored[:limit]

    @staticmethod
    def _score(q: str, a: App) -> float:
        qt = q.split()
        best = 0.0
        primary = [fold(n) for n in a.names if n]
        secondary = [fold(n) for n in a.generic if n] + [fold(a.stem.split(".")[-1]), fold(a.stem), fold(a.exec_name)]
        for n in primary:
            if not n:
                continue
            nt = n.split()
            if q == n:
                best = max(best, 100)
            elif n.startswith(q + " ") or q.startswith(n + " ") or (n.startswith(q) and len(q) >= 3):
                best = max(best, 82)
            elif all(t in nt for t in qt):
                best = max(best, 78)
            elif len(q) >= 3 and q in n:
                best = max(best, 70)
            elif len(n) >= 4 and n in q:
                best = max(best, 68)
            else:
                r = difflib.SequenceMatcher(None, q, n).ratio()
                if r >= 0.75:
                    best = max(best, 50 + 25 * r)
        for n in secondary:
            if not n:
                continue
            if q == n:
                best = max(best, 88)
            elif len(q) >= 4 and (q in n.split() or (len(n) >= 4 and n.endswith(q))):
                best = max(best, 72)
            elif len(q) >= 4 and q in n:
                best = max(best, 60)
            else:
                r = difflib.SequenceMatcher(None, q, n).ratio()
                if r >= 0.85:
                    best = max(best, 45 + 20 * r)
        if best <= 0:
            return 0.0
        if a.no_display:
            best -= 25
        if a.manifest_id:
            best += 4
        if a.stem.startswith("kcm_") or a.stem.startswith("org.kde.kcm"):
            best -= 15
        if not a.installed:
            best -= 1
        return best

    @staticmethod
    def _gio_default(kind: str, value: str) -> str | None:
        try:
            import gi
            gi.require_version("Gio", "2.0")
            from gi.repository import Gio
            info = Gio.AppInfo.get_default_for_uri_scheme(value) if kind == "scheme" else \
                Gio.AppInfo.get_default_for_type(value, False)
            return info.get_id() if info else None
        except Exception:
            return None


# ---------------------------------------------------------------------------- launching

def _reap(pid: int) -> None:
    try:
        os.waitpid(pid, 0)
    except ChildProcessError:
        pass


def move_to_scope(pid: int, app_id: str) -> None:
    """Put a freshly started app into its own transient scope, like Plasma does, so it does not
    live (and die) in the assistant's service cgroup."""
    safe = re.sub(r"[^A-Za-z0-9_.-]", "_", app_id)[:80]
    unit = f"app-{safe}@{uuid.uuid4().hex[:12]}.scope"
    try:
        dbus.session().call("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                            "org.freedesktop.systemd1.Manager", "StartTransientUnit", "ssa(sv)a(sa(sv))",
                            (unit, "fail", [("PIDs", dbus.Var("au", [pid])),
                                            ("Description", dbus.Var("s", f"{app_id} (opened by the assistant)")),
                                            ("CollectMode", dbus.Var("s", "inactive-or-failed"))], []))
    except dbus.DBusError as e:
        log.info("could not move pid %s into a scope: %s", pid, e.message)


def launch(app: App, uris: list[str] | None = None, env: dict | None = None) -> list[int]:
    """Start a desktop entry (with optional URIs).  Returns the started pids (empty for
    D-Bus-activated apps).  Raises OSError on failure."""
    try:
        import gi
        gi.require_version("Gio", "2.0")
        from gi.repository import Gio, GLib
    except (ImportError, ValueError) as e:
        raise OSError(f"python3-gobject unavailable: {e}")
    info = Gio.DesktopAppInfo.new_from_filename(app.path) if app.path else Gio.DesktopAppInfo.new(app.desktop_id)
    if info is None:
        raise OSError(f"cannot load {app.desktop_id}")
    ctx = Gio.AppLaunchContext()
    for k, v in (env or {}).items():
        ctx.setenv(k, v)
    pids: list[int] = []

    def on_pid(_info, pid, *_):
        pids.append(pid)

    flags = GLib.SpawnFlags.SEARCH_PATH | GLib.SpawnFlags.DO_NOT_REAP_CHILD
    try:
        info.launch_uris_as_manager(list(uris or []), ctx, flags, None, None, on_pid, None)
    except GLib.Error as e:
        raise OSError(e.message)
    for pid in pids:
        threading.Thread(target=_reap, args=(pid,), daemon=True, name=f"reap-{pid}").start()
        move_to_scope(pid, app.stem)
    return pids
