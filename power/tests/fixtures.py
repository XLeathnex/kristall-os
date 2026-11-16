# SPDX-License-Identifier: GPL-3.0-or-later
"""Fake hardware: builds trees that imitate the kernel interfaces kristall-power uses, for several
laptop personalities. Kernel behaviour that plain files cannot show (EACCES on a locked RAPL
limit, a driver that rounds a value) is injected through the KRISTALL_POWER_FAULTS map."""
import json
import os
import struct

W = 1_000_000  # microwatts per watt


def _w(root, rel, value, mode=None):
    p = os.path.join(root, rel.lstrip("/"))
    os.makedirs(os.path.dirname(p), exist_ok=True)
    data = value if isinstance(value, bytes) else (str(value) + ("" if str(value).endswith("\n") else "\n")).encode()
    with open(p, "wb") as f:
        f.write(data)
    return p


def edid(width, height, refresh, vendor="BOE", product=0x0A4F, name="Panel"):
    hb, vb = 160, 56
    pclk = round((width + hb) * (height + vb) * refresh / 10_000)
    assert pclk < 65536
    b = bytearray(128)
    b[0:8] = b"\x00\xff\xff\xff\xff\xff\xff\x00"
    m = ((ord(vendor[0]) - 64) << 10) | ((ord(vendor[1]) - 64) << 5) | (ord(vendor[2]) - 64)
    b[8], b[9] = m >> 8, m & 0xFF
    b[10], b[11] = product & 0xFF, product >> 8
    b[18], b[19] = 1, 4
    d = 54
    b[d:d + 2] = struct.pack("<H", pclk)
    b[d + 2] = width & 0xFF
    b[d + 3] = hb & 0xFF
    b[d + 4] = ((width >> 8) << 4) | (hb >> 8)
    b[d + 5] = height & 0xFF
    b[d + 6] = vb & 0xFF
    b[d + 7] = ((height >> 8) << 4) | (vb >> 8)
    d2 = 72
    b[d2:d2 + 5] = b"\x00\x00\x00\xfc\x00"
    b[d2 + 5:d2 + 18] = (name.encode() + b"\n").ljust(13, b" ")[:13]
    b[127] = (-sum(b[:127])) & 0xFF
    return bytes(b)


PERSONALITIES = {
    # 16" thin-and-light, i9-13900H, OLED 120 Hz, vendor platform profile with quiet mode,
    # both RAPL interfaces writable, charge thresholds (start+end).
    "thin-oled": dict(hybrid=True, pp=["low-power", "quiet", "balanced", "performance"], pp_cur="balanced",
                      msr=(45, 115), mmio=(45, 115), battery=dict(start=True, end=True), ac=True,
                      panel=(2880, 1800, 60), backlight="raw", fan=True),
    # Firmware locked the MSR limits (EACCES), no MMIO interface, no platform profile.
    "locked": dict(hybrid=True, pp=None, msr=(55, 115), mmio=None, lock_msr=True, battery=dict(start=False, end=True),
                   ac=True, panel=(2880, 1800, 60), backlight="raw"),
    # Firmware resets limits on resume/plug (the harness rewrites the files to simulate it).
    "reset-on-resume": dict(hybrid=True, pp=["low-power", "balanced", "performance"], pp_cur="balanced",
                            msr=(45, 115), mmio=(64, 115), battery=dict(start=True, end=True), ac=True,
                            panel=(2880, 1800, 60), backlight="raw"),
    # Cheap 60 Hz LCD laptop: no platform profile, MSR only, no charge-limit support.
    "lcd60-nopp": dict(hybrid=True, pp=None, msr=(35, 90), mmio=None, battery=dict(start=False, end=False),
                       ac=True, panel=(1920, 1200, 60), backlight="firmware"),
    # Lenovo-style firmware conservation mode only (charge_types Long_Life).
    "longlife": dict(hybrid=True, pp=["low-power", "balanced", "performance"], pp_cur="balanced", msr=(45, 115),
                     mmio=(45, 115), battery=dict(start=False, end=False, long_life=True), ac=True,
                     panel=(2880, 1800, 60), backlight="raw"),
    # Desktop: no battery, no AC device, not hybrid, no platform profile, no backlight, no eDP.
    "desktop": dict(hybrid=False, pp=None, msr=(65, 150), mmio=None, battery=None, ac=False, panel=None,
                    backlight=None),
}


def build(root, personality, on_battery=False, percent=64):
    cfg = PERSONALITIES[personality]
    faults = {}
    ncpu = 20 if cfg["hybrid"] else 8
    S = "/sys"
    _w(root, "/proc/cpuinfo", "".join(
        f"processor\t: {i}\nvendor_id\t: GenuineIntel\nmodel name\t: 13th Gen Intel(R) Core(TM) i9-13900H\nflags\t\t: fpu hwp hwp_epp\n\n"
        for i in range(ncpu)))
    _w(root, "/proc/cmdline", "BOOT_IMAGE=/vmlinuz root=UUID=x rhgb quiet")
    _w(root, "/proc/stat", "cpu  100 0 50 10000 10 0 0 0 0 0\n")
    _w(root, "/proc/meminfo", "MemTotal:       16000000 kB\nMemFree:  8000000 kB\n")
    _w(root, "/proc/interrupts", "           CPU0       CPU1\n  0:         10          0   IO-APIC   2-edge      timer\n")
    _w(root, "/proc/sys/kernel/nmi_watchdog", "0")
    _w(root, "/proc/sys/vm/swappiness", "180")
    _w(root, "/proc/1/status", "Name:\tsystemd\nvoluntary_ctxt_switches:\t100\nnonvoluntary_ctxt_switches:\t5\n")
    _w(root, "/usr/lib/os-release", 'PRETTY_NAME="Kristall OS 45"\nVERSION_ID=45\n')
    cpu = f"{S}/devices/system/cpu"
    _w(root, f"{cpu}/online", f"0-{ncpu - 1}")
    _w(root, f"{cpu}/intel_pstate/status", "active")
    _w(root, f"{cpu}/intel_pstate/no_turbo", "0")
    _w(root, f"{cpu}/cpuidle/current_driver", "intel_idle")
    _w(root, f"{cpu}/cpuidle/low_power_idle_system_residency_us", "0")
    if cfg["hybrid"]:
        _w(root, f"{S}/devices/cpu_core/cpus", "0-11")
        _w(root, f"{S}/devices/cpu_atom/cpus", "12-19")
    for i in range(ncpu):
        pol = f"{cpu}/cpufreq/policy{i}"
        _w(root, f"{pol}/energy_performance_preference", "balance_performance")
        _w(root, f"{pol}/energy_performance_available_preferences", "default performance balance_performance balance_power power")
        _w(root, f"{pol}/scaling_governor", "powersave")
        _w(root, f"{pol}/scaling_driver", "intel_pstate")
        _w(root, f"{cpu}/cpu{i}/power/energy_perf_bias", "6")
        for s, (name, t) in enumerate((("POLL", 0), ("C1E", 1000), ("C6", 50000), ("C10", 900000))):
            _w(root, f"{cpu}/cpu{i}/cpuidle/state{s}/name", name)
            _w(root, f"{cpu}/cpu{i}/cpuidle/state{s}/time", t)
    # platform profile
    if cfg["pp"]:
        _w(root, f"{S}/firmware/acpi/platform_profile", cfg["pp_cur"])
        _w(root, f"{S}/firmware/acpi/platform_profile_choices", " ".join(cfg["pp"]))
        _w(root, f"{S}/class/platform-profile/platform-profile-0/name", "vendor-wmi")
        _w(root, f"{S}/class/platform-profile/platform-profile-0/choices", " ".join(cfg["pp"]))
        _w(root, f"{S}/class/platform-profile/platform-profile-0/profile", cfg["pp_cur"])
    # RAPL
    for zid, lim in (("intel-rapl:0", cfg["msr"]), ("intel-rapl-mmio:0", cfg["mmio"])):
        if not lim:
            continue
        z = f"{S}/class/powercap/{zid}"
        _w(root, f"{z}/name", "package-0")
        _w(root, f"{z}/enabled", "0" if cfg.get("lock_msr") and "mmio" not in zid else "1")
        _w(root, f"{z}/energy_uj", "123456789")
        for i, (cname, val, mx) in enumerate((("long_term", lim[0], lim[0]), ("short_term", lim[1], 0), ("peak_power", 200, 0))):
            _w(root, f"{z}/constraint_{i}_name", cname)
            _w(root, f"{z}/constraint_{i}_power_limit_uw", val * W)
            _w(root, f"{z}/constraint_{i}_max_power_uw", mx * W)
            _w(root, f"{z}/constraint_{i}_time_window_us", 28000000 if i == 0 else 2440)
            if cfg.get("lock_msr") and "mmio" not in zid:
                faults[f"{z}/constraint_{i}_power_limit_uw"] = {"errno": 13}
        if "mmio" not in zid:
            _w(root, f"{S}/class/powercap/intel-rapl:0:0/name", "core")
            _w(root, f"{S}/class/powercap/intel-rapl:0:0/constraint_0_name", "long_term")
            _w(root, f"{S}/class/powercap/intel-rapl:0:0/constraint_0_power_limit_uw", 0)
            _w(root, f"{S}/class/powercap/intel-rapl:1/name", "psys")
            _w(root, f"{S}/class/powercap/intel-rapl:1/energy_uj", "999")
    # power supplies
    ps = f"{S}/class/power_supply"
    if cfg["ac"]:
        _w(root, f"{ps}/ADP1/type", "Mains")
        _w(root, f"{ps}/ADP1/online", "0" if on_battery else "1")
    if cfg["battery"]:
        b = f"{ps}/BAT0"
        _w(root, f"{b}/type", "Battery")
        _w(root, f"{b}/scope", "System")
        _w(root, f"{b}/present", "1")
        _w(root, f"{b}/status", "Discharging" if on_battery else "Charging")
        _w(root, f"{b}/capacity", percent)
        _w(root, f"{b}/energy_full_design", 99_900_000)
        _w(root, f"{b}/energy_full", 92_000_000)
        _w(root, f"{b}/energy_now", int(92_000_000 * percent / 100))
        _w(root, f"{b}/power_now", 7_400_000 if on_battery else 30_000_000)
        _w(root, f"{b}/cycle_count", 41)
        _w(root, f"{b}/technology", "Li-poly")
        _w(root, f"{b}/manufacturer", "ACME")
        _w(root, f"{b}/model_name", "Cell 4S")
        if cfg["battery"].get("end"):
            _w(root, f"{b}/charge_control_end_threshold", 100)
        if cfg["battery"].get("start"):
            _w(root, f"{b}/charge_control_start_threshold", 95)
        if cfg["battery"].get("long_life"):
            _w(root, f"{b}/charge_types", "[Standard] Long_Life")
        # a wireless mouse battery must be ignored everywhere
        _w(root, f"{ps}/hidpp_battery_0/type", "Battery")
        _w(root, f"{ps}/hidpp_battery_0/scope", "Device")
        _w(root, f"{ps}/hidpp_battery_0/capacity", 5)
    # thermal, fans
    _w(root, f"{S}/class/hwmon/hwmon3/name", "coretemp")
    _w(root, f"{S}/class/hwmon/hwmon3/temp1_label", "Package id 0")
    _w(root, f"{S}/class/hwmon/hwmon3/temp1_input", 52000)
    _w(root, f"{S}/class/hwmon/hwmon3/temp2_label", "Core 0")
    _w(root, f"{S}/class/hwmon/hwmon3/temp2_input", 49000)
    _w(root, f"{S}/class/thermal/thermal_zone0/type", "x86_pkg_temp")
    _w(root, f"{S}/class/thermal/thermal_zone0/temp", 52000)
    if cfg.get("fan"):
        _w(root, f"{S}/class/hwmon/hwmon5/name", "vendor_fan")
        _w(root, f"{S}/class/hwmon/hwmon5/fan1_input", 0)
    # graphics / panel
    card = f"{S}/class/drm/card1"
    os.makedirs(os.path.join(root, f"{S}/bus/pci/drivers/i915".lstrip("/")), exist_ok=True)
    os.makedirs(os.path.join(root, f"{card}/device".lstrip("/")), exist_ok=True)
    link = os.path.join(root, f"{card}/device/driver".lstrip("/"))
    if not os.path.islink(link):
        os.symlink(os.path.join(root, f"{S}/bus/pci/drivers/i915".lstrip("/")), link)
    _w(root, f"{card}/gt/gt0/rc6_residency_ms", 1000)
    _w(root, f"{card}/gt_max_freq_mhz", 1500)
    if cfg["panel"]:
        w, h, r = cfg["panel"]
        _w(root, f"{S}/class/drm/card1-eDP-1/status", "connected")
        _w(root, f"{S}/class/drm/card1-eDP-1/enabled", "enabled")
        _w(root, f"{S}/class/drm/card1-eDP-1/edid", edid(w, h, r))
    if cfg["backlight"]:
        _w(root, f"{S}/class/backlight/intel_backlight/type", cfg["backlight"])
        _w(root, f"{S}/class/backlight/intel_backlight/max_brightness", 400)
        _w(root, f"{S}/class/backlight/intel_backlight/brightness", 300)
    # PCI / USB
    for addr, cls, drv, ctl in (("0000:00:14.0", "0x0c0330", "xhci_hcd", "on"), ("0000:00:14.3", "0x028000", "iwlwifi", "on"),
                                ("0000:00:16.0", "0x078000", "mei_me", "on"), ("0000:00:12.0", "0x070000", "intel_ish_ipc", "auto")):
        d = f"{S}/bus/pci/devices/{addr}"
        _w(root, f"{d}/vendor", "0x8086")
        _w(root, f"{d}/device", "0x51ed")
        _w(root, f"{d}/class", cls)
        _w(root, f"{d}/power/control", ctl)
        _w(root, f"{d}/power/runtime_status", "active")
        _w(root, f"{d}/link/l1_2_aspm", "1")
        dl = os.path.join(root, f"{S}/bus/pci/drivers/{drv}".lstrip("/"))
        os.makedirs(dl, exist_ok=True)
        if not os.path.islink(os.path.join(root, f"{d}/driver".lstrip("/"))):
            os.symlink(dl, os.path.join(root, f"{d}/driver".lstrip("/")))
    for dev, removable, ifc, ctl in (("3-10", "fixed", "e0", "auto"), ("3-6", "fixed", "0e", "on"), ("3-1", "removable", "03", "on")):
        d = f"{S}/bus/usb/devices/{dev}"
        _w(root, f"{d}/idVendor", "8087")
        _w(root, f"{d}/idProduct", "0033")
        _w(root, f"{d}/removable", removable)
        _w(root, f"{d}/power/control", ctl)
        _w(root, f"{d}/{dev}:1.0/bInterfaceClass", ifc)
    _w(root, f"{S}/module/nvme_core/parameters/default_ps_max_latency_us", 100000)
    _w(root, f"{S}/class/nvme/nvme0/model", "ACME NVMe 1TB")
    _w(root, f"{S}/module/snd_hda_intel/parameters/power_save", 10)
    _w(root, f"{S}/module/btusb/parameters/enable_autosuspend", "Y")
    _w(root, f"{S}/module/pcie_aspm/parameters/policy", "[default] performance powersave powersupersave")
    _w(root, f"{S}/block/zram0/disksize", 16_384_000_000)
    _w(root, f"{S}/block/zram0/comp_algorithm", "[lzo-rle] zstd")
    _w(root, f"{S}/class/dmi/id/sys_vendor", "ACME")
    _w(root, f"{S}/class/dmi/id/product_name", "Thinbook 16")
    _w(root, f"{S}/class/dmi/id/product_serial", "SECRET-SERIAL")
    # tuned state
    _w(root, "/etc/tuned/active_profile", "kristall-balanced")
    _w(root, "/etc/tuned/ppd_base_profile", "balanced")
    _w(root, "/etc/tuned/ppd.conf", "[battery]\nbalanced=kristall-balanced-battery\n")
    faults_file = os.path.join(root, "faults.json")
    with open(faults_file, "w") as f:
        json.dump(faults, f)
    return faults_file


def set_power(root, on_battery, percent=None):
    S = os.path.join(root, "sys/class/power_supply")
    if os.path.exists(os.path.join(S, "ADP1")):
        _w(root, "/sys/class/power_supply/ADP1/online", "0" if on_battery else "1")
    if os.path.exists(os.path.join(S, "BAT0")):
        _w(root, "/sys/class/power_supply/BAT0/status", "Discharging" if on_battery else "Charging")
        if percent is not None:
            _w(root, "/sys/class/power_supply/BAT0/capacity", percent)


def set_active_profile(root, profile):
    _w(root, "/etc/tuned/active_profile", profile)


def read_uw(root, zone, idx):
    with open(os.path.join(root, f"sys/class/powercap/{zone}/constraint_{idx}_power_limit_uw")) as f:
        return int(f.read())


def write_uw(root, zone, idx, value):
    _w(root, f"/sys/class/powercap/{zone}/constraint_{idx}_power_limit_uw", value)
