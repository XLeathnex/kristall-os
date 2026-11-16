# SPDX-License-Identifier: GPL-3.0-or-later
# Finds where a running Qt app exports its menu bar over DBusMenu (bus name of its pid and the
# /MenuBar/<n> object path). The real bridge learns this from KWin (the app announces it with
# the org_kde_kwin_appmenu Wayland protocol); in tests we look it up and hand it to the mock bridge.
import re
import subprocess
import time


def find_menu(pid, env, timeout=10):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        names = subprocess.run(["busctl", "--user", "list", "--no-pager", "--no-legend"], env=env,
                               capture_output=True, text=True).stdout.splitlines()
        for line in names:
            parts = line.split()
            if len(parts) > 1 and parts[0].startswith(":") and parts[1] == str(pid):
                tree = subprocess.run(["busctl", "--user", "tree", parts[0], "--no-pager", "--list"], env=env,
                                      capture_output=True, text=True).stdout
                paths = [p for p in tree.split() if re.fullmatch(r"/MenuBar/\d+", p)]
                if paths:
                    return parts[0], paths[0]
        time.sleep(0.2)
    return None, None
