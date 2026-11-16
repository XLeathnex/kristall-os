# SPDX-License-Identifier: GPL-3.0-or-later
"""`kristall-power doctor`: the lab we do not have.

Checks every lever (applied / unsupported / locked / failed / ...), measures whether the machine
reaches deep idle, and records the hardware facts needed to tune for the real laptop. One JSON
report and one human summary (German and English). Run as root (kristall-power-doctor.service)
it can also read RAPL energy, lock state, debugfs PSR/package C-state counters; run as the owner
it adds the session's view (refresh rate, glass, automatic mode) to the latest root report.
No serial numbers, UUIDs, MAC addresses or user names are collected."""
import glob
import os
import re
import shutil
import subprocess
import time

from . import SCHEMA, charge, hw, logbook, paths, policy, rapl, status, sysfs, system

S = paths.SYS
OK, UNSUP, LOCKED, FAILED, NA, SKIPPED, UNKNOWN, WARN = (
    "applied", "unsupported", "locked", "failed", "not-applicable", "skipped", "unknown", "warning")


def _run(cmd, timeout=5):
    if os.environ.get("KRISTALL_POWER_NO_EXEC") == "1" or not shutil.which(cmd[0]):
        return None
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.stdout.strip() if p.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None


def _unit_active(unit):
    out = _run(["systemctl", "is-active", unit])
    return out if out else "unknown"


def lever(name, status_, detail=None, expected=None, actual=None, **extra):
    d = {"lever": name, "status": status_}
    if detail is not None:
        d["detail"] = detail
    if expected is not None:
        d["expected"] = expected
    if actual is not None:
        d["actual"] = actual
    d.update(extra)
    return d


# ------------------------------------------------------------------------------ sections
def section_system():
    cmdline = sysfs.read(os.path.join(paths.PROC, "cmdline"), "")
    return {"kernel": os.uname().release if not paths.ROOT else sysfs.read(os.path.join(paths.PROC, "sys/kernel/osrelease")),
            "cmdline": cmdline, "dmi": hw.dmi(), "cpu_model": hw.cpu_model(),
            "hybrid": hw.hybrid_layout(), "online_cpus": hw.format_cpulist(hw.online_cpus()),
            "os_release": {k: v.strip('"') for k, v in re.findall(r"^(\w+)=(.*)$", sysfs.read(paths.host("/usr/lib/os-release"), "") or "", re.M)
                           if k in ("PRETTY_NAME", "IMAGE_VERSION", "VERSION_ID")}}


def section_cpu(mode, on_bat):
    levers = []
    epp, avail = hw.epp_values()
    ip = hw.intel_pstate()
    want = policy.EPP.get((mode, on_bat)) if mode else None
    if not epp:
        levers.append(lever("epp", UNSUP, "no energy_performance_preference (HWP/intel_pstate active mode missing)"))
    else:
        vals = sorted(set(epp.values()))
        st = OK if want and vals == [want] else (FAILED if want else UNKNOWN)
        levers.append(lever("epp", st, expected=want, actual=vals, available=avail))
    epb_files = glob.glob(os.path.join(hw.CPU_DIR, "cpu[0-9]*", "power", "energy_perf_bias"))
    epb = sorted({sysfs.read(f) for f in epb_files} - {None})
    epb_num = {"performance": "0", "balance-performance": "4", "normal": "6", "balance-power": "8", "power": "15"}
    want_epb = epb_num.get(policy.EPB.get((mode, on_bat))) if mode else None
    levers.append(lever("epb", UNSUP if not epb else (OK if want_epb and epb == [want_epb] else (FAILED if want_epb else UNKNOWN)),
                        expected=want_epb, actual=epb))
    if ip:
        stp = ip.get("status")
        levers.append(lever("intel-pstate-active", OK if stp == "active" else WARN,
                            None if stp == "active" else "HWP/EPP control and GameMode's governor write assume active mode",
                            expected="active", actual=stp))
        nt = ip.get("no_turbo")
        levers.append(lever("turbo", OK if nt == "0" else (WARN if nt == "1" else UNKNOWN),
                            "turbo disabled (by firmware, BIOS or thermal state)" if nt == "1" else None, expected="no_turbo=0", actual=nt))
    else:
        levers.append(lever("turbo", UNSUP, "intel_pstate not active"))
    sched = {"itmt": sysfs.read(os.path.join(paths.PROC, "sys/kernel/sched_itmt_enabled")),
             "energy_aware": sysfs.read(os.path.join(paths.PROC, "sys/kernel/sched_energy_aware")),
             "sched_ext": sysfs.read(os.path.join(S, "kernel/sched_ext/state")),
             "smt": sysfs.read(os.path.join(S, "devices/system/cpu/smt/control"))}
    pols = []
    for d in hw.cpufreq_policy_dirs():
        pols.append({k: sysfs.read(os.path.join(d, k)) for k in (
            "affected_cpus", "scaling_driver", "scaling_governor", "energy_performance_preference",
            "cpuinfo_min_freq", "cpuinfo_max_freq", "base_frequency", "scaling_min_freq", "scaling_max_freq")})
    return levers, {"intel_pstate": ip, "epp_available": avail, "scheduler": sched, "policies": pols}


def section_platform_profile(mode):
    pp = hw.platform_profile()
    if not pp:
        return [lever("platform-profile", UNSUP, "no /sys/firmware/acpi/platform_profile (no vendor fan/power profile driver)")], None
    want = hw.pick_platform_profile(policy.PLATFORM_PROFILE[mode], pp["choices"]) if mode else None
    st = OK if want and pp["profile"] == want else (FAILED if want else UNKNOWN)
    return [lever("platform-profile", st, expected=want, actual=pp["profile"], choices=pp["choices"])], pp


def section_rapl(is_root):
    levers, zones = [], []
    applied = sysfs.read_json(os.path.join(paths.RUN_DIR, "applied.json"), {}) or {}
    by_lever = {r["lever"]: r for r in applied.get("rapl", [])}
    for z in rapl.package_zones():
        zi = {"id": z["id"], "interface": z["interface"], "enabled": z["enabled"], "constraints": {}}
        for kind, c in z["constraints"].items():
            ci = {"limit_uw": sysfs.read_int(c["file"]), "max_uw": sysfs.read_int(c["max_file"]),
                  "time_window_us": sysfs.read_int(c["window_file"])}
            if is_root:
                ci["lock_probe"] = rapl.probe_lock(z["dir"], c["index"])
            zi["constraints"][kind] = ci
            r = by_lever.get(f"rapl:{z['id']}:{kind}")
            if ci.get("lock_probe") == "locked":
                levers.append(lever(f"rapl:{z['id']}:{kind}", LOCKED, "locked by firmware", actual=ci["limit_uw"]))
            elif r:
                levers.append(lever(f"rapl:{z['id']}:{kind}", r["status"], r.get("detail"), expected=r.get("target_uw"),
                                    actual=ci["limit_uw"], baseline=r.get("baseline_uw")))
            else:
                levers.append(lever(f"rapl:{z['id']}:{kind}", UNKNOWN, "not applied by a kristall tuned profile in this boot",
                                    actual=ci["limit_uw"]))
        zones.append(zi)
    if not zones:
        levers.append(lever("rapl", UNSUP, "no package RAPL zone in /sys/class/powercap"))
    st = sysfs.read_json(rapl.STATE_FILE, {})
    return levers, {"zones": zones, "state": st, "psys": rapl.psys_zone() is not None, "drift_events": applied.get("drift")}


def section_battery():
    bats = [hw.battery_info(b) for b in hw.system_batteries()]
    caps = charge.capability()
    lim = charge.stored_limit()
    levers = []
    if not bats:
        levers.append(lever("charge-limit", NA, "no battery"))
    elif not any(c["method"] for c in caps):
        levers.append(lever("charge-limit", UNSUP, "battery driver has no charge_control_end_threshold / Long_Life"))
    else:
        cur = [b.get("charge_control_end_threshold") for b in bats]
        want = lim if lim is not None else 100
        st = OK if all(c in (None, want) for c in cur) or caps[0]["method"] == "long-life" else FAILED
        levers.append(lever("charge-limit", st, expected=want, actual=cur, methods=caps))
    return levers, {"batteries": bats, "supplies": [{k: p[k] for k in ("name", "type", "scope", "online")} for p in hw.power_supplies()],
                    "on_battery": hw.on_battery()}


def section_devices():
    levers = []
    pci = []
    base = os.path.join(S, "bus/pci/devices")
    for n in sysfs.listdir(base):
        d = os.path.join(base, n)
        drv = os.path.basename(os.path.realpath(os.path.join(d, "driver"))) if os.path.exists(os.path.join(d, "driver")) else None
        e = {"addr": n, "vendor": sysfs.read(os.path.join(d, "vendor")), "device": sysfs.read(os.path.join(d, "device")),
             "class": sysfs.read(os.path.join(d, "class")), "driver": drv,
             "control": sysfs.read(os.path.join(d, "power/control")),
             "runtime_status": sysfs.read(os.path.join(d, "power/runtime_status")),
             "d3cold_allowed": sysfs.read(os.path.join(d, "d3cold_allowed"))}
        link = {}
        for a in ("clkpm", "l0s_aspm", "l1_aspm", "l1_1_aspm", "l1_2_aspm", "l1_1_pcipm", "l1_2_pcipm"):
            v = sysfs.read(os.path.join(d, "link", a))
            if v is not None:
                link[a] = v
        if link:
            e["aspm"] = link
        pci.append(e)
    intel = [p for p in pci if p["vendor"] == "0x8086" and p["driver"] not in RUNTIME_PM_DENY and not (p["class"] or "").startswith("0x0200")]
    if intel:
        auto_n = sum(1 for p in intel if p["control"] == "auto")
        levers.append(lever("pci-runtime-pm", OK if auto_n == len(intel) else FAILED,
                            f"{auto_n}/{len(intel)} eligible Intel devices on 'auto'"))
    else:
        levers.append(lever("pci-runtime-pm", NA, "no eligible Intel PCI devices"))
    aspm_policy = sysfs.read(os.path.join(S, "module/pcie_aspm/parameters/policy"))
    no_l12 = [p["addr"] for p in pci if p.get("aspm") and p["aspm"].get("l1_2_aspm") == "0"]
    levers.append(lever("pcie-aspm", SKIPPED if aspm_policy else UNKNOWN,
                        "left to firmware on purpose; devices without L1.2: " + (", ".join(no_l12) or "none"),
                        actual=aspm_policy, devices_without_l1_2=no_l12))
    usb = []
    ubase = os.path.join(S, "bus/usb/devices")
    for n in sysfs.listdir(ubase):
        d = os.path.join(ubase, n)
        if ":" in n or not os.path.exists(os.path.join(d, "idVendor")):
            continue
        ifc = sorted({sysfs.read(f) for f in glob.glob(os.path.join(d, n + ":*", "bInterfaceClass"))} - {None})
        usb.append({"dev": n, "id": f"{sysfs.read(os.path.join(d, 'idVendor'))}:{sysfs.read(os.path.join(d, 'idProduct'))}",
                    "product": sysfs.read(os.path.join(d, "product")), "removable": sysfs.read(os.path.join(d, "removable")),
                    "control": sysfs.read(os.path.join(d, "power/control")), "interfaces": ifc,
                    "runtime_status": sysfs.read(os.path.join(d, "power/runtime_status"))})
    fixed = [u for u in usb if u["removable"] == "fixed" and "03" not in u["interfaces"] and u["interfaces"] != ["09"]]
    if fixed:
        n_auto = sum(1 for u in fixed if u["control"] == "auto")
        levers.append(lever("usb-autosuspend", OK if n_auto == len(fixed) else FAILED,
                            f"{n_auto}/{len(fixed)} internal non-input USB devices on 'auto' (external devices untouched)"))
    else:
        levers.append(lever("usb-autosuspend", NA, "no internal non-input USB devices"))
    apst = sysfs.read_int(os.path.join(S, "module/nvme_core/parameters/default_ps_max_latency_us"))
    nvme = []
    for n in sysfs.listdir(os.path.join(S, "class/nvme")):
        d = os.path.join(S, "class/nvme", n)
        nvme.append({"name": n, "model": sysfs.read(os.path.join(d, "model")), "firmware": sysfs.read(os.path.join(d, "firmware_rev")),
                     "latency_tolerance_us": sysfs.read(os.path.join(d, "power/pm_qos_latency_tolerance_us"))})
    levers.append(lever("nvme-apst", OK if apst else (FAILED if apst == 0 else UNKNOWN) if nvme else NA,
                        "APST enabled by the kernel (default_ps_max_latency_us)" if apst else None, actual=apst))
    hda = sysfs.read(os.path.join(S, "module/snd_hda_intel/parameters/power_save"))
    levers.append(lever("audio-power-save", OK if hda and hda not in ("0", "-1") else (UNSUP if hda is None else FAILED),
                        expected="10 (tuned [audio])", actual=hda))
    wifi = []
    for n in sysfs.listdir(os.path.join(S, "class/net")):
        if os.path.isdir(os.path.join(S, "class/net", n, "wireless")) or os.path.isdir(os.path.join(S, "class/net", n, "phy80211")):
            ps = _run(["iw", "dev", n, "get", "power_save"])
            drv = os.path.realpath(os.path.join(S, "class/net", n, "device/driver"))
            wifi.append({"iface": n, "driver": os.path.basename(drv), "power_save": ps})
    if wifi:
        on = [w for w in wifi if w["power_save"] and "on" in w["power_save"].lower()]
        levers.append(lever("wifi-power-save", OK if len(on) == len(wifi) else (UNKNOWN if any(w["power_save"] is None for w in wifi) else FAILED),
                            actual=[w["power_save"] for w in wifi]))
    else:
        levers.append(lever("wifi-power-save", NA, "no wireless interface"))
    bt = sysfs.read(os.path.join(S, "module/btusb/parameters/enable_autosuspend"))
    levers.append(lever("bluetooth-autosuspend", OK if bt == "Y" else (UNKNOWN if bt is None else FAILED), actual=bt))
    nmi = sysfs.read(os.path.join(paths.PROC, "sys/kernel/nmi_watchdog"))
    levers.append(lever("nmi-watchdog-off", OK if nmi == "0" else (UNKNOWN if nmi is None else FAILED), actual=nmi))
    return levers, {"pci": pci, "usb": usb, "nvme": nvme, "wifi": wifi,
                    "aspm_policy": aspm_policy, "nvme_default_ps_max_latency_us": apst}


RUNTIME_PM_DENY = {"mei_me", "xhci_hcd", "e1000e", "snd_hda_intel", "snd_sof_pci_intel_tgl", "i915", "xe",
                   "nouveau", "nvidia", "amdgpu", "radeon"}


def section_graphics():
    cards = []
    for c in hw.drm_cards():
        d = os.path.join(S, "class/drm", c["card"])
        gt = os.path.join(d, "gt/gt0")
        info = {"card": c["card"], "driver": c["driver"],
                "rc6_enable": sysfs.read(os.path.join(gt, "rc6_enable")) or sysfs.read(os.path.join(d, "power/rc6_enable")),
                "freq_mhz": {k: sysfs.read_int(os.path.join(d, f"gt_{k}_freq_mhz")) for k in ("min", "max", "boost", "act", "RP0", "RPn")},
                "connectors": []}
        for con in c["connectors"]:
            entry = {"name": con["name"], "status": con["status"], "enabled": con["enabled"]}
            try:
                with open(os.path.join(con["dir"], "edid"), "rb") as f:
                    e = hw.parse_edid(f.read())
                if e:
                    entry["edid"] = e
            except OSError:
                pass
            info["connectors"].append(entry)
        cards.append(info)
    params = {}
    for drv in ("i915", "xe"):
        for p in ("enable_psr", "enable_fbc", "enable_dc", "enable_guc", "enable_dpcd_backlight", "enable_psr2_sel_fetch"):
            v = sysfs.read(os.path.join(S, "module", drv, "parameters", p))
            if v is not None:
                params[f"{drv}.{p}"] = v
    psr = None
    for f in glob.glob(paths.host("/sys/kernel/debug/dri/*/i915_edp_psr_status")) + \
            glob.glob(paths.host("/sys/kernel/debug/dri/*/*/i915_psr_status")):
        psr = (psr or {})
        psr[f.split("/debug/")[-1]] = (sysfs.read(f) or "")[:600]
    drrs = {}
    for f in glob.glob(paths.host("/sys/kernel/debug/dri/*/i915_drrs_status")):
        drrs[f.split("/debug/")[-1]] = (sysfs.read(f) or "")[:600]
    panel = hw.internal_panels()
    levers = [lever("panel-self-refresh", OK if psr and any("enabled" in v.lower() for v in psr.values()) else UNKNOWN,
                    "driver default kept (never forced); status from debugfs (root only)", actual=psr)]
    return levers, {"cards": cards, "params": params, "psr_status": psr, "drrs_status": drrs or None,
                    "internal_panels": [p["name"] for p in panel], "backlights": hw.backlights()}


def section_memory():
    mi = sysfs.read(os.path.join(paths.PROC, "meminfo"), "") or ""
    total = re.search(r"MemTotal:\s+(\d+)", mi)
    zram = []
    for n in sysfs.listdir(os.path.join(S, "block")):
        if n.startswith("zram"):
            d = os.path.join(S, "block", n)
            zram.append({"dev": n, "disksize": sysfs.read_int(os.path.join(d, "disksize")),
                         "algorithm": sysfs.read(os.path.join(d, "comp_algorithm")), "mm_stat": sysfs.read(os.path.join(d, "mm_stat"))})
    sysctl = {k: sysfs.read(os.path.join(paths.PROC, "sys", k.replace(".", "/"))) for k in (
        "vm.swappiness", "vm.page-cluster", "vm.watermark_boost_factor", "vm.dirty_writeback_centisecs",
        "kernel.split_lock_mitigate")}
    want_size = int(total.group(1)) * 1024 if total else None
    lv = [lever("zram", OK if zram and want_size and abs(zram[0]["disksize"] - want_size) < want_size * 0.1 else (UNKNOWN if not zram else WARN),
                expected="zram-size = ram", actual=[z["disksize"] for z in zram]),
          lever("swappiness", OK if sysctl["vm.swappiness"] == "180" else FAILED, expected="180", actual=sysctl["vm.swappiness"])]
    return lv, {"mem_total_kb": int(total.group(1)) if total else None, "zram": zram, "sysctl": sysctl,
                "thp": sysfs.read(os.path.join(S, "kernel/mm/transparent_hugepage/enabled")),
                "mglru": sysfs.read(os.path.join(S, "kernel/mm/lru_gen/enabled"))}


def section_services():
    units = {u: _unit_active(u) for u in ("tuned.service", "tuned-ppd.service", "kristall-power.service",
                                          "power-profiles-daemon.service", "thermald.service", "intel_lpmd.service",
                                          "tlp.service", "auto-cpufreq.service", "systemd-oomd.service")}
    levers = []
    t = units["tuned.service"]
    levers.append(lever("tuned", OK if t == "active" else (UNKNOWN if t == "unknown" else FAILED), actual=t))
    ppd_conf = sysfs.read(os.path.join(paths.TUNED_DIR, "ppd.conf"), "") or ""
    levers.append(lever("ppd-mapping", OK if "kristall-balanced-battery" in ppd_conf else FAILED,
                        "/etc/tuned/ppd.conf maps the three modes to kristall-* profiles"))
    conflicts = [u for u in ("power-profiles-daemon.service", "tlp.service", "auto-cpufreq.service") if units[u] == "active"]
    levers.append(lever("no-conflicting-daemons", FAILED if conflicts else OK, ", ".join(conflicts) or None))
    gm = paths.host("/etc/gamemode.ini")
    have_gm = os.path.exists(gm) and (bool(shutil.which("gamemoded")) or bool(paths.ROOT))
    levers.append(lever("gamemode", OK if have_gm else FAILED,
                        "games request full power through GameMode" if have_gm else "GameMode or /etc/gamemode.ini missing"))
    eslice = sysfs.read(paths.host("/sys/fs/cgroup/kristall.slice/kristall-background.slice/cpuset.cpus")) or \
        sysfs.read(paths.host("/run/systemd/generator/kristall-background.slice.d/50-kristall-ecores.conf"))
    hyb = hw.hybrid_layout()
    levers.append(lever("background-on-e-cores", (OK if eslice else UNKNOWN) if hyb else NA,
                        None if hyb else "not a hybrid CPU", actual=eslice))
    return levers, {"units": units, "tuned_active_profile": status.tuned_state()[0], "ppd_base_profile": status.tuned_state()[1]}


def measure_idle(seconds):
    """Residency of each cpuidle state, wakeup-causing processes and interrupts over `seconds`."""
    def idle_times():
        out = {}
        for cpu in hw.online_cpus() or [0]:
            d = os.path.join(hw.CPU_DIR, f"cpu{cpu}", "cpuidle")
            for st in sysfs.listdir(d):
                name = sysfs.read(os.path.join(d, st, "name"))
                t = sysfs.read_int(os.path.join(d, st, "time"))
                if name and t is not None:
                    out[name] = out.get(name, 0) + t
        return out

    def proc_switches():
        out = {}
        for pid in os.listdir(paths.PROC) if os.path.isdir(paths.PROC) else []:
            if not pid.isdigit():
                continue
            txt = sysfs.read(os.path.join(paths.PROC, pid, "status"))
            if not txt:
                continue
            m = re.search(r"^Name:\s*(.*)$", txt, re.M)
            v = re.search(r"^voluntary_ctxt_switches:\s*(\d+)", txt, re.M)
            nv = re.search(r"^nonvoluntary_ctxt_switches:\s*(\d+)", txt, re.M)
            if m and v and nv:
                out[pid] = (m.group(1), int(v.group(1)) + int(nv.group(1)))
        return out

    def irqs():
        out = {}
        for ln in (sysfs.read(os.path.join(paths.PROC, "interrupts"), "") or "").splitlines()[1:]:
            parts = ln.split()
            if not parts:
                continue
            nums = [int(x) for x in parts[1:] if x.isdigit()]
            label = " ".join(p for p in parts[1 + len(nums):])
            out[parts[0].rstrip(":") + (" " + label if label else "")] = sum(nums)
        return out

    def pkg_cstates():
        f = paths.host("/sys/kernel/debug/pmc_core/package_cstate_show")
        txt = sysfs.read(f)
        if not txt:
            return None
        return {m.group(1).strip(): int(m.group(2)) for m in re.finditer(r"^(Package C\d+\w*)\s*:\s*(\d+)", txt, re.M)}

    a_idle, a_proc, a_irq, a_pkg = idle_times(), proc_switches(), irqs(), pkg_cstates()
    t0 = time.monotonic()
    time.sleep(seconds)
    dt = time.monotonic() - t0
    b_idle, b_proc, b_irq, b_pkg = idle_times(), proc_switches(), irqs(), pkg_cstates()
    ncpu = max(len(hw.online_cpus()), 1)
    residency = {k: round((b_idle.get(k, 0) - v) / 1e6 / dt / ncpu, 4) for k, v in a_idle.items()}
    wake = sorted(((b_proc[p][0], (b_proc[p][1] - a_proc[p][1]) / dt) for p in b_proc if p in a_proc),
                  key=lambda x: -x[1])[:20]
    irq = sorted(((k, (b_irq.get(k, 0) - v) / dt) for k, v in a_irq.items()), key=lambda x: -x[1])[:15]
    pkg = None
    if a_pkg and b_pkg:
        pkg = {k: round((b_pkg.get(k, 0) - v) / 1e6 / dt, 4) for k, v in a_pkg.items()}
    deep = sum(v for k, v in residency.items() if re.match(r"C(6|7|8|9|10)", k))
    s0ix = {k: sysfs.read_int(os.path.join(S, "devices/system/cpu/cpuidle", k)) for k in (
        "low_power_idle_cpu_residency_us", "low_power_idle_system_residency_us")}
    susp = {n: sysfs.read(os.path.join(S, "power/suspend_stats", n)) for n in sysfs.listdir(os.path.join(S, "power/suspend_stats"))}
    return {"seconds": round(dt, 2), "cpuidle_driver": sysfs.read(os.path.join(S, "devices/system/cpu/cpuidle/current_driver")),
            "core_state_residency": residency, "deep_core_residency": round(deep, 4), "package_cstate_residency": pkg,
            "wakeups_per_s": [{"process": n, "per_s": round(r, 1)} for n, r in wake if r > 0],
            "interrupts_per_s": [{"irq": n, "per_s": round(r, 1)} for n, r in irq if r > 0],
            "s0ix": s0ix, "mem_sleep": sysfs.read(os.path.join(S, "power/mem_sleep")), "suspend_stats": susp or None,
            "load_note": "measured while the machine may be in use; compare runs with the screen locked"}


def idle_lever(idle):
    if not idle:
        return lever("deep-idle", UNKNOWN, "not measured")
    if not idle["core_state_residency"]:
        return lever("deep-idle", UNSUP, "no cpuidle states visible")
    deep = idle["deep_core_residency"]
    pkg = idle.get("package_cstate_residency") or {}
    pk_deep = sum(v for k, v in pkg.items() if re.search(r"C(8|9|10)", k))
    detail = f"deep core C-states {round(deep * 100, 1)} % of time" + (f", package C8+ {round(pk_deep * 100, 1)} %" if pkg else "")
    return lever("deep-idle", OK if deep >= 0.80 else WARN, detail)


# ------------------------------------------------------------------------------ report
def run_system(idle_seconds=10.0):
    is_root = os.geteuid() == 0
    active, base = status.tuned_state()
    parsed = policy.parse_tuned_profile(active) if active else None
    mode, on_bat = parsed if parsed else (None, hw.on_battery())
    report = {"schema": SCHEMA, "kind": "kristall-power-doctor", "time": logbook.now_iso(), "as_root": is_root,
              "mode": mode, "on_battery": on_bat, "levers": []}
    report["system"] = section_system()
    sections = [("cpu", lambda: section_cpu(mode, on_bat)), ("platform_profile", lambda: section_platform_profile(mode)),
                ("rapl", lambda: section_rapl(is_root)), ("battery", section_battery), ("devices", section_devices),
                ("graphics", section_graphics), ("memory", section_memory), ("services", section_services)]
    for key, fn in sections:
        try:
            lv, data = fn()
        except Exception as e:  # noqa: BLE001 - a broken section must not lose the rest of the report
            lv, data = [lever(key, FAILED, f"doctor error: {e!r}"[:300])], None
        report["levers"].extend(lv)
        report[key] = data
    report["temperatures"] = hw.temperatures()
    report["thermal_zones"] = hw.thermal_zones()
    report["hwmon"] = hw.hwmon()
    if is_root:
        report["power_w"] = status.rapl_power_w(1.0)
    idle = measure_idle(idle_seconds) if idle_seconds > 0 else None
    report["idle"] = idle
    report["levers"].append(idle_lever(idle))
    report["events"] = logbook.tail(system.EVENTS_LOG, 300)
    return report


def add_session(report):
    sess = sysfs.read_json(paths.session_state_file(), None)
    report["session"] = sess
    if sess is None:
        why = "session daemon state not found (not running, or not run as the owner)"
        report["levers"] += [lever("automatic-mode", UNKNOWN, why), lever("refresh-rate", UNKNOWN, why),
                             lever("glass-quality", UNKNOWN, why)]
    else:
        report["levers"].append(lever("automatic-mode", OK if sess.get("automatic") else SKIPPED, sess.get("reason")))
        r = sess.get("refresh") or {}
        panel = r.get("panel") or {}
        if r.get("managed") is False and "no internal panel" in (r.get("reason") or ""):
            report["levers"].append(lever("refresh-rate", NA, r.get("reason")))
        elif r.get("managed") is False:
            report["levers"].append(lever("refresh-rate", SKIPPED, r.get("reason"), actual=panel.get("refresh_hz")))
        elif panel.get("available_hz") and len(panel["available_hz"]) < 2:
            report["levers"].append(lever("refresh-rate", UNSUP, "panel offers a single refresh rate", actual=panel.get("refresh_hz")))
        else:
            report["levers"].append(lever("refresh-rate", OK if r.get("managed") else UNKNOWN, expected=r.get("target"),
                                          actual=panel.get("refresh_hz"), available=panel.get("available_hz")))
        g = sess.get("glass_hint")
        report["levers"].append(lever("glass-quality", OK if g else (UNKNOWN if not sess.get("glass_connected") else FAILED),
                                      None if sess.get("glass_connected") else "glass effect socket not connected", actual=g))
    report["session_log"] = logbook.tail(os.path.join(paths.user_state_dir(), "log.jsonl"), 300)
    return report


SYMBOL = {OK: "[OK]", UNSUP: "[--]", NA: "[--]", SKIPPED: "[..]", LOCKED: "[LK]", FAILED: "[!!]", WARN: "[ !]", UNKNOWN: "[??]"}
STATUS_TEXT = {
    OK: ("aktiv", "applied"), UNSUP: ("von dieser Hardware nicht unterstützt", "unsupported on this hardware"),
    NA: ("nicht zutreffend", "not applicable"), SKIPPED: ("bewusst ausgelassen", "skipped"),
    LOCKED: ("von der Firmware gesperrt", "locked by firmware"), FAILED: ("fehlgeschlagen", "failed"),
    WARN: ("auffällig", "needs attention"), UNKNOWN: ("unbekannt", "unknown"), "reverted": ("zurückgesetzt", "reverted"),
}


def summary(report):
    lines = []
    dmi = (report.get("system") or {}).get("dmi") or {}
    machine = " ".join(x for x in (dmi.get("sys_vendor"), dmi.get("product_name")) if x) or "?"
    for lang, title in ((0, "Kristall Energie-Diagnose"), (1, "Kristall power diagnosis")):
        lines.append(f"== {title} ({report['time']}) ==")
        lines.append(("Gerät: " if lang == 0 else "Machine: ") + machine + " | " + str((report.get("system") or {}).get("cpu_model")))
        mode = report.get("mode")
        lines.append(("Modus: " if lang == 0 else "Mode: ") + (policy.NAMES[mode]["de" if lang == 0 else "en"] if mode else "?") +
                     (" / Akku" if report.get("on_battery") and lang == 0 else " / battery" if report.get("on_battery") else ""))
        counts = {}
        for lv in report["levers"]:
            counts[lv["status"]] = counts.get(lv["status"], 0) + 1
            txt = STATUS_TEXT.get(lv["status"], (lv["status"], lv["status"]))[lang]
            extra = f" — {lv['detail']}" if lv.get("detail") else ""
            exp, act = lv.get("expected"), lv.get("actual")
            if lv["lever"].startswith("rapl:"):
                exp = f"{exp / 1e6:g} W" if isinstance(exp, int) else exp
                act = f"{act / 1e6:g} W" if isinstance(act, int) else act
            if exp is not None:
                extra += f" ({'soll' if lang == 0 else 'expected'} {exp}, {'ist' if lang == 0 else 'actual'} {act})"
            elif act is not None:
                extra += f" ({'ist' if lang == 0 else 'actual'} {act})"
            lines.append(f"  {SYMBOL.get(lv['status'], '[  ]')} {lv['lever']}: {txt}{extra}")
        idle = report.get("idle") or {}
        if idle.get("wakeups_per_s"):
            top = ", ".join(f"{w['process']} {w['per_s']}/s" for w in idle["wakeups_per_s"][:5])
            lines.append(("  Häufigste Aufwecker: " if lang == 0 else "  Top wake-ups: ") + top)
        lines.append(("  Zusammenfassung: " if lang == 0 else "  Summary: ") +
                     ", ".join(f"{k} {v}" for k, v in sorted(counts.items())))
        lines.append("")
    return "\n".join(lines)
