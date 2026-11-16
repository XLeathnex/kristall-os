# SPDX-License-Identifier: GPL-3.0-or-later
"""Hardware detection: read-only views of the kernel interfaces this component uses.
Nothing here writes; every function tolerates missing files (absent hardware)."""
import os
import re

from . import paths, sysfs

S = paths.SYS


def j(*parts):
    return os.path.join(*parts)


# ------------------------------------------------------------------------------ power supplies
PS_DIR = j(S, "class", "power_supply")
MAINS_TYPES = {"Mains", "USB", "USB_C", "USB_PD", "USB_PD_DRP", "BrickID", "Wireless"}


def power_supplies():
    out = []
    for name in sysfs.listdir(PS_DIR):
        d = j(PS_DIR, name)
        out.append({"name": name, "dir": d, "type": sysfs.read(j(d, "type")),
                    "scope": sysfs.read(j(d, "scope")), "online": sysfs.read(j(d, "online"))})
    return out


def system_batteries():
    """Laptop batteries (peripheral batteries have scope=Device and are ignored)."""
    return [p for p in power_supplies() if p["type"] == "Battery" and p["scope"] != "Device"
            and sysfs.read(j(p["dir"], "present"), "1") != "0"]


def ac_online():
    """True/False if a mains-type supply reports online, None if there is no such supply."""
    seen = False
    for p in power_supplies():
        if p["type"] in MAINS_TYPES:
            seen = True
            if p["online"] == "1":
                return True
    return False if seen else None


def on_battery():
    """True only if there is a system battery and no mains-type supply is online."""
    bats = system_batteries()
    if not bats:
        return False
    ac = ac_online()
    if ac is True:
        return False
    if ac is None:  # no AC device: trust the battery status
        return any(sysfs.read(j(b["dir"], "status")) == "Discharging" for b in bats)
    return True


def _uw(v):
    return None if v is None else v / 1_000_000


def battery_info(b):
    d = b["dir"]
    r = lambda a: sysfs.read_int(j(d, a))  # noqa: E731
    energy_now, energy_full, energy_design = r("energy_now"), r("energy_full"), r("energy_full_design")
    if energy_now is None and r("charge_now") is not None:  # charge-based (uAh) batteries
        v = r("voltage_min_design") or r("voltage_now")
        if v:
            conv = lambda c: None if c is None else c * v // 1_000_000  # noqa: E731
            energy_now, energy_full, energy_design = conv(r("charge_now")), conv(r("charge_full")), conv(r("charge_full_design"))
    power = r("power_now")
    if power is None and r("current_now") is not None and r("voltage_now") is not None:
        power = r("current_now") * r("voltage_now") // 1_000_000
    status = sysfs.read(j(d, "status"))
    capacity = r("capacity")
    if capacity is None and energy_now and energy_full:
        capacity = round(100 * energy_now / energy_full)
    health = round(100 * energy_full / energy_design, 1) if energy_full and energy_design else None
    tte = ttf = None
    if power and power > 0 and energy_now is not None:
        if status == "Discharging":
            tte = int(3600 * energy_now / power)
        elif status == "Charging" and energy_full:
            ttf = int(3600 * max(energy_full - energy_now, 0) / power)
    return {
        "name": b["name"], "percent": capacity, "status": status,
        "health_percent": health, "cycle_count": r("cycle_count"),
        "energy_wh": _uw(energy_now), "energy_full_wh": _uw(energy_full),
        "energy_full_design_wh": _uw(energy_design),
        "power_w": round(power / 1_000_000, 2) if power is not None else None,
        "time_to_empty_s": tte, "time_to_full_s": ttf,
        "technology": sysfs.read(j(d, "technology")),
        "manufacturer": sysfs.read(j(d, "manufacturer")), "model": sysfs.read(j(d, "model_name")),
        "charge_control_end_threshold": r("charge_control_end_threshold"),
        "charge_control_start_threshold": r("charge_control_start_threshold"),
        "charge_types": sysfs.read(j(d, "charge_types")),
    }


# ------------------------------------------------------------------------------ CPU
CPU_DIR = j(S, "devices", "system", "cpu")


def parse_cpulist(s):
    cpus = []
    for part in (s or "").replace("\n", ",").split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            a, b = part.split("-", 1)
            if a.isdigit() and b.isdigit():
                cpus.extend(range(int(a), int(b) + 1))
        elif part.isdigit():
            cpus.append(int(part))
    return cpus


def format_cpulist(cpus):
    cpus = sorted(set(cpus))
    out, i = [], 0
    while i < len(cpus):
        a = cpus[i]
        while i + 1 < len(cpus) and cpus[i + 1] == cpus[i] + 1:
            i += 1
        out.append(f"{a}-{cpus[i]}" if cpus[i] != a else str(a))
        i += 1
    return ",".join(out)


def cpu_model():
    txt = sysfs.read(j(paths.PROC, "cpuinfo"), "")
    m = re.search(r"^model name\s*:\s*(.+)$", txt, re.M)
    return m.group(1).strip() if m else None


def hybrid_layout():
    """{'p': [...], 'e': [...]} on Intel hybrid CPUs (cpu_core/cpu_atom PMUs), else None."""
    e = parse_cpulist(sysfs.read(j(S, "devices", "cpu_atom", "cpus")))
    p = parse_cpulist(sysfs.read(j(S, "devices", "cpu_core", "cpus")))
    if not e or not p:
        return None
    return {"p": p, "e": e}


def online_cpus():
    return parse_cpulist(sysfs.read(j(CPU_DIR, "online"))) or []


def cpufreq_policy_dirs():
    base = j(CPU_DIR, "cpufreq")
    return [j(base, n) for n in sysfs.listdir(base) if n.startswith("policy")]


def epp_values():
    """{policyN: epp} and the available preferences (from policy0)."""
    vals, avail = {}, None
    for d in cpufreq_policy_dirs():
        v = sysfs.read(j(d, "energy_performance_preference"))
        if v is not None:
            vals[os.path.basename(d)] = v
        if avail is None:
            a = sysfs.read(j(d, "energy_performance_available_preferences"))
            avail = a.split() if a else None
    return vals, avail


def intel_pstate():
    d = j(CPU_DIR, "intel_pstate")
    if not os.path.isdir(d):
        return None
    return {k: sysfs.read(j(d, k)) for k in ("status", "no_turbo", "hwp_dynamic_boost", "max_perf_pct",
                                             "min_perf_pct", "energy_efficiency")}


# ------------------------------------------------------------------------------ platform profile
ACPI_PP = j(S, "firmware", "acpi", "platform_profile")


def platform_profile():
    if not os.path.exists(ACPI_PP):
        return None
    handlers = []
    cls = j(S, "class", "platform-profile")
    for n in sysfs.listdir(cls):
        d = j(cls, n)
        handlers.append({"id": n, "name": sysfs.read(j(d, "name")),
                         "choices": (sysfs.read(j(d, "choices")) or "").split(),
                         "profile": sysfs.read(j(d, "profile"))})
    return {"profile": sysfs.read(ACPI_PP),
            "choices": (sysfs.read(ACPI_PP + "_choices") or "").split(), "handlers": handlers}


def pick_platform_profile(preferences, choices):
    for p in preferences:
        if p in choices:
            return p
    return None


# ------------------------------------------------------------------------------ thermal / fans
def thermal_zones():
    base = j(S, "class", "thermal")
    out = []
    for n in sysfs.listdir(base):
        if not n.startswith("thermal_zone"):
            continue
        t = sysfs.read_int(j(base, n, "temp"))
        out.append({"zone": n, "type": sysfs.read(j(base, n, "type")),
                    "temp_c": None if t is None else round(t / 1000, 1)})
    return out


def hwmon():
    base = j(S, "class", "hwmon")
    out = []
    for n in sysfs.listdir(base):
        d = j(base, n)
        entry = {"hwmon": n, "name": sysfs.read(j(d, "name")), "temps": {}, "fans": {}}
        for f in sysfs.listdir(d):
            m = re.match(r"(temp|fan)(\d+)_input$", f)
            if not m:
                continue
            v = sysfs.read_int(j(d, f))
            if v is None:
                continue
            label = sysfs.read(j(d, f"{m.group(1)}{m.group(2)}_label")) or f"{m.group(1)}{m.group(2)}"
            if m.group(1) == "temp":
                entry["temps"][label] = round(v / 1000, 1)
            else:
                entry["fans"][label] = v
        out.append(entry)
    return out


def temperatures():
    """Best-effort summary: package, max core, NVMe, skin/chassis where present (deg C)."""
    t = {}
    for h in hwmon():
        if h["name"] == "coretemp":
            pk = [v for k, v in h["temps"].items() if k.startswith("Package")]
            cores = [v for k, v in h["temps"].items() if k.startswith("Core")]
            if pk:
                t["cpu_package"] = max(pk)
            if cores:
                t["cpu_core_max"] = max(cores)
        elif h["name"] == "nvme" and h["temps"]:
            t["nvme"] = max(h["temps"].values())
    for z in thermal_zones():
        ty = (z["type"] or "").lower()
        if z["temp_c"] is None:
            continue
        if "x86_pkg_temp" in ty and "cpu_package" not in t:
            t["cpu_package"] = z["temp_c"]
        elif ty in ("sen1", "skin", "tskn", "sen2", "sen3") or "skin" in ty or "chassis" in ty:
            t.setdefault("skin", z["temp_c"])
        elif ty == "acpitz":
            t.setdefault("acpi", z["temp_c"])
    return t


def fans():
    out = {}
    for h in hwmon():
        for k, v in h["fans"].items():
            out[f"{h['name']}/{k}"] = v
    return out


# ------------------------------------------------------------------------------ graphics / display
def drm_cards():
    base = j(S, "class", "drm")
    out = []
    for n in sysfs.listdir(base):
        if not re.match(r"card\d+$", n):
            continue
        d = j(base, n)
        drv = os.path.basename(os.path.realpath(j(d, "device", "driver"))) if os.path.exists(j(d, "device", "driver")) else None
        card = {"card": n, "driver": drv, "connectors": []}
        for c in sysfs.listdir(base):
            if c.startswith(n + "-"):
                cd = j(base, c)
                card["connectors"].append({"name": c[len(n) + 1:], "status": sysfs.read(j(cd, "status")),
                                           "enabled": sysfs.read(j(cd, "enabled")), "dir": cd})
        out.append(card)
    return out


def gpu_idle_residency_paths():
    """Files with cumulative GPU idle time in ms (i915 RC6 or xe gt-idle), one per GT."""
    found = []
    base = j(S, "class", "drm")
    for card in sysfs.listdir(base):
        if not re.match(r"card\d+$", card):
            continue
        d = j(base, card)
        for cand in (j(d, "gt", "gt0", "rc6_residency_ms"), j(d, "power", "rc6_residency_ms"),
                     j(d, "device", "tile0", "gt0", "gtidle", "idle_residency_ms")):
            if os.path.exists(cand):
                found.append(cand)
                break
    return found


def internal_panels():
    return [c for card in drm_cards() for c in card["connectors"]
            if re.match(r"(eDP|LVDS|DSI)-", c["name"]) and c["status"] == "connected"]


def parse_edid(blob: bytes):
    """Tiny EDID 1.x parser: vendor, product, and the detailed timings' refresh rates."""
    if len(blob) < 128 or blob[:8] != b"\x00\xff\xff\xff\xff\xff\xff\x00":
        return None
    m = (blob[8] << 8) | blob[9]
    vendor = "".join(chr(((m >> s) & 0x1F) + 64) for s in (10, 5, 0))
    timings = []
    for i in range(4):
        o = 54 + 18 * i
        pclk = (blob[o] | (blob[o + 1] << 8)) * 10_000
        if not pclk:
            continue
        ha = blob[o + 2] | ((blob[o + 4] & 0xF0) << 4)
        hb = blob[o + 3] | ((blob[o + 4] & 0x0F) << 8)
        va = blob[o + 5] | ((blob[o + 7] & 0xF0) << 4)
        vb = blob[o + 6] | ((blob[o + 7] & 0x0F) << 8)
        if (ha + hb) and (va + vb):
            timings.append({"width": ha, "height": va, "refresh_hz": round(pclk / ((ha + hb) * (va + vb)), 2)})
    name = None
    for i in range(4):
        o = 54 + 18 * i
        if blob[o:o + 3] == b"\x00\x00\x00" and blob[o + 3] == 0xFC:
            name = blob[o + 5:o + 18].split(b"\n")[0].decode("ascii", "replace").strip()
    return {"vendor": vendor, "product": (blob[11] << 8) | blob[10], "name": name, "timings": timings,
            "extensions": blob[126]}


def backlights():
    base = j(S, "class", "backlight")
    return [{"name": n, "type": sysfs.read(j(base, n, "type")), "max": sysfs.read_int(j(base, n, "max_brightness")),
             "brightness": sysfs.read_int(j(base, n, "brightness"))} for n in sysfs.listdir(base)]


# ------------------------------------------------------------------------------ DMI
def dmi():
    d = j(S, "class", "dmi", "id")
    # never product_serial / product_uuid / board_serial (private, and root-only anyway)
    keys = ("sys_vendor", "product_name", "product_version", "product_family", "board_vendor",
            "board_name", "bios_vendor", "bios_version", "bios_date", "chassis_type")
    return {k: sysfs.read(j(d, k)) for k in keys}
