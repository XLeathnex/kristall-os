# SPDX-License-Identifier: GPL-3.0-or-later
"""Hard refusals that do not depend on the permission policy: the lock screen, authentication
prompts, password fields, protected apps; and masking of secrets in text read from the screen."""
from __future__ import annotations

import re

from . import dbus
from .tooling import HandsError

LOCKED_MSG = ("The screen is locked, so I can't see or operate anything right now. "
              "The owner has to unlock it first.")
AUTH_MSG = ("This is a password or authentication prompt. I never type into those: the owner has to "
            "enter the password themselves.")
PROTECTED_MSG = ("That window belongs to a password or security app, which I am not allowed to read or "
                 "operate. The owner has to do this part themselves.")

AUTH_TITLE = re.compile(
    r"(?i)(authentication required|authenticat(e|ion) (is )?needed|legitimierung erforderlich|"
    r"authentifizierung (erforderlich|notwendig)|enter (your )?password|passwor[dt] eingeben|"
    r"kennwort eingeben|passphrase|kwallet|polkit|unlock (the )?keyring|schlüsselbund entsperren)")


def screen_locked(bus=None) -> bool:
    bus = bus or dbus.session()
    for name, path, iface in (("org.freedesktop.ScreenSaver", "/ScreenSaver", "org.freedesktop.ScreenSaver"),
                              ("org.freedesktop.ScreenSaver", "/org/freedesktop/ScreenSaver",
                               "org.freedesktop.ScreenSaver")):
        try:
            return bool(bus.call(name, path, iface, "GetActive")[0])
        except dbus.DBusError as e:
            if e.name in ("org.freedesktop.DBus.Error.ServiceUnknown", "org.kristall.NoGio", "org.kristall.NoBus"):
                return False
            continue
    return False


def ensure_unlocked(bus=None) -> None:
    if screen_locked(bus):
        raise HandsError(LOCKED_MSG)


def is_protected_app(app_id: str, protected: list[str]) -> bool:
    a = (app_id or "").lower()
    if a.endswith(".desktop"):
        a = a[:-8]
    return any(a == p.lower() or a.endswith("." + p.lower()) for p in protected)


def is_auth_window(win: dict, protected: list[str]) -> bool:
    return is_protected_app(str(win.get("appId", "")), protected) or bool(AUTH_TITLE.search(str(win.get("title", ""))))


def check_window(win: dict | None, protected: list[str], typing: bool = False) -> None:
    if not win:
        return
    if is_protected_app(str(win.get("appId", "")), protected):
        raise HandsError(AUTH_MSG if typing else PROTECTED_MSG)
    if typing and AUTH_TITLE.search(str(win.get("title", ""))):
        raise HandsError(AUTH_MSG)


# ---------------------------------------------------------------------------- secrets

_PEM = re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?(-----END [A-Z ]*PRIVATE KEY-----|$)", re.S)
_KEYS = re.compile(
    r"\b(sk-(?:ant-)?[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|"
    r"xox[abpr]-[A-Za-z0-9-]{10,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,}|glpat-[A-Za-z0-9_-]{16,}|"
    r"eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,})")
_CARD = re.compile(r"\b(?:\d[ -]?){13,19}\b")
_LONG = re.compile(r"\b[A-Za-z0-9+/_=-]{40,}\b")


def _luhn(digits: str) -> bool:
    total, alt = 0, False
    for ch in reversed(digits):
        d = ord(ch) - 48
        if alt:
            d *= 2
            if d > 9:
                d -= 9
        total += d
        alt = not alt
    return total % 10 == 0


def _mask_card(m: re.Match) -> str:
    s = m.group(0)
    digits = re.sub(r"\D", "", s)
    if 13 <= len(digits) <= 19 and _luhn(digits):
        return f"[card number ending {digits[-4:]}]"
    return s


def _mask_long(m: re.Match) -> str:
    s = m.group(0)
    # long tokens that mix upper, lower and digits look like keys; paths/words do not
    if re.search(r"[A-Z]", s) and re.search(r"[a-z]", s) and re.search(r"\d", s) and "/" not in s[:8]:
        return f"[hidden secret-looking text, {len(s)} chars]"
    return s


def mask_secrets(text: str) -> str:
    if not text:
        return text
    text = _PEM.sub("[hidden private key]", text)
    text = _KEYS.sub(lambda m: f"[hidden key {m.group(0)[:4]}…]", text)
    text = _CARD.sub(_mask_card, text)
    text = _LONG.sub(_mask_long, text)
    return text
