# SPDX-License-Identifier: GPL-3.0-or-later
"""Permission policy: decides, for each tool call the model wants to make,
whether it runs, whether the owner is asked first, or whether it is refused.

Principle (from the owner's brief): read-only and reversible actions run
without asking.  Anything destructive, irreversible, costing money, sending
something on the owner's behalf, running with elevated rights or touching
credentials produces a permission request.  A few things are never allowed
(the owner's Claude credentials, our own permission store).

The policy is pure: ``Policy.evaluate`` takes the tool name and input and
returns a ``Decision``; persistence of "always allow" grants lives in
``GrantStore``.  The daemon asks the owner when the verdict is ``ask``.
"""
from __future__ import annotations

import fnmatch
import json
import logging
import os
import tempfile
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from . import shell

log = logging.getLogger("kristall.policy")

# category -> (verdict, may the owner grant "always")
CATEGORIES: dict[str, tuple[str, bool]] = {
    "read":           ("allow", True),
    "reversible":     ("allow", True),
    "files.modify":   ("ask", True),
    "system.config":  ("ask", True),
    "processes.stop": ("ask", True),
    "system.power":   ("ask", True),
    "apps.install":   ("ask", True),
    "files.delete":   ("ask", True),
    "shell.run":      ("ask", True),     # granted per program
    "tool.use":       ("ask", True),     # undeclared MCP tool, granted per tool
    "send":           ("ask", False),
    "purchase":       ("ask", False),
    "elevated":       ("ask", False),
    "credentials":    ("ask", False),
    "deny":           ("deny", False),
}
ORDER = shell.ORDER[:]
ORDER.insert(ORDER.index("shell.run") + 1, "tool.use")
RANK = {c: i for i, c in enumerate(ORDER)}


def worst(a: str, b: str) -> str:
    return a if RANK[a] >= RANK[b] else b


@dataclass
class Decision:
    verdict: str                     # "allow" | "ask" | "deny"
    category: str
    scope: str                       # key for an "always" grant
    can_always: bool
    action: dict[str, str]           # owner-facing infinitive phrase {"de","en"}
    question: dict[str, str]         # "Darf ich …?" {"de","en"}
    technical: str                   # what exactly runs (shown under "Details")
    reason: str = ""                 # log only
    granted: bool = False            # allowed because of an earlier "always"


# --------------------------------------------------------------------------- paths

def _home() -> str:
    return os.path.expanduser("~")


CLAUDE_SECRET_GLOBS = [
    "~/.claude/.credentials.json", "~/.claude.json", "~/.claude.json.backup*",
    "~/.claude/**", "~/.config/claude/**",
]
CREDENTIAL_GLOBS = [
    "~/.ssh/**", "~/.gnupg/**", "~/.local/share/keyrings/**", "~/.local/share/kwalletd/**",
    "~/.password-store/**", "~/.netrc", "~/.git-credentials", "~/.config/gh/hosts.yml",
    "~/.docker/config.json", "~/.aws/**", "~/.kube/**", "~/.config/rclone/rclone.conf",
    "**/logins.json", "**/key4.db", "**/cookies.sqlite", "**/Login Data*", "**/Cookies",
    "**/id_rsa*", "**/id_ed25519*", "**/id_ecdsa*", "**/*.pem", "**/*.key", "**/*.p12", "**/*.pfx",
    "**/.env", "**/.env.*", "/etc/shadow", "/etc/gshadow", "/etc/sudoers*",
    "~/.var/app/*/.mozilla/**/logins.json", "~/.var/app/*/config/*/Login Data*",
    "~/.config/Bitwarden/**", "~/.config/KeePassXC/**", "**/*.kdbx",
]
SYSTEM_CONFIG_GLOBS = [
    "~/.bashrc", "~/.bash_profile", "~/.profile", "~/.zshrc", "~/.config/autostart/**",
    "~/.config/systemd/**", "~/.config/environment.d/**", "~/.local/share/applications/**",
    "~/.config/kwinrc", "~/.config/kdeglobals", "~/.config/plasma*", "~/.pam_environment",
    "~/.xprofile", "~/.config/fish/**", "~/.local/bin/**",
]


def _expand(g: str) -> str:
    return os.path.expanduser(g)


def _match(path: str, globs: list[str]) -> bool:
    for g in globs:
        pat = _expand(g)
        if fnmatch.fnmatch(path, pat):
            return True
        if pat.endswith("/**") and (path == pat[:-3] or path.startswith(pat[:-2])):
            return True
        if pat.startswith("**/") and fnmatch.fnmatch(os.path.basename(path), pat[3:]):
            return True
    return False


@dataclass
class PolicyPaths:
    workspace: str
    protected: list[str] = field(default_factory=list)   # our own store files: never writable by the model


def norm_path(p: str, cwd: str) -> str:
    p = os.path.expanduser(str(p or ""))
    if not os.path.isabs(p):
        p = os.path.join(cwd, p)
    return os.path.normpath(p)


def path_category(path: str, write: bool, pp: PolicyPaths) -> str:
    """Category of reading/writing one path.

    Symbolic links are followed as well: a link in the workspace that points at ~/.bashrc must not
    turn a write to ~/.bashrc into a "reversible" one. The stricter of the two answers wins.
    """
    literal = _path_category_literal(path, write, pp)
    try:
        real = os.path.realpath(path)
    except (OSError, ValueError):
        return literal
    if real == path:
        return literal
    return worst(literal, _path_category_literal(real, write, pp))


def _path_category_literal(path: str, write: bool, pp: PolicyPaths) -> str:
    home = _home()
    if _match(path, CLAUDE_SECRET_GLOBS):
        return "deny"
    for prot in pp.protected:
        if path == prot or path.startswith(prot.rstrip("/") + "/"):
            return "deny" if write else "read"
    if _match(path, CREDENTIAL_GLOBS):
        return "credentials"
    if not write:
        return "read"
    ws = pp.workspace.rstrip("/")
    if path == ws or path.startswith(ws + "/"):
        return "reversible"
    if _match(path, SYSTEM_CONFIG_GLOBS):
        return "system.config"
    if not (path == home or path.startswith(home + "/")):
        return "elevated"
    rel = path[len(home) + 1:]
    if rel.startswith("."):
        return "system.config"
    return "files.modify" if os.path.lexists(path) else "reversible"


# --------------------------------------------------------------------------- grants

class GrantStore:
    """"Always allow this kind of thing" grants, persisted as JSON (mode 0600)."""

    def __init__(self, path: Path | None):
        self.path = path
        self._lock = threading.Lock()
        self._grants: dict[str, dict[str, Any]] = {}
        self.load()

    def load(self) -> None:
        if not self.path:
            return
        try:
            with open(self.path, encoding="utf-8") as f:
                d = json.load(f)
            self._grants = {k: v for k, v in (d.get("always") or {}).items() if isinstance(v, dict)}
        except FileNotFoundError:
            self._grants = {}
        except (OSError, ValueError) as e:
            log.warning("ignoring unreadable grants file: %s", e)
            self._grants = {}

    def has(self, scope: str) -> bool:
        return scope in self._grants

    def add(self, scope: str, label: str = "") -> None:
        import time
        with self._lock:
            self._grants[scope] = {"since": int(time.time()), "label": label}
            self._save()

    def remove(self, scope: str) -> None:
        with self._lock:
            self._grants.pop(scope, None)
            self._save()

    def all(self) -> dict[str, dict[str, Any]]:
        return dict(self._grants)

    def _save(self) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, prefix=".permissions.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "always": self._grants}, f, indent=1, ensure_ascii=False)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise


# --------------------------------------------------------------------------- wording

def _q(s: str) -> str:
    return f"„{s}“"


def _qe(s: str) -> str:
    return f"“{s}”"


def _name(p: str) -> str:
    return os.path.basename(p.rstrip("/")) or p


def _things(paths: list[str], lang: str) -> str:
    paths = [p for p in paths if p]
    if not paths:
        return "Dateien" if lang == "de" else "files"
    if len(paths) == 1:
        n = _name(paths[0])
        return f"{_q(n)}" if lang == "de" else _qe(n)
    if any("*" in p for p in paths):
        return "mehrere Dateien" if lang == "de" else "several files"
    return f"{len(paths)} Dateien" if lang == "de" else f"{len(paths)} files"


def describe(category: str, *, program: str = "", targets: list[str] | None = None,
             tool_label: str = "", server: str = "") -> dict[str, str]:
    """Owner-facing infinitive phrase for an action, e.g. 'die Datei „a.txt“ löschen'."""
    t = targets or []
    de_t, en_t = _things(t, "de"), _things(t, "en")
    if category == "files.delete":
        return {"de": f"{de_t} endgültig löschen", "en": f"permanently delete {en_t}"}
    if category == "files.modify":
        return {"de": f"{de_t} verändern oder überschreiben", "en": f"change or overwrite {en_t}"}
    if category == "system.config":
        return {"de": "Systemeinstellungen in deinen Konfigurationsdateien ändern",
                "en": "change system settings in your configuration files"}
    if category == "processes.stop":
        return {"de": "ein laufendes Programm beenden", "en": "stop a running program"}
    if category == "system.power":
        return {"de": "den Computer ausschalten, neu starten oder abmelden",
                "en": "shut down, restart or log out of the computer"}
    if category == "apps.install":
        return {"de": "Software installieren oder entfernen", "en": "install or remove software"}
    if category == "send":
        return {"de": "etwas in deinem Namen senden", "en": "send something on your behalf"}
    if category == "purchase":
        return {"de": "etwas kaufen oder bezahlen", "en": "buy or pay for something"}
    if category == "elevated":
        return {"de": "einen Befehl mit Administratorrechten ausführen",
                "en": "run a command with administrator rights"}
    if category == "credentials":
        return {"de": "auf Passwörter oder Zugangsdaten zugreifen",
                "en": "access passwords or sign-in data"}
    if category == "shell.run":
        if program:
            return {"de": f"das Programm {_q(program)} ausführen", "en": f"run the program {_qe(program)}"}
        return {"de": "einen Befehl ausführen", "en": "run a command"}
    if category == "tool.use":
        lbl = tool_label or "ein Werkzeug"
        return {"de": f"{_q(lbl)} verwenden", "en": f"use {_qe(tool_label or 'a tool')}"}
    if category == "deny":
        return {"de": "auf geschützte Daten zugreifen", "en": "access protected data"}
    return {"de": "das tun", "en": "do this"}


def question_for(action: dict[str, str]) -> dict[str, str]:
    return {"de": f"Darf ich {action['de']}?", "en": f"May I {action['en']}?"}


# --------------------------------------------------------------------------- policy

@dataclass
class ToolDecl:
    """Policy declaration a tool server makes in its mcp.d drop-in."""
    risk: str = "ask"                                  # category name, or "ask" (=tool.use)
    label: dict[str, str] = field(default_factory=dict)  # {"de","en"} short name of the tool


class Policy:
    def __init__(self, paths: PolicyPaths, grants: GrantStore,
                 tool_decls: dict[str, dict[str, ToolDecl]] | None = None):
        self.paths = paths
        self.grants = grants
        self.tool_decls = tool_decls or {}      # server -> tool -> decl

    # -- entry point ----------------------------------------------------------
    def evaluate(self, tool: str, inp: dict[str, Any] | None) -> Decision:
        inp = inp or {}
        try:
            d = self._evaluate(tool, inp)
        except Exception as e:                       # never fail open
            log.exception("policy error for %s", tool)
            d = self._mk("shell.run" if tool == "Bash" else "tool.use", f"error:{tool}",
                         describe("tool.use", tool_label=tool), str(inp)[:500], f"policy error {e}")
        # Model-declared risk can only make things stricter.
        declared = inp.get("risk") if isinstance(inp.get("risk"), str) else None
        if declared in CATEGORIES and RANK.get(declared, -1) > RANK[d.category]:
            act = describe(declared)
            d = self._mk(declared, f"{declared}", act, d.technical, f"model declared risk {declared}")
        if d.verdict == "ask" and d.can_always and self.grants.has(d.scope):
            d.verdict = "allow"
            d.granted = True
        return d

    def _mk(self, category: str, scope: str, action: dict[str, str], technical: str, reason: str = "") -> Decision:
        verdict, can_always = CATEGORIES[category]
        return Decision(verdict, category, scope, can_always, action, question_for(action),
                        technical, reason)

    def _evaluate(self, tool: str, inp: dict[str, Any]) -> Decision:
        cwd = self.paths.workspace
        if tool in ("Read", "NotebookRead"):
            p = norm_path(inp.get("file_path") or inp.get("notebook_path") or "", cwd)
            cat = path_category(p, False, self.paths)
            return self._mk(cat, cat, describe(cat, targets=[p]), f"Lesen: {p}", "read")
        if tool in ("Glob", "Grep", "LS"):
            p = norm_path(inp.get("path") or cwd, cwd)
            pattern = str(inp.get("pattern") or "")
            cat = path_category(p, False, self.paths)
            if cat == "read" and _match(os.path.join(p, pattern), CREDENTIAL_GLOBS):
                cat = "credentials"
            return self._mk(cat, cat, describe(cat, targets=[p]), f"{tool}: {pattern} in {p}")
        if tool in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
            p = norm_path(inp.get("file_path") or inp.get("notebook_path") or "", cwd)
            cat = path_category(p, True, self.paths)
            return self._mk(cat, cat, describe(cat, targets=[p]), f"{tool}: {p}")
        if tool == "Bash":
            return self._bash(str(inp.get("command") or ""))
        if tool == "WebFetch" and _url_carries_data(str(inp.get("url") or "")):
            # A long query or path can smuggle the owner's data out to any site: ask first.
            url = str(inp.get("url") or "")
            return self._mk("send", "send", describe("send"), f"WebFetch: {url[:300]}",
                            "url carries data")
        if tool in ("WebSearch", "WebFetch", "TodoWrite", "ToolSearch"):
            tech = inp.get("query") or inp.get("url") or tool
            return self._mk("read", "read", describe("read"), f"{tool}: {tech}")
        if tool.startswith("mcp__"):
            return self._mcp(tool, inp)
        # Anything else (subagents, notebooks, unknown future tools): ask.
        return self._mk("tool.use", f"tool:{tool}", describe("tool.use", tool_label=tool),
                        f"{tool}: {json.dumps(inp, ensure_ascii=False)[:400]}")

    def _bash(self, command: str) -> Decision:
        cwd = self.paths.workspace
        an = shell.analyze(command, cwd)
        cat = an.category
        # Any token that names a sensitive path raises the category.
        toks = shell._tokenize(command) or command.split()
        for t in toks:
            if "/" in t or t.startswith("~") or t.startswith("."):
                p = norm_path(t, cwd)
                pc = path_category(p, False, self.paths)
                if pc in ("credentials", "deny"):
                    cat = worst(cat, pc)
        # Writing into our protected store via any command is refused.
        main = an.main
        for f in an.findings:
            if f.category not in ("read",):
                for t in f.targets:
                    if path_category(norm_path(t, cwd), True, self.paths) == "deny":
                        cat = "deny"
        if cat == "shell.run":
            prog = main.program or "?"
            scope = f"shell.run:{prog}"
            act = describe("shell.run", program=prog)
        elif cat in ("files.delete", "files.modify"):
            tf = next((f for f in an.findings if f.category == cat), main)
            scope = cat
            act = describe(cat, targets=tf.targets)
        else:
            scope = cat
            act = describe(cat, program=main.program, targets=main.targets)
        return self._mk(cat, scope, act, command, f"bash programs={an.programs}")

    def _mcp(self, tool: str, inp: dict[str, Any]) -> Decision:
        parts = tool.split("__", 2)
        server = parts[1] if len(parts) > 1 else ""
        name = parts[2] if len(parts) > 2 else ""
        tech = f"{server}.{name} {json.dumps({k: v for k, v in inp.items() if k != 'risk'}, ensure_ascii=False)[:400]}"
        if server == "kristall":            # our own in-process tools (memory)
            return self._mk("reversible", "reversible", describe("reversible"), tech)
        decl = self.tool_decls.get(server, {}).get(name) or self.tool_decls.get(server, {}).get("*")
        label = (decl.label.get("de") if decl else "") or name
        if decl and decl.risk in CATEGORIES and decl.risk != "deny":
            cat = decl.risk
            scope = f"mcp:{server}:{name}" if cat in ("tool.use", "shell.run") else cat
            act = describe(cat, tool_label=label, targets=_paths_in(inp))
            if cat == "tool.use":
                act = {"de": describe(cat, tool_label=label)["de"],
                       "en": describe(cat, tool_label=(decl.label.get("en") if decl else "") or name)["en"]}
            return self._mk(cat, scope, act, tech)
        if decl and decl.risk == "deny":
            return self._mk("deny", "deny", describe("deny"), tech)
        return self._mk("tool.use", f"mcp:{server}:{name}",
                        describe("tool.use", tool_label=label), tech)


def _url_carries_data(url: str) -> bool:
    """True when a URL is long enough in its query, fragment or a path segment to carry data."""
    from urllib.parse import urlsplit
    try:
        u = urlsplit(url)
    except ValueError:
        return True
    if len(u.query) + len(u.fragment) > 200:
        return True
    return any(len(seg) > 120 for seg in u.path.split("/"))


def _paths_in(inp: dict[str, Any]) -> list[str]:
    out = []
    for k in ("path", "paths", "file", "files", "target"):
        v = inp.get(k)
        if isinstance(v, str):
            out.append(v)
        elif isinstance(v, list):
            out += [x for x in v if isinstance(x, str)]
    return out
