# SPDX-License-Identifier: GPL-3.0-or-later
"""Root-side commands: run by tuned (profile hook), udev/system-sleep (re-apply), and the boot and
charge-limit units. All idempotent and fail-soft; every outcome is logged to the events log."""
import os
import subprocess
import time

from . import charge, hw, logbook, paths, policy, rapl, sysfs

EVENTS_LOG = os.path.join(paths.STATE_DIR, "events.jsonl")
APPLIED_FILE = os.path.join(paths.RUN_DIR, "applied.json")
STOPPED_FILE = os.path.join(paths.RUN_DIR, "stopped")   # kristall-power.service was stopped: hands off


def log(event, **fields):
    return logbook.append(EVENTS_LOG, event, **fields)


def active_tuned_profile():
    v = sysfs.read(os.path.join(paths.TUNED_DIR, "active_profile"))
    return v.split()[0] if v and v.split() else None


def _settle_delays():
    raw = os.environ.get("KRISTALL_POWER_SETTLE", "2,8")
    try:
        return [float(x) for x in raw.split(",") if x.strip()]
    except ValueError:
        return [2.0, 8.0]


def _systemctl(*args):
    if os.environ.get("KRISTALL_POWER_NO_SYSTEMD") == "1":
        return
    try:
        subprocess.run(["systemctl", *args], timeout=10, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def _summary(results):
    return {r["lever"]: r["status"] for r in results}


def _write_applied(profile, mode, on_battery, results, drift):
    pp = hw.platform_profile()
    want_pp = hw.pick_platform_profile(policy.PLATFORM_PROFILE[mode], pp["choices"]) if pp else None
    data = {"schema": 1, "time": logbook.now_iso(), "tuned_profile": profile, "mode": mode,
            "on_battery": on_battery, "rapl": results, "drift": drift,
            "platform_profile": {"current": pp["profile"] if pp else None, "expected": want_pp,
                                 "supported": pp is not None}}
    try:
        sysfs.write_json_atomic(APPLIED_FILE, data)
    except OSError:
        pass
    return data


def apply_profile(profile, reason):
    parsed = policy.parse_tuned_profile(profile)
    if os.path.exists(STOPPED_FILE):
        return None
    if not parsed:
        st, drift = rapl.observe()
        return None
    mode, on_battery = parsed
    results, drift = rapl.apply(mode, on_battery)
    for d in drift:
        log("drift", reason=reason, **d)
    log("apply", reason=reason, profile=profile, result=_summary(results))
    return _write_applied(profile, mode, on_battery, results, drift)


def live_session():
    """True in the installer's live system: nothing here changes the machine there."""
    cmdline = sysfs.read(os.path.join(paths.PROC, "cmdline"), "") or ""
    return "rd.live.image" in cmdline.split() or os.path.exists(paths.host("/etc/kristall/live"))


def tuned_hook(action, profile):
    """Called by power/tuned/script.sh inside each kristall-* tuned profile."""
    if live_session():
        return 0
    if action == "start":
        apply_profile(profile, "tuned")
        # Firmware/EC often rewrites limits shortly after a platform-profile or power-source
        # change: check again a little later (bounded, event-triggered, then exits).
        _systemctl("--no-block", "start", "kristall-power-reapply.service")
        return 0   # outcomes are in the events log; a non-zero exit would only make tuned log noise
    if action == "stop":
        res = rapl.revert()
        if res:
            log("revert", reason="tuned-stop", profile=profile, result=_summary(res))
        return 0
    if action == "verify":
        return 0
    return 2


def reapply(settle=False):
    """After resume / power-source change: put our limits back if firmware reset them."""
    profile = active_tuned_profile()
    out = apply_profile(profile, "reapply")
    if settle:
        for delay in _settle_delays():
            time.sleep(delay)
            out = apply_profile(active_tuned_profile(), "settle")
    return out


def boot():
    """Early boot (before tuned): remember the firmware's own limits, re-apply the charge limit."""
    try:
        os.unlink(STOPPED_FILE)
    except OSError:
        pass
    st, _ = rapl.observe()
    log("boot", rapl={z: {k: v.get("baseline") for k, v in c.items()} for z, c in st.items()},
        platform_profile=(hw.platform_profile() or {}).get("profile"))
    lim = charge.stored_limit()
    if lim is not None and charge.supported():
        res = charge.apply_limit(lim)
        log("charge-limit", reason="boot", limit=lim, result=_summary(res))
    return 0


def revert_all(include_charge=False):
    """Undo our power limits. The charge limit is the owner's standing choice (and must survive
    shutdown, when this runs from ExecStop), so it is only reverted on explicit request."""
    res = rapl.revert() + (charge.revert() if include_charge else [])
    log("revert", reason="charge+limits" if include_charge else "service-stop", result=_summary(res))
    try:
        os.makedirs(paths.RUN_DIR, exist_ok=True)
        with open(STOPPED_FILE, "w") as f:
            f.write("kristall-power.service stopped: power limits are left to the firmware until it starts again\n")
    except OSError:
        pass
    try:
        os.unlink(APPLIED_FILE)
    except OSError:
        pass
    return res


def set_charge_limit(value):
    res = charge.apply_limit(value)
    log("charge-limit", reason="request", limit=str(value), result=_summary(res))
    ok = all(r["status"] in ("applied", "unsupported", "not-applicable") for r in res)
    return res, ok
