# SPDX-License-Identifier: GPL-3.0-or-later
"""Package power limits through the powercap RAPL interfaces.

Two interfaces may exist: `intel-rapl` (MSR) and `intel-rapl-mmio` (the processor thermal device's
MMIO copy, which laptop firmware/EC usually programs). The CPU enforces the lower of the two, so
we only ever *lower* either one below what the firmware set, and restore the firmware value to undo.

Firmware value ("baseline") tracking: the first value we see in a boot is the baseline. Whenever the
current value is not what we last wrote, something else (firmware on resume, the EC on a power
source or platform profile change) changed it: that value becomes the new baseline and the event is
reported as drift. Baselines live in /run (gone at reboot, by design)."""
import errno
import os
import re

from . import paths, policy, sysfs

PC_DIR = os.path.join(paths.SYS, "class", "powercap")
STATE_FILE = os.path.join(paths.RUN_DIR, "rapl.json")
CONSTRAINT_KIND = {"long_term": "pl1", "short_term": "pl2"}


def package_zones():
    """Package-level zones: intel-rapl:N / intel-rapl-mmio:N whose name is package-*."""
    zones = []
    for n in sysfs.listdir(PC_DIR):
        if not re.match(r"intel-rapl(-mmio)?:\d+$", n):
            continue
        d = os.path.join(PC_DIR, n)
        name = sysfs.read(os.path.join(d, "name")) or ""
        if not name.startswith("package"):
            continue
        cons = {}
        for f in sysfs.listdir(d):
            m = re.match(r"constraint_(\d+)_name$", f)
            if not m:
                continue
            kind = CONSTRAINT_KIND.get(sysfs.read(os.path.join(d, f)))
            if kind:
                i = m.group(1)
                cons[kind] = {"index": int(i), "file": os.path.join(d, f"constraint_{i}_power_limit_uw"),
                              "max_file": os.path.join(d, f"constraint_{i}_max_power_uw"),
                              "window_file": os.path.join(d, f"constraint_{i}_time_window_us")}
        zones.append({"id": n, "dir": d, "interface": "mmio" if "-mmio" in n else "msr",
                      "enabled": sysfs.read(os.path.join(d, "enabled")), "constraints": cons})
    return zones


def psys_zone():
    for n in sysfs.listdir(PC_DIR):
        if re.match(r"intel-rapl(-mmio)?:\d+$", n) and sysfs.read(os.path.join(PC_DIR, n, "name")) == "psys":
            return os.path.join(PC_DIR, n)
    return None


def _load():
    return sysfs.read_json(STATE_FILE, {}) or {}


def _save(st):
    try:
        sysfs.write_json_atomic(STATE_FILE, st)
    except OSError:
        pass


def _close(a, b):
    return a is not None and b is not None and abs(a - b) <= policy.TOLERANCE_UW


def observe(st=None, save=True):
    """Record baselines/drift without writing anything. Returns (state, drift events)."""
    st = _load() if st is None else st
    drift = []
    for z in package_zones():
        zs = st.setdefault(z["id"], {})
        for kind, c in z["constraints"].items():
            cur = sysfs.read_int(c["file"])
            cs = zs.setdefault(kind, {"baseline": None, "written": None, "status": None})
            if cur is None:
                continue
            if cs["baseline"] is None:
                cs["baseline"] = cur
            elif cs["written"] is not None and not _close(cur, cs["written"]):
                drift.append({"zone": z["id"], "constraint": kind, "expected_uw": cs["written"], "found_uw": cur})
                cs["baseline"] = cur          # firmware set a new value: that is its new opinion
                cs["written"] = None
            elif cs["written"] is None and cur != cs["baseline"]:
                cs["baseline"] = cur          # changed by firmware while we were not managing it
    if save:
        _save(st)
    return st, drift


def apply(mode: str, on_battery: bool):
    """Program the limits for (mode, source). Returns (results, drift)."""
    st, drift = observe(save=False)
    caps = policy.RAPL_CAPS.get((mode, on_battery))
    results = []
    zones = package_zones()
    if not zones:
        results.append({"lever": "rapl", "status": "unsupported", "detail": "no package RAPL zone"})
    for z in zones:
        zs = st.setdefault(z["id"], {})
        if not z["constraints"]:
            results.append({"lever": f"rapl:{z['id']}", "status": "unsupported", "detail": "no long/short term constraint"})
        for kind, c in sorted(z["constraints"].items()):
            cs = zs.setdefault(kind, {"baseline": None, "written": None, "status": None})
            cur = sysfs.read_int(c["file"])
            lever = f"rapl:{z['id']}:{kind}"
            if cur is None or cs.get("baseline") is None:
                results.append({"lever": lever, "status": "unsupported", "detail": "unreadable"})
                continue
            max_uw = sysfs.read_int(c["max_file"], 0) or 0
            target = policy.rapl_target_uw(caps[kind] if caps else None, cs["baseline"], max_uw, kind)
            entry = {"lever": lever, "interface": z["interface"], "baseline_uw": cs["baseline"],
                     "target_uw": target, "current_uw": cur}
            if target is None:
                entry.update(status="skipped", detail="firmware value is 0/unknown")
            elif _close(cur, target):
                entry.update(status="applied", detail="already at target")
                if target != cs["baseline"]:
                    cs["written"] = cur
                else:
                    cs["written"] = None
            else:
                assert target <= cs["baseline"] and (not max_uw or target <= max_uw)
                rc = sysfs.write(c["file"], target)
                if rc == 0:
                    rb = sysfs.read_int(c["file"])
                    entry["current_uw"] = rb
                    if rb is not None and _close(rb, target):
                        entry.update(status="applied")
                        cs["written"] = rb if target != cs["baseline"] else None
                    elif rb is not None and rb != cur:
                        # the write took effect but the hardware rounded/clamped it: still ours
                        entry.update(status="applied", detail=f"hardware adjusted {target} to {rb}")
                        cs["written"] = rb
                    else:
                        entry.update(status="failed", detail=f"write accepted but value stayed {rb}")
                        cs["written"] = None
                elif rc in (errno.EACCES, errno.EPERM):
                    entry.update(status="locked", detail="locked by firmware (EACCES)")
                else:
                    entry.update(status="failed", detail=f"write error {sysfs.errname(rc)}")
            cs["status"] = entry["status"]
            results.append(entry)
    _save(st)
    return results, drift


def revert():
    """Restore every limit we changed to its firmware value."""
    st, _ = observe(save=False)
    results = []
    for z in package_zones():
        for kind, c in z["constraints"].items():
            cs = st.get(z["id"], {}).get(kind)
            if not cs or cs.get("written") is None or cs.get("baseline") is None:
                continue
            rc = sysfs.write(c["file"], cs["baseline"])
            results.append({"lever": f"rapl:{z['id']}:{kind}", "status": "reverted" if rc == 0 else "failed",
                            "target_uw": cs["baseline"], "detail": sysfs.errname(rc)})
            if rc == 0:
                cs["written"] = None
    _save(st)
    return results


def probe_lock(zone_dir: str, index: int):
    """Write the current value back (a no-op for the hardware) to learn if the limit is locked."""
    f = os.path.join(zone_dir, f"constraint_{index}_power_limit_uw")
    cur = sysfs.read_int(f)
    if cur is None:
        return "unreadable"
    rc = sysfs.write(f, cur)
    if rc == 0:
        return "writable"
    if rc in (errno.EACCES, errno.EPERM):
        return "locked"
    return f"error:{sysfs.errname(rc)}"
