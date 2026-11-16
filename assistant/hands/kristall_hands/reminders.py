# SPDX-License-Identifier: GPL-3.0-or-later
"""Timers, alarms and reminders that fire as notifications even when the assistant is not running.

Each one is a transient systemd user timer (``kristall-reminder-<id>.timer``) that runs
``kristall-hands fire <id>``; the list lives in ``~/.local/share/kristall/hands/reminders.json``.
Transient units vanish at logout, so ``kristall-hands-session.service`` re-arms them at login and
fires the ones that came due while the owner was away (marked as missed).  No process runs while
waiting.  A sleeping laptop does not wake up for them; they fire right after it resumes.
"""
from __future__ import annotations

import contextlib
import datetime as dt
import fcntl
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import time

from . import dbus, log
from .tooling import Context, HandsError, Registry, Result

KIND_TITLE = {"timer": {"de": "Timer", "en": "Timer"}, "alarm": {"de": "Wecker", "en": "Alarm"},
              "reminder": {"de": "Erinnerung", "en": "Reminder"}}


def store_path() -> str:
    base = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    return os.path.join(base, "kristall", "hands", "reminders.json")


@contextlib.contextmanager
def locked_store():
    path = store_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    lock = open(path + ".lock", "a")
    fcntl.flock(lock, fcntl.LOCK_EX)
    try:
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            data = {"version": 1, "items": []}
        if not isinstance(data.get("items"), list):
            data["items"] = []
        yield data
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=1)
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    finally:
        fcntl.flock(lock, fcntl.LOCK_UN)
        lock.close()


def self_command() -> list[str]:
    exe = os.environ.get("KRISTALL_HANDS_BIN")
    if exe:
        return [exe]
    for p in ("/usr/bin/kristall-hands",):
        if os.path.exists(p):
            return [p]
    pkg_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return [sys.executable, "-I", "-c", f"import sys; sys.path.insert(0, {pkg_parent!r}); "
                                          "from kristall_hands.__main__ import main; sys.exit(main())"]


def arm(item: dict) -> None:
    """Create the transient timer for one item (replacing an existing one)."""
    rid = item["id"]
    unit = f"kristall-reminder-{rid}"
    bus = dbus.session()
    try:
        bus.call("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
                 "StopUnit", "ss", (unit + ".timer", "replace"))
    except dbus.DBusError:
        pass
    when = dt.datetime.fromtimestamp(item["at"]).strftime("%Y-%m-%d %H:%M:%S")
    cmd = self_command() + ["fire", rid]
    bus.call("org.freedesktop.systemd1", "/org/freedesktop/systemd1", "org.freedesktop.systemd1.Manager",
             "StartTransientUnit", "ssa(sv)a(sa(sv))",
             (unit + ".timer", "replace",
              [("Description", dbus.Var("s", f"Kristall {item['kind']}: {item['text'][:60]}")),
               ("TimersCalendar", dbus.Var("a(ss)", [("OnCalendar", when)])),
               ("AccuracyUSec", dbus.Var("t", 1_000_000)),
               ("RemainAfterElapse", dbus.Var("b", False))],
              [(unit + ".service",
                [("Description", dbus.Var("s", f"Kristall {item['kind']}")),
                 ("Type", dbus.Var("s", "oneshot")),
                 ("ExecStart", dbus.Var("a(sasb)", [(cmd[0], cmd, False)]))])]))


def disarm(rid: str) -> None:
    try:
        dbus.session().call("org.freedesktop.systemd1", "/org/freedesktop/systemd1",
                            "org.freedesktop.systemd1.Manager", "StopUnit", "ss",
                            (f"kristall-reminder-{rid}.timer", "replace"))
    except dbus.DBusError:
        pass


def parse_when(at: str | None, in_seconds: int | None, now: dt.datetime | None = None) -> dt.datetime:
    now = now or dt.datetime.now()
    if in_seconds is not None:
        return now + dt.timedelta(seconds=int(in_seconds))
    if not at:
        raise HandsError("Say when: 'in_seconds' for a timer, or 'at' (e.g. '07:30' or '2026-11-16 09:00').")
    s = at.strip().replace("T", " ")
    m = re.fullmatch(r"(\d{1,2})[:.](\d{2})(?::(\d{2}))?", s)
    if m:
        t = now.replace(hour=int(m.group(1)), minute=int(m.group(2)), second=int(m.group(3) or 0), microsecond=0)
        if t <= now:
            t += dt.timedelta(days=1)
        return t
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            t = dt.datetime.strptime(s[:19], fmt)
            if fmt == "%Y-%m-%d":
                t = t.replace(hour=9)
            return t
        except ValueError:
            continue
    raise HandsError(f"I don't understand the time “{at[:40]}”. Use '07:30' or '2026-11-16 09:00'.")


def next_repeat(t: dt.datetime, repeat: str, now: dt.datetime) -> dt.datetime:
    while t <= now:
        t += dt.timedelta(days=1)
    if repeat == "weekdays":
        while t.weekday() >= 5:
            t += dt.timedelta(days=1)
    return t


def human_delta(seconds: float) -> str:
    seconds = int(max(0, seconds))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h} h {m} min"
    if m:
        return f"{m} min" + (f" {s} s" if s and m < 10 else "")
    return f"{s} s"


def register(reg: Registry, hands) -> None:
    @reg.tool("timer",
              "Timers, alarms and reminders that pop up as notifications at the right time (also when you are "
              "not running). action set: kind timer (in_seconds), alarm or reminder (at '07:30' or "
              "'2026-11-16 09:00', or in_seconds), text = what it is for, optional repeat daily/weekdays. "
              "action list: show all. action cancel: by id, by words of its text, or 'all'.",
              {"action": {"type": "string", "enum": ["set", "list", "cancel"]},
               "kind": {"type": "string", "enum": ["timer", "alarm", "reminder"]},
               "in_seconds": {"type": "integer", "minimum": 1, "maximum": 31_536_000},
               "at": {"type": "string", "maxLength": 40},
               "text": {"type": "string", "maxLength": 300},
               "repeat": {"type": "string", "enum": ["none", "daily", "weekdays"]},
               "which": {"type": "string", "maxLength": 100, "description": "For cancel: id, words, or 'all'."}},
              ["action"], risk="reversible", title="Timers and reminders")
    def timer(ctx: Context, action: str, kind: str = "reminder", in_seconds: int | None = None,
              at: str | None = None, text: str = "", repeat: str = "none", which: str | None = None) -> Result:
        now = dt.datetime.now()
        if action == "set":
            when = parse_when(at, in_seconds, now)
            if when <= now:
                raise HandsError("That time has already passed.")
            item = {"id": secrets.token_hex(4), "kind": kind, "text": (text or KIND_TITLE[kind]["de"]).strip()[:300],
                    "at": when.timestamp(), "created": time.time(), "repeat": repeat if repeat != "none" else None}
            try:
                arm(item)
            except dbus.DBusError as e:
                raise HandsError(f"The {kind} could not be scheduled: the system's timer service is not "
                                 f"available ({e.message[:80]}).")
            with locked_store() as data:
                data["items"].append(item)
            rep = {"daily": ", every day", "weekdays": ", every weekday"}.get(repeat, "")
            return Result.text(f"{kind.capitalize()} set for {when:%A %d %B, %H:%M:%S} (in "
                               f"{human_delta((when - now).total_seconds())}){rep}. id {item['id']}.")
        with locked_store() as data:
            items = sorted(data["items"], key=lambda i: i["at"])
            if action == "list":
                if not items:
                    return Result.text("No timers, alarms or reminders are set.")
                lines = [f"{i['id']} {i['kind']} at {dt.datetime.fromtimestamp(i['at']):%a %d %b %H:%M:%S} "
                         f"(in {human_delta(i['at'] - now.timestamp())}){' repeats ' + i['repeat'] if i.get('repeat') else ''}: "
                         f"{i['text']}" for i in items]
                return Result.text(f"{len(items)} set:\n" + "\n".join(lines))
            # cancel
            w = (which or "").strip().lower()
            if not w:
                raise HandsError("Which one? Give its id, words from its text, or 'all'.")
            if w in ("all", "alle"):
                hit = items
            else:
                hit = [i for i in items if i["id"] == w] or [i for i in items if w in i["text"].lower()] or \
                      [i for i in items if w == i["kind"]]
            if not hit:
                raise HandsError(f"Nothing set matches “{which[:40]}”.")
            for i in hit:
                disarm(i["id"])
            ids = {i["id"] for i in hit}
            data["items"] = [i for i in data["items"] if i["id"] not in ids]
            return Result.text(f"Cancelled {len(hit)}: " + "; ".join(f"{i['kind']} {i['text'][:40]}" for i in hit))


# ---------------------------------------------------------------------------- entry points

def _lang() -> str:
    try:
        from .config import Settings
        return Settings().language()
    except Exception:
        return "de"


def fire(rid: str) -> int:
    from .system import send_notification
    lang = _lang()
    now = dt.datetime.now()
    with locked_store() as data:
        item = next((i for i in data["items"] if i["id"] == rid), None)
        if item is None:
            return 0
        missed = now.timestamp() - item["at"] > 120
        if item.get("repeat"):
            item["at"] = next_repeat(dt.datetime.fromtimestamp(item["at"]), item["repeat"], now).timestamp()
        else:
            data["items"] = [i for i in data["items"] if i["id"] != rid]
    if item.get("repeat"):
        try:
            arm(item)
        except dbus.DBusError as e:
            log.warning("could not re-arm %s: %s", rid, e)
    title = KIND_TITLE.get(item["kind"], KIND_TITLE["reminder"])[lang]
    body = item["text"]
    if missed:
        when = dt.datetime.fromtimestamp(item["at"] if not item.get("repeat") else time.time())
        body += (f" (verpasst, war fällig um {when:%H:%M})" if lang == "de" else f" (missed, was due at {when:%H:%M})")
    loud = item["kind"] in ("timer", "alarm")
    try:
        send_notification(title, body, urgency=2 if loud else 1,
                          sound="alarm-clock-elapsed" if loud else "message-new-instant", icon="alarm-clock")
    except dbus.DBusError as e:
        log.error("reminder %s: notification failed: %s", rid, e)
    if loud and not missed:
        snd = "/usr/share/sounds/freedesktop/stereo/alarm-clock-elapsed.oga"
        player = shutil.which("pw-play")
        if player and os.path.exists(snd):
            subprocess.run([player, snd], timeout=15, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
    return 0


def rearm_all() -> int:
    """At login: re-create the timers (transient units do not survive a logout) and fire what
    came due in the meantime."""
    now = time.time()
    due, future = [], []
    with locked_store() as data:
        for i in data["items"]:
            (due if i["at"] <= now else future).append(i)
    for i in future:
        try:
            arm(i)
        except dbus.DBusError as e:
            log.warning("cannot arm %s: %s", i["id"], e)
    for i in due:
        fire(i["id"])
    log.info("re-armed %d reminders, fired %d missed", len(future), len(due))
    return 0
