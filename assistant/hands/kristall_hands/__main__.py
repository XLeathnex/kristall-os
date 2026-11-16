# SPDX-License-Identifier: GPL-3.0-or-later
"""Command line of kristall-hands.

    kristall-hands                 MCP server on stdin/stdout (started by Claude Code)
    kristall-hands fire ID         deliver a timer/alarm/reminder (run by its systemd timer)
    kristall-hands session-start   at login: re-arm reminders, apply the accessibility mode
    kristall-hands dropin [CMD]    print the mcp.d drop-in for the assistant daemon
    kristall-hands --version
"""
from __future__ import annotations

import sys

from . import __version__, log


def session_start() -> int:
    from . import dbus, reminders
    from .config import Settings
    log.setup()
    try:
        reminders.rearm_all()
    except Exception:
        log.exception("re-arming reminders failed")
    settings = Settings()
    mode = settings.hands().get("accessibility", "always")
    # hands.md §5: while the assistant is enabled and the mode is "always" (default), accessibility
    # is on from the start of the session (the environment generator 60-kristall-accessibility
    # did the toolkit side before any app started); otherwise every session starts with it off
    # (the value is persisted in GSettings, so a previous session's switch would otherwise stick).
    on = mode == "always" and settings.get("assistant.enabled", True) is not False
    bus = dbus.session()
    try:
        reader = bus.get("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "ScreenReaderEnabled")
        if not reader:
            bus.set("org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status", "IsEnabled", "b", on)
            log.info("accessibility at session start: %s", "on" if on else "off")
    except dbus.DBusError as e:
        log.info("accessibility bus not available: %s", e)
    return 0


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] == "serve":
        from .server import serve
        return serve()
    cmd = argv[0]
    if cmd in ("--version", "-V"):
        print(__version__)
        return 0
    if cmd == "fire" and len(argv) == 2:
        from . import reminders
        log.setup()
        return reminders.fire(argv[1])
    if cmd == "session-start":
        return session_start()
    if cmd == "dropin":
        from .server import print_dropin
        return print_dropin(argv[1] if len(argv) > 1 else "/usr/bin/kristall-hands")
    print(__doc__, file=sys.stderr)
    return 2


if __name__ == "__main__":
    sys.exit(main())
