# SPDX-License-Identifier: GPL-3.0-or-later
# Tiny test framework shared by the bridge test files (no pytest needed in the image).
import os
import sys
import time
import traceback

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "support"))
from harness import *  # noqa: E402,F401,F403

TESTS = []


class Failed(AssertionError):
    pass


def test(fn):
    TESTS.append(fn)
    return fn


def check(cond, msg):
    if not cond:
        raise Failed(msg)
    print(f"    ok   {msg}", flush=True)


def note(msg):
    print(f"    note {msg}", flush=True)


def near(a, b, tol=0.01):
    return a is not None and b is not None and abs(a - b) <= tol


def pointer_events(proc, mark=0, kinds=("enter", "leave", "motion", "button", "axis")):
    return [e for e in proc.since(mark) if e.get("ev") in kinds]


def run(argv):
    selected = [t for t in TESTS if not argv or any(a in t.__name__ for a in argv)]
    results = []
    for t in selected:
        print(f"--- {t.__name__}: {(t.__doc__ or '').strip().splitlines()[0] if t.__doc__ else ''}", flush=True)
        start = time.monotonic()
        try:
            t()
            results.append((t.__name__, True, ""))
            print(f"PASS {t.__name__} ({time.monotonic() - start:.1f}s)", flush=True)
        except Exception as e:  # noqa: BLE001
            results.append((t.__name__, False, str(e)))
            traceback.print_exc()
            print(f"FAIL {t.__name__}: {e}", flush=True)
    print("\n=== summary ===")
    for name, ok, msg in results:
        print(f"{'PASS' if ok else 'FAIL'} {name}{'' if ok else ': ' + msg}")
    failed = sum(1 for _, ok, _ in results if not ok)
    print(f"{len(results) - failed}/{len(results)} passed")
    return 1 if failed else 0


# ------------------------------------------------------------------------------- shared helpers

def content(w):
    return w["content"]["x"], w["content"]["y"]


def qt_layout(proc):
    return proc.wait("layout", 10)


def place(b, w, x, y, width, height):
    b.call("window.setGeometry", id=w["id"], x=x, y=y, w=width, h=height)
    return wait_until(lambda: next((v for v in b.call("window.list")["windows"]
                                    if v["id"] == w["id"] and abs(v["x"] - x) < 1 and abs(v["y"] - y) < 1), None), 5)


def refresh(b, w):
    return next(v for v in b.call("window.list")["windows"] if v["id"] == w["id"])


SHELL_QML = r"""
import QtQuick
import Quickshell
import Quickshell.Wayland
ShellRoot {
    PanelWindow {
        WlrLayershell.namespace: "kristall-dock"
        anchors { bottom: true; left: true; right: true }
        implicitHeight: 60
        color: "#3050ff"
        MouseArea { anchors.fill: parent; onPressed: (m) => console.warn("DOCK_PRESS " + m.x + " " + m.y) }
    }
    PanelWindow {
        WlrLayershell.namespace: "kristall-assistant-glow"
        WlrLayershell.layer: WlrLayer.Overlay
        anchors { top: true; left: true }
        margins { top: 0; left: 0 }
        implicitWidth: 400; implicitHeight: 300
        color: "#ff0000"
        MouseArea { anchors.fill: parent; onPressed: (m) => console.warn("GLOW_PRESS " + m.x + " " + m.y) }
    }
}
"""


def start_shell(s):
    path = os.path.join(s.tmp, "shell.qml")
    with open(path, "w") as f:
        f.write(SHELL_QML)
    return s.spawn(["quickshell", "-p", path], "shell", env={"QT_QPA_PLATFORM": "wayland", "QT_QUICK_BACKEND": "software"}, merge_stderr=True)


