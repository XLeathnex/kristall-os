# SPDX-License-Identifier: GPL-3.0-or-later
"""Battery charge limit (battery longevity).

Kernel interfaces, in order of preference, per system battery:
  1. charge_control_end_threshold (+ charge_control_start_threshold when present), percent;
  2. charge_types offering "Long_Life" (firmware-defined limit, e.g. Lenovo conservation mode).
The owner's choice is `power.chargeLimit` (50..100, 100 = off). The persisted copy for boot is
/var/lib/kristall/power/charge-limit; the values found before our first write are kept in
charge-original.json and restored by `revert`. Some firmware forgets thresholds at power-off, which
is why kristall-power.service re-applies the stored value at every boot."""
import errno
import os
import re

from . import hw, paths, sysfs

LIMIT_FILE = os.path.join(paths.STATE_DIR, "charge-limit")
ORIG_FILE = os.path.join(paths.STATE_DIR, "charge-original.json")
APPLIED_FILE = os.path.join(paths.RUN_DIR, "charge.json")
MIN_LIMIT, MAX_LIMIT = 50, 100
START_GAP = 5  # restart charging 5 points below the limit (no micro-cycles at the top)


def valid_limit(v):
    try:
        n = int(str(v))
    except (TypeError, ValueError):
        return None
    if str(n) != str(v).strip() or not MIN_LIMIT <= n <= MAX_LIMIT:
        return None
    return n


def _charge_types(d):
    raw = sysfs.read(os.path.join(d, "charge_types"))
    if raw is None:
        return None, []
    cur = re.search(r"\[([^\]]+)\]", raw)
    return (cur.group(1) if cur else raw.split()[0] if raw.split() else None), raw.replace("[", "").replace("]", "").split()


def capability():
    """What this machine supports, per battery."""
    out = []
    for b in hw.system_batteries():
        d = b["dir"]
        end = os.path.exists(os.path.join(d, "charge_control_end_threshold"))
        start = os.path.exists(os.path.join(d, "charge_control_start_threshold"))
        cur_type, types = _charge_types(d)
        kind = "threshold" if end else ("long-life" if "Long_Life" in types else None)
        out.append({"battery": b["name"], "method": kind, "start_threshold": start,
                    "charge_types": types or None, "charge_type": cur_type})
    return out


def supported():
    return any(c["method"] for c in capability())


def _remember_originals():
    orig = sysfs.read_json(ORIG_FILE, {}) or {}
    changed = False
    for b in hw.system_batteries():
        if b["name"] in orig:
            continue
        d = b["dir"]
        cur_type, _ = _charge_types(d)
        orig[b["name"]] = {"end": sysfs.read_int(os.path.join(d, "charge_control_end_threshold")),
                           "start": sysfs.read_int(os.path.join(d, "charge_control_start_threshold")),
                           "charge_type": cur_type}
        changed = True
    if changed:
        try:
            sysfs.write_json_atomic(ORIG_FILE, orig)
        except OSError:
            pass
    return orig


def _set_thresholds(d, end, start):
    """Write end/start in an order the driver accepts (start must stay below end)."""
    endf, startf = os.path.join(d, "charge_control_end_threshold"), os.path.join(d, "charge_control_start_threshold")
    has_start = os.path.exists(startf) and start is not None
    cur_end = sysfs.read_int(endf)
    order = [(endf, end)]
    if has_start:
        order = [(endf, end), (startf, start)] if cur_end is None or end >= cur_end else [(startf, start), (endf, end)]
    for f, v in order:
        rc = sysfs.write(f, v)
        if rc:
            return rc, f
    return 0, None


def apply_limit(limit: int):
    n = valid_limit(limit)
    if n is None:
        return [{"lever": "charge-limit", "status": "rejected", "detail": f"invalid value {limit!r} (allowed {MIN_LIMIT}..{MAX_LIMIT})"}]
    orig = _remember_originals()
    results = []
    bats = hw.system_batteries()
    if not bats:
        return [{"lever": "charge-limit", "status": "not-applicable", "detail": "no battery"}]
    for b, cap in zip(bats, capability()):
        d, lever = b["dir"], f"charge-limit:{b['name']}"
        if cap["method"] == "threshold":
            o = orig.get(b["name"], {})
            if n >= 100:
                # "off": charge to full. Keep the machine's own start value if it came with no
                # limit; otherwise 95 (accepted by every driver we know that has a start file).
                end = 100
                if o.get("end") == 100 and o.get("start") is not None and o["start"] < 100:
                    start = o["start"]
                else:
                    start = 100 - START_GAP
            else:
                end, start = n, max(n - START_GAP, 0)
            rc, where = _set_thresholds(d, end, start if cap["start_threshold"] else None)
            got = sysfs.read_int(os.path.join(d, "charge_control_end_threshold"))
            if rc:
                status = "failed" if rc != errno.EACCES else "locked"
                results.append({"lever": lever, "status": status, "detail": f"{os.path.basename(where)}: {sysfs.errname(rc)}"})
            elif got != end:
                results.append({"lever": lever, "status": "applied", "value": got,
                                "detail": f"firmware adjusted {end} to {got}"})
            else:
                results.append({"lever": lever, "status": "applied", "value": got})
        elif cap["method"] == "long-life":
            want = "Long_Life" if n < 100 else ("Standard" if "Standard" in (cap["charge_types"] or []) else orig.get(b["name"], {}).get("charge_type") or "Standard")
            rc = sysfs.write(os.path.join(d, "charge_types"), want)
            results.append({"lever": lever, "status": "applied" if rc == 0 else "failed",
                            "value": "firmware" if want == "Long_Life" else 100, "detail": f"charge_types={want}" + ("" if rc == 0 else f" {sysfs.errname(rc)}")})
        else:
            results.append({"lever": lever, "status": "unsupported", "detail": "no charge_control_end_threshold or Long_Life charge type"})
    try:
        os.makedirs(paths.STATE_DIR, exist_ok=True)
        with open(LIMIT_FILE + ".tmp", "w") as f:
            f.write(f"{n}\n")
        os.replace(LIMIT_FILE + ".tmp", LIMIT_FILE)
        sysfs.write_json_atomic(APPLIED_FILE, {"limit": n, "results": results})
    except OSError:
        pass
    return results


def stored_limit():
    v = sysfs.read(LIMIT_FILE)
    return valid_limit(v) if v else None


def revert():
    orig = sysfs.read_json(ORIG_FILE, {}) or {}
    results = []
    for b in hw.system_batteries():
        o = orig.get(b["name"])
        if not o:
            continue
        d = b["dir"]
        if o.get("end") is not None:
            rc, _ = _set_thresholds(d, o["end"], o.get("start"))
            results.append({"lever": f"charge-limit:{b['name']}", "status": "reverted" if rc == 0 else "failed"})
        elif o.get("charge_type"):
            rc = sysfs.write(os.path.join(d, "charge_types"), o["charge_type"])
            results.append({"lever": f"charge-limit:{b['name']}", "status": "reverted" if rc == 0 else "failed"})
    return results
