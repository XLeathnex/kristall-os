# SPDX-License-Identifier: GPL-3.0-or-later
"""Firefox (the RPM, as the OS image ships it) in a headless KWin session, on a static local page,
with a throw-away profile that skips first-run pages and never touches the network."""
from __future__ import annotations

import json
import os
import subprocess

PAGE = """<!doctype html><html lang="de"><head><meta charset="utf-8"><title>Kristall Testseite</title></head>
<body><h1>Wochenmarkt am Samstag</h1><p>Frische Äpfel, Brot und Käse.</p>
<button>Bestellen</button> <a href="#preise">Preise ansehen</a></body></html>"""

PREFS = {
    "browser.shell.checkDefaultBrowser": False, "browser.aboutwelcome.enabled": False,
    "browser.startup.homepage_override.mstone": "ignore", "trailhead.firstrun.didSeeAboutWelcome": True,
    "datareporting.policy.dataSubmissionEnabled": False, "toolkit.telemetry.reportingpolicy.firstRun": False,
    "app.update.enabled": False, "app.normandy.enabled": False, "browser.region.network.url": "",
    "network.captive-portal-service.enabled": False, "network.connectivity-service.enabled": False,
    "extensions.update.enabled": False, "browser.safebrowsing.update.enabled": False,
    "browser.newtabpage.enabled": False, "browser.startup.page": 0, "browser.sessionstore.resume_from_crash": False,
    "browser.tabs.warnOnClose": False, "media.hardware-video-decoding.enabled": False,
}


def available() -> bool:
    return os.path.exists("/usr/bin/firefox") or os.path.exists("/usr/lib64/firefox/firefox")


def start(session, tmp: str, env: dict, name: str = "firefox") -> subprocess.Popen:
    page = os.path.join(tmp, "seite.html")
    with open(page, "w", encoding="utf-8") as f:
        f.write(PAGE)
    profile = os.path.join(tmp, f"profile-{name}")
    os.makedirs(profile, exist_ok=True)
    with open(os.path.join(profile, "user.js"), "w") as f:
        for k, v in PREFS.items():
            f.write(f'user_pref("{k}", {json.dumps(v)});\n')
    extra = {"MOZ_ENABLE_WAYLAND": "1", "MOZ_CRASHREPORTER_DISABLE": "1", "HOME": tmp}
    extra.update(env)
    return session.app(["firefox", "--no-remote", "--new-instance", "--profile", profile, "file://" + page],
                       name=name, **extra)
