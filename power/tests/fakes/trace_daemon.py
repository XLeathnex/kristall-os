# SPDX-License-Identifier: GPL-3.0-or-later
"""Debug helper (KP_DEBUG_IDLE=1): run the session daemon with every GLib timer and io watch
callback logged, to find whatever wakes it while it should be idle."""
import os
import sys
import time

sys.path.insert(0, os.environ["KRISTALL_POWER_LIB"])
from gi.repository import GLib  # noqa: E402


def wrap(name):
    orig = getattr(GLib, name)

    def patched(*args):
        fn = args[-1] if callable(args[-1]) else next(a for a in args if callable(a))
        label = getattr(fn, "__qualname__", repr(fn))

        def cb(*a):
            print(f"WAKE {time.monotonic():.2f} {name} {label}", file=sys.stderr, flush=True)
            return fn(*a)
        args = tuple(cb if a is fn else a for a in args)
        return orig(*args)
    setattr(GLib, name, patched)


for n in ("timeout_add", "timeout_add_seconds", "io_add_watch", "idle_add"):
    wrap(n)
from kristall_power import session  # noqa: E402
session.main()
