# SPDX-License-Identifier: GPL-3.0-or-later
"""The power policy: what Leise / Ausgewogen / Leistung mean, as numbers.

This table is the single source of truth. The tuned profiles in power/tuned/ carry the parts tuned
applies natively (EPP, EPB, turbo, platform profile, sysctl) and the test suite checks that they
agree with this table; the package power limits are applied by `kristall-power` itself because they
must be computed relative to what the firmware set (docs/contracts/power.md §4 has the reasoning).
"""
import os

MODES = ("quiet", "balanced", "performance")
PPD_OF_MODE = {"quiet": "power-saver", "balanced": "balanced", "performance": "performance"}
MODE_OF_PPD = {v: k for k, v in PPD_OF_MODE.items()}
NAMES = {
    "quiet": {"de": "Leise", "en": "Quiet"},
    "balanced": {"de": "Ausgewogen", "en": "Balanced"},
    "performance": {"de": "Leistung", "en": "Performance"},
}


def tuned_profile(mode: str, on_battery: bool) -> str:
    return f"kristall-{mode}" + ("-battery" if on_battery else "")


def parse_tuned_profile(name: str):
    """'kristall-quiet-battery' -> ('quiet', True); anything else -> None."""
    if not name or not name.startswith("kristall-"):
        return None
    rest = name[len("kristall-"):]
    on_battery = rest.endswith("-battery")
    if on_battery:
        rest = rest[: -len("-battery")]
    return (rest, on_battery) if rest in MODES else None


ALL_TUNED_PROFILES = [tuned_profile(m, b) for m in MODES for b in (False, True)]

# --------------------------------------------------------------------------------------------
# Package power limits (RAPL). Each entry: (absolute cap in W, fraction of the firmware value).
# Target = min(firmware value, absolute cap, fraction x firmware value), never below the floor,
# never above the firmware value or the zone's reported maximum. None = leave firmware values.
# Reference: i9-13900H: Processor Base Power 45 W, Maximum Turbo Power 115 W,
# Minimum Assured Power 35 W (Intel ARK).
RAPL_CAPS = {
    ("quiet", False):       {"pl1": (20.0, 0.45), "pl2": (45.0, 0.50)},
    ("quiet", True):        {"pl1": (15.0, 0.35), "pl2": (35.0, 0.40)},
    ("balanced", False):    {"pl1": (45.0, 1.00), "pl2": (90.0, 1.00)},
    ("balanced", True):     {"pl1": (28.0, 0.65), "pl2": (55.0, 0.60)},
    ("performance", False): None,
    ("performance", True):  None,
}
FLOOR_W = {"pl1": 12.0, "pl2": 20.0}
# Readback granularity: RAPL power units are 1/8 W on client parts; a readback within this of
# what we wrote is ours, anything else means firmware/EC changed the limit.
TOLERANCE_UW = 250_000

# --------------------------------------------------------------------------------------------
# What tuned applies (kept here so status/doctor know what to expect).
EPP = {
    ("quiet", False): "balance_power", ("quiet", True): "balance_power",
    ("balanced", False): "balance_performance", ("balanced", True): "balance_power",
    ("performance", False): "performance", ("performance", True): "performance",
}
EPB = {
    ("quiet", False): "balance-power", ("quiet", True): "balance-power",
    ("balanced", False): "normal", ("balanced", True): "balance-power",
    ("performance", False): "performance", ("performance", True): "performance",
}
# First available choice wins (tuned's '|' fallback). 'cool' is deliberately absent from Leise:
# on several vendors it means "spin the fans to keep the chassis cool", the opposite of quiet.
PLATFORM_PROFILE = {
    "quiet": ["quiet", "low-power", "balanced"],
    "balanced": ["balanced"],
    "performance": ["performance", "balanced-performance", "balanced"],
}
TURBO = True  # never disabled: bursts must stay instant in every mode


def rapl_target_uw(cap, baseline_uw: int, max_uw: int, which: str):
    """Return the value to program for one constraint, or None to leave it alone."""
    if not baseline_uw or baseline_uw <= 0:
        return None
    if cap is None:
        return baseline_uw
    abs_w, frac = cap
    t = min(baseline_uw, int(abs_w * 1_000_000), int(frac * baseline_uw))
    t = max(t, int(FLOOR_W[which] * 1_000_000))
    t = min(t, baseline_uw)                    # the floor never raises us above firmware
    if max_uw and max_uw > 0:
        t = min(t, max_uw)
    return t


# --------------------------------------------------------------------------------------------
# Session-side policies.

def glass_hint(effective_mode: str, on_battery: bool) -> str:
    """Quality hint for the glass effect while appearance.glassQuality is 'auto'."""
    if on_battery or effective_mode == "quiet":
        return "efficient"
    return "high"


def refresh_policy(effective_mode: str, on_battery: bool, setting: str) -> str:
    """'max' or 'low' (lowest mode >= 59 Hz at the current resolution).

    setting = power.batteryRefreshRate: 'auto' (lower on battery unless Leistung) | 'max'."""
    if setting == "max" or not on_battery:
        return "max"
    return "max" if effective_mode == "performance" else "low"


# --------------------------------------------------------------------------------------------
# Automatic mode thresholds (session daemon).
_FAST = os.environ.get("KRISTALL_POWER_TEST_FAST") == "1"   # test hook: 1-second timers
BATTERY_BASES = ("quiet", "balanced")   # power.batteryBase: automatic on battery = Leise | Ausgewogen
LOW_BATTERY_ON = 20       # percent: automatic switches to Leise at or below this on battery
LOW_BATTERY_OFF = 25      # hysteresis: back above this (or on mains)
BOOST_CPU_CORES = 4.0     # heavy app scope busy >= 4 logical CPUs ...
BOOST_GPU_BUSY = 0.70     # ... or iGPU >= 70 % busy while the heavy app uses >= 0.5 CPU
BOOST_GPU_APP_CORES = 0.5
BOOST_ON_SAMPLES = 2      # consecutive samples (10 s each) to engage
BOOST_OFF_SAMPLES = 6     # consecutive quiet samples (60 s) to release
SAMPLE_SECONDS = 1 if _FAST else 10      # only while a heavy app runs on mains in automatic mode
LOG_SAMPLE_SECONDS = 1 if _FAST else 60  # thermal log cadence while unlocked (written only under load)
SOURCE_DEBOUNCE_S = 1 if _FAST else 3    # display changes wait until the power source is stable

DEFAULT_HEAVY_APPS = [
    "org.blender.Blender", "blender",
    "org.vinegarhq.Vinegar", "org.vinegarhq.Sober",
    "com.valvesoftware.Steam", "steam",
    "com.heroicgameslauncher.hgl", "net.lutris.Lutris", "org.prismlauncher.PrismLauncher",
]
