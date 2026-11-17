#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Build the Kristall overlay of Plasma's desktop shell package (lock screen and log-out dialog).

In Plasma 6.8 the lock screen (kscreenlocker) and the log-out dialog are part of the *shell*
package org.kde.plasma.desktop, not of the look-and-feel package, and there is no setting to
point only those two at another package. So at image build time we copy the installed package
unchanged into /usr/share/kristall/theme/overlay/plasma/shells/org.kde.plasma.desktop and change
only two things in the copy; that directory is put first in XDG_DATA_DIRS for the session
(/usr/lib/environment.d/50-kristall-theme.conf), so Plasma finds the copy first. Because the copy
is made from the very plasma-desktop in the image, plasmashell itself sees identical files.

  * lock screen: LockScreenUi.qml is patched with exact-text anchors (clock → KristallClock at the
    top, user and password field lower, no sleep/hibernate/switch-user buttons). If any anchor
    does not match (Plasma changed the file), the lock screen stays stock. LockScreen.qml loads
    the patched file and falls back to the stock one if it fails to load; if even that fails,
    kscreenlocker uses its built-in fallback locker. The authentication code is never touched.
  * log-out: Logout.qml becomes a small loader for KristallLogout.qml with the stock dialog
    (Logout.stock.qml) as fallback.

    build-overlay.py SRC DEST OURS [MARKS]
      SRC   installed package, e.g. /usr/share/plasma/shells/org.kde.plasma.desktop
      DEST  overlay package directory to (re)create
      OURS  theme/plasma/shell-overlay (this directory)
      MARKS directory with mark.png / mark-dark.png (generated)
Exit status 0 always when DEST was written; a JSON report goes to stdout.
"""
import json
import os
import shutil
import sys

LOCK_PATCHES = [
    ("clock at the top, in the Mac's arrangement",
     """        Clock {
            id: clock
            property Item shadow: clockShadow
            visible: y > 0 && config.alwaysShowClock
            anchors.horizontalCenter: parent.horizontalCenter
            y: (mainBlock.userList.y + mainStack.y)/2 - height/2
            Layout.alignment: Qt.AlignBaseline
        }""",
     """        KristallClock {
            id: clock
            property Item shadow: clockShadow
            visible: config.alwaysShowClock
            anchors.horizontalCenter: parent.horizontalCenter
            y: Math.round(parent.height * 0.08)
        }"""),
    ("picture, name and password field in the lower part of the screen",
     """        StackView {
            id: mainStack
""",
     """        StackView {
            id: mainStack
            y: Math.round(lockScreenRoot.height * 0.17)
"""),
    ("no sleep button on the lock screen", "visible: sessionManagement.canSuspend", "visible: false && sessionManagement.canSuspend"),
    ("no hibernate button", "visible: sessionManagement.canHibernate", "visible: false && sessionManagement.canHibernate"),
    ("no switch-user button (one owner)", "visible: sessionManagement.canSwitchUser", "visible: false && sessionManagement.canSwitchUser"),
    # stock shows the button always; KWin has an input method only with a touchscreen on Kristall
    # (setup/keyboard: onscreenkeyboard.h), so without one there is no "Virtual Keyboard" button
    ("'Virtual Keyboard' button only when there is an on-screen keyboard",
     """                id: virtualKeyboardButton

                focusPolicy: Qt.TabFocus
""",
     """                id: virtualKeyboardButton

                visible: Keyboards.KWinVirtualKeyboard.available
                focusPolicy: Qt.TabFocus
"""),
]

LOCK_ROOT_ANCHOR = """    LockScreenUi {
        anchors.fill: parent
    }"""
LOCK_ROOT_REPLACEMENT = """    // Kristall: our arrangement, falling back to the stock lock screen if it does not load
    Loader {
        id: kristallLockUi
        anchors.fill: parent
        focus: true
        property bool fellBack: false
        source: "KristallLockScreenUi.qml"
        onStatusChanged: {
            if (status === Loader.Error && !fellBack) {
                fellBack = true;
                console.warn("kristall-theme: KristallLockScreenUi.qml failed to load, using the stock lock screen");
                source = "LockScreenUi.qml";
            }
        }
    }"""


def build(src, dest, ours, marks=None):
    report = {"source": src, "lockscreen": "stock", "logout": "stock", "notes": []}
    if os.path.exists(dest):
        shutil.rmtree(dest)
    shutil.copytree(src, dest, symlinks=True)
    lock = os.path.join(dest, "contents", "lockscreen")
    ui = os.path.join(lock, "LockScreenUi.qml")
    root = os.path.join(lock, "LockScreen.qml")
    if os.path.exists(ui) and os.path.exists(root):
        text = open(ui, encoding="utf-8").read()
        rtext = open(root, encoding="utf-8").read()
        missing = [name for name, old, _ in LOCK_PATCHES if text.count(old) != 1]
        if rtext.count(LOCK_ROOT_ANCHOR) != 1:
            missing.append("LockScreen.qml root anchor")
        if missing:
            report["notes"].append("lock screen left stock, anchors not found: " + "; ".join(missing))
        else:
            for _, old, new in LOCK_PATCHES:
                text = text.replace(old, new)
            with open(os.path.join(lock, "KristallLockScreenUi.qml"), "w", encoding="utf-8") as f:
                f.write("// Kristall: patched copy of plasma-desktop's LockScreenUi.qml (theme/plasma/shell-overlay/build-overlay.py)\n" + text)
            shutil.copy(os.path.join(ours, "lockscreen", "KristallClock.qml"), lock)
            with open(root, "w", encoding="utf-8") as f:
                f.write(rtext.replace(LOCK_ROOT_ANCHOR, LOCK_ROOT_REPLACEMENT))
            report["lockscreen"] = "kristall"
    else:
        report["notes"].append("no lockscreen in the source package")
    logout = os.path.join(dest, "contents", "logout")
    stock = os.path.join(logout, "Logout.qml")
    if os.path.exists(stock):
        os.rename(stock, os.path.join(logout, "Logout.stock.qml"))
        shutil.copy(os.path.join(ours, "logout", "Logout.qml"), logout)
        shutil.copy(os.path.join(ours, "logout", "KristallLogout.qml"), logout)
        if marks:
            for m in ("mark.png", "mark-dark.png"):
                if os.path.exists(os.path.join(marks, m)):
                    shutil.copy(os.path.join(marks, m), logout)
        report["logout"] = "kristall"
    else:
        report["notes"].append("no logout dialog in the source package")
    with open(os.path.join(dest, "contents", "kristall-overlay.json"), "w") as f:
        json.dump(report, f, indent=1)
    return report


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(__doc__, file=sys.stderr)
        sys.exit(2)
    print(json.dumps(build(*sys.argv[1:5])))
