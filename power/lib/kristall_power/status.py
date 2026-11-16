# SPDX-License-Identifier: GPL-3.0-or-later
"""`kristall-power status [--json]`: everything the shell and the settings screen show.
Unprivileged, no D-Bus, a few ms: reads sysfs, tuned's state files and the state files written by
the root side (/run/kristall-power) and the session daemon ($XDG_RUNTIME_DIR/kristall/power.json)."""
import os
import time

from . import SCHEMA, charge, hw, logbook, paths, policy, rapl, sysfs


def tuned_state():
    active = sysfs.read(os.path.join(paths.TUNED_DIR, "active_profile"))
    active = active.split()[0] if active and active.split() else None
    base = sysfs.read(os.path.join(paths.TUNED_DIR, "ppd_base_profile"))
    return active, base


def rapl_power_w(interval=0.5):
    """Package and platform (psys) power from RAPL energy counters. Root only (energy_uj is 0400
    since the 2020 PLATYPUS fix); returns {} for other users."""
    zones = {}
    for z in rapl.package_zones():
        if z["interface"] == "msr":
            zones["package"] = os.path.join(z["dir"], "energy_uj")
    ps = rapl.psys_zone()
    if ps:
        zones["platform"] = os.path.join(ps, "energy_uj")
    first = {k: sysfs.read_int(v) for k, v in zones.items()}
    first = {k: v for k, v in first.items() if v is not None}
    if not first:
        return {}
    t0 = time.monotonic()
    time.sleep(interval)
    dt = time.monotonic() - t0
    out = {}
    for k, v0 in first.items():
        v1 = sysfs.read_int(zones[k])
        if v1 is not None and v1 >= v0:
            out[k] = round((v1 - v0) / 1e6 / dt, 2)
    return out


def collect(measure=False):
    active, base = tuned_state()
    parsed = policy.parse_tuned_profile(active) if active else None
    sess = sysfs.read_json(paths.session_state_file(), None)
    bats = hw.system_batteries()
    on_batt = hw.on_battery()
    source = "battery" if on_batt else ("ac" if bats or hw.ac_online() else "none")
    battery = hw.battery_info(bats[0]) if bats else None
    caps = charge.capability()
    applied_limit = (sysfs.read_json(os.path.join(paths.RUN_DIR, "charge.json"), {}) or {}).get("limit")
    stored = charge.stored_limit()
    mode = parsed[0] if parsed else (sess or {}).get("mode") or policy.MODE_OF_PPD.get(base)
    draw = None
    if battery and battery.get("status") == "Discharging" and battery.get("power_w"):
        draw = {"watts": battery["power_w"], "source": "battery"}
    if measure:
        rp = rapl_power_w()
        if rp.get("platform") is not None and draw is None:
            draw = {"watts": rp["platform"], "source": "rapl-platform"}
        elif rp.get("package") is not None and draw is None:
            draw = {"watts": rp["package"], "source": "rapl-package (CPU+iGPU only)"}
    if sess:
        automatic = {"enabled": sess.get("automatic"), "manual": sess.get("manual"),
                     "reason": sess.get("reason"), "hold": sess.get("hold"),
                     "game": sess.get("game"), "heavy_app": sess.get("heavy_app")}
    else:
        automatic = {"enabled": None, "manual": None, "reason": "session daemon not running", "hold": None}
    refresh = (sess or {}).get("refresh") or {}
    panel = refresh.get("panel") or {}
    applied = sysfs.read_json(os.path.join(paths.RUN_DIR, "applied.json"), {}) or {}
    return {
        "schema": SCHEMA,
        "time": logbook.now_iso(),
        "mode": mode,
        "mode_name": policy.NAMES.get(mode) if mode else None,
        "tuned_profile": active,
        "ppd_base_profile": base,
        "automatic": automatic,
        "power_source": source,
        "battery": battery,
        "charge_limit": {"supported": any(c["method"] for c in caps), "methods": caps,
                         "value": applied_limit if applied_limit is not None else stored if stored is not None else 100},
        "draw": draw,
        "temperatures": hw.temperatures(),
        "fans": hw.fans(),
        "display": {"refresh_hz": panel.get("refresh_hz"), "available_hz": panel.get("available_hz"),
                    "managed": refresh.get("managed"), "target": refresh.get("target"),
                    "vrr_policy": panel.get("vrr_policy")},
        "glass_quality_hint": (sess or {}).get("glass_hint"),
        "platform_profile": (applied.get("platform_profile") or {}).get("current") or (hw.platform_profile() or {}).get("profile"),
        "limits": [{k: r.get(k) for k in ("lever", "status", "target_uw", "baseline_uw")} for r in applied.get("rapl", [])],
    }


def human(st, lang="de"):
    de = lang == "de"
    lines = []
    m = st.get("mode_name") or {}
    lines.append(("Modus: " if de else "Mode: ") + (m.get(lang) or "?") +
                 ((" (automatisch)" if de else " (automatic)") if st["automatic"].get("enabled") and not st["automatic"].get("manual") else ""))
    src = {"battery": ("Akku", "battery"), "ac": ("Netzteil", "power adapter"), "none": ("Netz (kein Akku)", "mains (no battery)")}[st["power_source"]]
    lines.append(("Stromquelle: " if de else "Power source: ") + src[0 if de else 1])
    b = st.get("battery")
    if b:
        lines.append(f"{'Akku' if de else 'Battery'}: {b.get('percent')} %" +
                     (f", {'Zustand' if de else 'health'} {b['health_percent']} %" if b.get("health_percent") else "") +
                     (f", {b['cycle_count']} {'Ladezyklen' if de else 'cycles'}" if b.get("cycle_count") else ""))
    if st.get("draw"):
        lines.append(f"{'Leistungsaufnahme' if de else 'Power draw'}: {st['draw']['watts']} W")
    if st["display"].get("refresh_hz"):
        lines.append(f"{'Bildwiederholrate' if de else 'Refresh rate'}: {st['display']['refresh_hz']} Hz")
    t = st.get("temperatures") or {}
    if t.get("cpu_package") is not None:
        lines.append(f"{'Prozessor' if de else 'Processor'}: {t['cpu_package']} °C")
    return "\n".join(lines)
