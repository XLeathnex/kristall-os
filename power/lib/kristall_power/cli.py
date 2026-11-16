# SPDX-License-Identifier: GPL-3.0-or-later
"""kristall-power command line (contract: docs/contracts/power.md §7)."""
import argparse
import json
import os
import subprocess
import sys

from . import VERSION, paths, policy, sysfs

DOCTOR_SYSTEM_JSON = os.path.join(paths.STATE_DIR, "doctor-system.json")


def _print_json(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False, separators=(",", ":"), sort_keys=True) + "\n")


def _lang():
    lang = (os.environ.get("LANGUAGE") or os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "de")
    return "en" if lang.lower().startswith("en") else "de"


def _need_root():
    if os.geteuid() != 0 and not paths.ROOT:
        print("kristall-power: this command needs root (it is run by systemd/tuned)", file=sys.stderr)
        sys.exit(4)


def cmd_status(a):
    from . import status
    st = status.collect(measure=a.measure)
    if a.json:
        _print_json(st)
    else:
        print(status.human(st, _lang()))
    return 0


def cmd_doctor(a):
    from . import doctor
    if os.geteuid() == 0 or paths.ROOT or a.local:
        rep = doctor.run_system(a.idle_seconds)
        if os.geteuid() == 0 and a.system_only:
            sysfs.write_json_atomic(DOCTOR_SYSTEM_JSON, rep)
            with open(DOCTOR_SYSTEM_JSON.replace(".json", ".txt"), "w") as f:
                f.write(doctor.summary(rep))
            return 0
    else:
        # unprivileged: ask the root unit for a fresh system report (polkit allows the active
        # local user without a password), then add this session's view
        before = os.path.getmtime(DOCTOR_SYSTEM_JSON) if os.path.exists(DOCTOR_SYSTEM_JSON) else 0
        if not a.no_refresh:
            subprocess.run(["systemctl", "start", "kristall-power-doctor.service"], check=False,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=120)
        rep = sysfs.read_json(DOCTOR_SYSTEM_JSON, None)
        if rep is None:
            rep = doctor.run_system(a.idle_seconds)
            rep["note"] = "system part collected without root (RAPL lock state, energy and debugfs unavailable)"
        elif os.path.getmtime(DOCTOR_SYSTEM_JSON) <= before:
            rep["note"] = "system part is from an earlier run (could not refresh)"
    rep = doctor.add_session(rep)
    out_dir = a.out or paths.user_state_dir()
    try:
        os.makedirs(out_dir, exist_ok=True)
        sysfs.write_json_atomic(os.path.join(out_dir, "doctor.json"), rep, mode=0o600)
        with open(os.path.join(out_dir, "doctor.txt"), "w") as f:
            f.write(doctor.summary(rep))
    except OSError as e:
        print(f"kristall-power: cannot write report to {out_dir}: {e}", file=sys.stderr)
    if a.json:
        _print_json(rep)
    else:
        print(doctor.summary(rep))
        print(f"Bericht / report: {os.path.join(out_dir, 'doctor.json')}")
    return 0


def cmd_mode(a):
    if a.mode == "auto":
        try:
            import dbus
            bus = dbus.SessionBus()
            bus.get_object("org.kristall.Power1", "/org/kristall/Power1").ResumeAutomatic(dbus_interface="org.kristall.Power1")
            return 0
        except Exception as e:  # noqa: BLE001
            print(f"kristall-power: session daemon not reachable: {e}", file=sys.stderr)
            return 1
    prof = policy.PPD_OF_MODE[a.mode]
    for name, path, iface in (("org.freedesktop.UPower.PowerProfiles", "/org/freedesktop/UPower/PowerProfiles", "org.freedesktop.UPower.PowerProfiles"),
                              ("net.hadess.PowerProfiles", "/net/hadess/PowerProfiles", "net.hadess.PowerProfiles")):
        r = subprocess.run(["busctl", "--system", "set-property", name, path, iface, "ActiveProfile", "s", prof],
                           stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
        if r.returncode == 0:
            return 0
    print("kristall-power: power-profiles service (tuned-ppd) not reachable", file=sys.stderr)
    return 1


def cmd_tuned_hook(a):
    from . import system
    return system.tuned_hook(a.action, a.profile)


def cmd_reapply(a):
    _need_root()
    from . import system
    system.reapply(settle=a.settle)
    return 0


def cmd_boot(a):
    _need_root()
    from . import system
    return system.boot()


def cmd_revert(a):
    _need_root()
    from . import system
    res = system.revert_all(include_charge=a.charge)
    if a.json:
        _print_json(res)
    return 0


def cmd_charge_limit(a):
    from . import charge, system
    if a.value is None:
        _print_json({"supported": charge.supported(), "methods": charge.capability(), "stored": charge.stored_limit()})
        return 0
    _need_root()
    res, ok = system.set_charge_limit(a.value)
    if a.json:
        _print_json(res)
    return 0 if ok else (2 if res and res[0]["status"] == "rejected" else 1)


def cmd_session(a):
    from . import session
    return session.main()


def main(argv=None):
    p = argparse.ArgumentParser(prog="kristall-power", description="Kristall OS power management")
    p.add_argument("--version", action="version", version=VERSION)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="current mode, power source, battery, draw, temperatures")
    s.add_argument("--json", action="store_true")
    s.add_argument("--measure", action="store_true", help="also measure RAPL power for 0.5 s (root)")
    s.set_defaults(fn=cmd_status)

    s = sub.add_parser("doctor", help="check every lever, measure idle, write the diagnostic report")
    s.add_argument("--json", action="store_true")
    s.add_argument("--out", help="report directory (default ~/.local/state/kristall/power)")
    s.add_argument("--idle-seconds", type=float, default=10.0)
    s.add_argument("--local", action="store_true", help="collect the system part in this process")
    s.add_argument("--no-refresh", action="store_true", help="do not start kristall-power-doctor.service")
    s.add_argument("--system-only", action="store_true", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_doctor)

    s = sub.add_parser("mode", help="choose a mode by hand, or 'auto' to return to automatic")
    s.add_argument("mode", choices=["auto", *policy.MODES])
    s.set_defaults(fn=cmd_mode)

    s = sub.add_parser("charge-limit", help="show charge-limit support, or set it (root)")
    s.add_argument("value", nargs="?")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_charge_limit)

    s = sub.add_parser("tuned-hook", help=argparse.SUPPRESS)
    s.add_argument("action")
    s.add_argument("profile")
    s.set_defaults(fn=cmd_tuned_hook)

    s = sub.add_parser("reapply", help=argparse.SUPPRESS)
    s.add_argument("--settle", action="store_true")
    s.set_defaults(fn=cmd_reapply)

    s = sub.add_parser("boot", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_boot)

    s = sub.add_parser("revert", help="undo power limits (and with --charge the charge limit)")
    s.add_argument("--charge", action="store_true")
    s.add_argument("--json", action="store_true")
    s.set_defaults(fn=cmd_revert)

    s = sub.add_parser("session", help=argparse.SUPPRESS)
    s.set_defaults(fn=cmd_session)

    a = p.parse_args(argv)
    return a.fn(a)


if __name__ == "__main__":
    sys.exit(main())
