#!/usr/bin/python3
# SPDX-License-Identifier: GPL-3.0-or-later
"""Validate the Kristall tuned profiles and ppd.conf with tuned's own code (needs the `tuned`
Python package, i.e. the dev container or the image build):

1. every kristall-* profile loads through tuned's profile Loader (include chain, syntax,
   variable expansion);
2. every unit names an existing tuned plugin and only options that plugin declares;
3. the values agree with power/lib/kristall_power/policy.py (EPP, EPB, platform profile order,
   turbo, battery sysctl, the [script] hook running last);
4. ppd.conf is accepted by tuned-ppd's own PPDConfig parser and maps the three PPD profiles to the
   six Kristall profiles, injectively, for mains and battery.
"""
import argparse
import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "lib"))

import tuned.consts as consts  # noqa: E402
import tuned.profiles as profiles  # noqa: E402
from tuned.ppd.config import PPDConfig  # noqa: E402
from tuned.profiles.variables import Variables  # noqa: E402
from tuned.utils.global_config import GlobalConfig  # noqa: E402

from kristall_power import policy  # noqa: E402

GENERIC = {"priority", "type", "enabled", "replace", "prepend", "drop", "devices", "devices_udev_regex",
           "cpuinfo_regex", "uname_regex", "script_pre", "script_post"}
EPB_ALIASES = {"normal": "normal", "balance-power": "balance-power", "performance": "performance"}

failures = []


def check(cond, msg):
    print(("ok   " if cond else "FAIL ") + msg)
    if not cond:
        failures.append(msg)


def plugin_options(plugin_type):
    mod = __import__(f"tuned.plugins.plugin_{plugin_type}", fromlist=["x"])
    for obj in vars(mod).values():
        if isinstance(obj, type) and hasattr(obj, "_get_config_options") and obj.__module__ == mod.__name__:
            return set(obj._get_config_options().keys())
    raise LookupError(plugin_type)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profiles", required=True, help="directory holding kristall-* profile dirs")
    ap.add_argument("--ppd", required=True)
    a = ap.parse_args()

    dirs = [a.profiles, consts.SYSTEM_PROFILES_DIR]
    loader = profiles.Loader(profiles.Locator(dirs), profiles.Factory(), profiles.Merger(),
                             GlobalConfig(), Variables())
    for name in policy.ALL_TUNED_PROFILES:
        mode, on_bat = policy.parse_tuned_profile(name)
        try:
            prof = loader.load(name)
        except Exception as e:  # noqa: BLE001
            check(False, f"{name}: tuned Loader failed: {e}")
            continue
        check(True, f"{name}: loads (include chain kristall-common)")
        units = prof.units
        for uname, unit in units.items():
            try:
                allowed = plugin_options(unit.type)
            except (ImportError, LookupError):
                check(False, f"{name}: [{uname}] unknown plugin type '{unit.type}'")
                continue
            bad = set(unit.options) - allowed - GENERIC
            if unit.type == "sysctl":
                bad = set()  # sysctl options are sysctl names
            check(not bad, f"{name}: [{uname}] options known to plugin '{unit.type}'" + (f" (unknown: {sorted(bad)})" if bad else ""))
        cpu = units["cpu"].options
        check(cpu.get("energy_performance_preference") == policy.EPP[(mode, on_bat)],
              f"{name}: EPP {cpu.get('energy_performance_preference')} == policy {policy.EPP[(mode, on_bat)]}")
        check(cpu.get("energy_perf_bias") == policy.EPB[(mode, on_bat)],
              f"{name}: EPB {cpu.get('energy_perf_bias')} == policy {policy.EPB[(mode, on_bat)]}")
        check(cpu.get("boost") == "1" and "no_turbo" not in cpu, f"{name}: turbo stays enabled")
        check("performance" not in (cpu.get("governor") or "").split("|"), f"{name}: never the 'performance' governor")
        check("min_perf_pct" not in cpu, f"{name}: no min_perf_pct (would pin frequencies)")
        pp = units["acpi"].options.get("platform_profile", "").split("|")
        check(pp == policy.PLATFORM_PROFILE[mode], f"{name}: platform_profile {pp} == policy {policy.PLATFORM_PROFILE[mode]}")
        sc = units["script"]
        check(sc.priority is not None and int(sc.priority) >= 100, f"{name}: [script] runs last (priority {sc.priority})")
        scripts = sc.options.get("script")
        scripts = scripts if isinstance(scripts, list) else [scripts]
        check(any(s and s.endswith(f"/{name}/script.sh") for s in scripts), f"{name}: hook is {name}/script.sh")
        check(os.access(os.path.join(a.profiles, name, "script.sh"), os.X_OK) or not os.path.isdir(os.path.join(a.profiles, name)) or
              os.path.exists(os.path.join(a.profiles, "script.sh")),
              f"{name}: hook script present")
        sysctl = units["sysctl"].options
        check(sysctl.get("kernel.nmi_watchdog") == "0", f"{name}: nmi_watchdog off")
        if on_bat:
            check(sysctl.get("vm.dirty_writeback_centisecs") == "1500", f"{name}: battery writeback 15 s")
        else:
            check("vm.dirty_writeback_centisecs" not in sysctl, f"{name}: default writeback on mains")
        check(units["audio"].options.get("timeout") == "10", f"{name}: audio power save 10 s")

    class FakeTuned:
        def profiles(self):
            return sorted(set(os.listdir(consts.SYSTEM_PROFILES_DIR)) | set(os.listdir(a.profiles)))

    try:
        cfg = PPDConfig(a.ppd, FakeTuned())
        for mode in policy.MODES:
            ppd = policy.PPD_OF_MODE[mode]
            for on_bat in (False, True):
                got = cfg.ppd_to_tuned.get(ppd, on_bat)
                check(got == policy.tuned_profile(mode, on_bat), f"ppd.conf: {ppd} on {'battery' if on_bat else 'mains'} -> {got}")
                check(cfg.tuned_to_ppd.get(got, on_bat) == ppd, f"ppd.conf: {got} maps back to {ppd}")
        check(cfg.default_profile == "balanced", "ppd.conf: default balanced")
        check(cfg.battery_detection, "ppd.conf: battery detection on")
    except Exception as e:  # noqa: BLE001
        check(False, f"ppd.conf rejected by tuned-ppd's parser: {e}")

    print(f"\n{len(failures)} failure(s)")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
