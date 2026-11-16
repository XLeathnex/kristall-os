# Contract: `power` — performance, battery, heat, noise

Owner: `power/`. Consumers: shell-core (`Power` service, Control Center), setup (Kristall settings
screen), assistant/hands (`power_mode` tool), glass (quality hint), image (update scheduling).
Status: interface version **1**. Normative; the implementation follows it.

## 1. Pieces

| What | Where | Runs as |
|---|---|---|
| CLI + library | `/usr/bin/kristall-power`, `/usr/lib/kristall/power/kristall_power/` (Python 3, stdlib; the session daemon also uses python3-dbus + GLib) | — |
| Six tuned profiles | `/usr/lib/tuned/profiles/kristall-{quiet,balanced,performance}[-battery]/` (+ `kristall-common`) | tuned |
| PPD mapping | `/etc/tuned/ppd.conf` (§2) | tuned-ppd |
| Profile hook | `script.sh` inside each profile → `kristall-power tuned-hook start\|stop <profile>` | root (tuned) |
| Boot unit | `kristall-power.service` (before tuned: remembers firmware limits, re-applies the charge limit; `ExecStop` gives every power limit back to the firmware) | root |
| Re-apply | `kristall-power-reapply.service` (started by udev on a power-source change, by the system-sleep hook after resume and by the profile hook; applies, re-checks after 2 s and 8 s, exits) | root |
| Charge limit | `kristall-power-charge@<50..100>.service` | root |
| Diagnostics | `kristall-power-doctor.service` (+ `.timer`: 15 min after every boot) | root |
| Session daemon | user unit `kristall-power-session.service` (`graphical-session.target`, D-Bus name `org.kristall.Power1`) | owner |
| Background slice | `kristall-background.slice` (CPUWeight/IOWeight 20; generator `kristall-power-ecores` adds `AllowedCPUs=<E-cores>` on Intel hybrid CPUs); drop-ins put `kristall-update.service` and `kristall-apps-provision.service` into it | — |
| Static config | udev `60-kristall-power.rules`, polkit `50-kristall-power.rules`, sysctl `60-kristall-power.conf`, `zram-generator.conf.d/50-kristall-power.conf`, NetworkManager `conf.d/50-kristall-power.conf`, `/etc/gamemode.ini`, tuned `sleep_interval=10` in `/etc/tuned/tuned-main.conf` | — |
| Presets | system: `kristall-power.service`, `kristall-power-doctor.timer`, `tuned.service`, `tuned-ppd.service`; user: `kristall-power-session.service` | — |

Every unit that changes the machine carries `ConditionKernelCommandLine=!rd.live.image` and
`ConditionPathExists=!/etc/kristall/live`; the tuned hook is a no-op in the live system as well.
Packages added by `power/image/install.sh`: `gamemode` (tuned, tuned-ppd, python3-dbus,
python3-gobject-base are already in the base; `power-profiles-daemon` is removed if present).

## 2. Modes

| Owner sees | PPD profile (D-Bus API the shell uses) | tuned profile on mains | on battery |
|---|---|---|---|
| **Leise** / Quiet | `power-saver` | `kristall-quiet` | `kristall-quiet-battery` |
| **Ausgewogen** / Balanced | `balanced` | `kristall-balanced` | `kristall-balanced-battery` |
| **Leistung** / Performance | `performance` | `kristall-performance` | `kristall-performance-battery` |

Mode changes go through the standard power-profiles API (`org.freedesktop.UPower.PowerProfiles` /
`net.hadess.PowerProfiles`, provided by tuned-ppd; active local users need no password). tuned-ppd
switches between the mains and battery variant by itself when UPower's `OnBattery` changes, so a
mode has a mains and a battery meaning without anyone switching modes. A laptop's own profile
hotkey (if its driver reports it through `platform_profile`) is seen by tuned-ppd as a mode change.

## 3. Automatic mode (default) and manual choices

Setting `power.automatic` (default `true`). Implemented by the session daemon; state in
`$XDG_RUNTIME_DIR/kristall/power.json` (§7.3).

**Automatic** follows the owner's stated priority, "silent and cold while doing tasks": **on
battery it means Leise from the start, on mains Ausgewogen**, with Leistung on mains for games and
genuinely busy heavy apps. Leise keeps turbo and a 35 W (battery) / 45 W (mains) burst limit, so
clicks, app starts and short compiles still feel instant; only sustained load is held back.
The base PPD profile stays Ausgewogen; everything else is a temporary **hold** placed with the
standard `HoldProfile` API (holds never change the base mode, and tuned-ppd drops them if the daemon
dies — the machine then simply runs Ausgewogen):

| Condition | Hold | Released when |
|---|---|---|
| on battery **and** `power.batteryBase` is `"quiet"` (default) | Leise (`auto-battery`) | mains; a manual choice |
| on battery **and** battery ≤ 20 % (`power.lowBatteryQuiet`) | Leise (`auto-low-battery`; with the quiet base the `auto-battery` hold is simply kept — never released and re-placed — and `reason` reports `auto-low-battery`) | ≥ 25 % or mains |
| on mains **and** a GameMode client is registered | Leistung (`auto-game`) | the last game unregisters, or unplug |
| on mains **and** a heavy app (`power.heavyApps`) is *busy*: its systemd scope uses ≥ 4 logical CPUs, or the iGPU is ≥ 70 % busy while the app uses ≥ 0.5 CPU, in 2 consecutive 10-s samples | Leistung (`auto-heavy-app`) | 6 consecutive calm samples (60 s), the app quits, or unplug |

`power.batteryBase` (*addition, 2026-11-16*): `"quiet"` (default) — automatic on battery is Leise;
`"balanced"` — for owners who prefer speed, automatic on battery is Ausgewogen(-battery) and drops to
Leise only at ≤ 20 % (the original behaviour). With the quiet base the low-battery rule changes no
mode (it is Leise already) and only shows in `reason`; `power.lowBatteryQuiet` matters for the
balanced base. Changing the setting applies at once.

Never on battery automatically: Leistung. An app that is merely open (Blender modelling, Steam in
the background, a video) does not boost. Samples are taken only while a heavy app runs on mains
in automatic mode.

**Manual choice:** any profile change the daemon did not make (shell, assistant, hotkey, another
PPD client) is the owner's choice. tuned-ppd itself cancels all holds when a profile is set, so the
choice takes effect at once. From then on automatic holds stop, and the choice is kept across
plugging and unplugging, with one exception: **a Leistung chosen on mains pauses while on battery**
(the machine runs Ausgewogen-on-battery — not the quiet battery base, because the owner asked for
speed; Leise only at ≤ 20 %) and resumes when power returns; a Leistung chosen on battery stays. A manual choice ends when the owner chooses "Automatisch" (`kristall-power mode auto`
or `org.kristall.Power1.ResumeAutomatic`), when `power.automatic` is switched off and on, or at the
next login (each session starts automatic). Low-battery Leise is never forced over a manual choice.

**`power.automatic = false`:** the daemon never sets profiles or holds; the mode is whatever the
owner last chose (tuned-ppd remembers it across reboots). The mains/battery variants, refresh rate,
glass hint and dimming still follow §4/§6 because they are part of what a mode means.

Attribution rule: profile changes within 3 s after one of the daemon's own calls are not judged at
once; 3.5 s later the daemon compares tuned-ppd's active profile with what it wants and treats an
unexplained difference as the owner's choice. Holds held by other applications are respected and
never counted as a manual choice.

Sequences (all tested, `power/tests/test_auto.py`, `test_session_dbus.py`): unplug → Leise hold at
once (default base), replug → Ausgewogen; unplug during a game → Leistung released, Leise-on-battery,
display changes wait for the game to end; `batteryBase` switched live in both directions; replug with the game
still running → Leistung again; manual Leise during a game → stays Leise through unplug/replug;
manual Leistung on mains → paused on battery, resumes on replug; suspend → resume re-reads power
source and battery and re-decides; tuned-ppd restart → holds re-placed.

## 4. What each mode means

Package power limits are programmed by the profile hook through powercap RAPL, on **both** the MSR
(`intel-rapl:N`) and the MMIO (`intel-rapl-mmio:N`) interfaces where present (the CPU enforces the
lower of the two). Target per constraint = `min(firmware value, absolute cap, fraction × firmware
value)`, never below the floor (PL1 12 W, PL2 20 W) unless the firmware value itself is lower (then
untouched), never above the firmware value or the zone's `constraint_N_max_power_uw`. "Firmware
value" is what the firmware/EC last programmed (§5.1). PL4/peak power and the time windows are never
written (no reported valid range).

| | Leise mains | Leise battery | Ausgewogen mains | Ausgewogen battery | Leistung (both) |
|---|---|---|---|---|---|
| PL1 sustained | min(20 W, 0.45×fw) | min(15 W, 0.35×fw) | min(45 W, fw) | min(28 W, 0.65×fw) | firmware |
| PL2 burst | min(45 W, 0.5×fw) | min(35 W, 0.4×fw) | min(90 W, fw) | min(55 W, 0.6×fw) | firmware |
| EPP (HWP) | balance_power | balance_power | balance_performance | balance_power | performance |
| EPB | balance-power | balance-power | normal | balance-power | performance |
| platform_profile (first available) | quiet → low-power → balanced | same | balanced | balanced | performance → balanced-performance → balanced |
| Turbo | on | on | on | on | on |
| Refresh (`batteryRefreshRate: auto`) | max | 60 Hz | max | 60 Hz | max |
| Glass hint | efficient | efficient | high | efficient | high mains / efficient battery |
| Dirty writeback | 5 s | 15 s | 5 s | 15 s | 5 s / 15 s |

Common to all: governor `schedutil|powersave` (never `performance`, which on HWP pins the minimum
frequency to the maximum; never `min_perf_pct`), audio codec power-save after 10 s, NMI watchdog off.

Why these numbers (i9-13900H: Processor Base Power 45 W, Maximum Turbo Power 115 W, Minimum
Assured Power 35 W; Intel ARK). Confidence in brackets.
* **Leise 20/45 W mains, 15/35 W battery.** A thin 14–16" chassis dissipates roughly 15–20 W with
  fans off or at their lowest step, 35–45 W only with clearly audible fans. Browsing, coding, video
  and calls mostly draw 3–15 W of package power, so they are unaffected; PL2 45 W still lets a
  single P-core reach full turbo for the length of the PL1 time window (OEM default ~28 s), so
  clicks and short compiles feel instant; a render is held to 20 W (≈ 55–65 % of its 45 W speed on
  Raptor Lake's perf/W curve). [medium: chassis unknown]
* **Ausgewogen mains 45/90 W.** 45 W is the sustained power the chip is specified for; the last
  25 W of burst (90 → 115 W) buys ~5 % multi-thread burst speed but is what makes the fans jump on
  short spikes. On mains the vendor's balanced fan curve decides the noise. [medium]
* **Ausgewogen battery 28/55 W.** Typical OEM battery-balanced range; long sustained loads stay
  below the point where the fans become loud and the battery's discharge limit is reached. [medium]
* **Leistung = firmware.** "Everything the firmware and cooling allow"; the vendor performance
  profile usually raises the limits and the fan curve. [high that this is the right policy]
* **EPP.** balance_power makes HWP choose lower clocks for light, bursty work (the largest saving in
  light use) while still ramping on sustained demand; balance_performance is the kernel default;
  performance (0) for Leistung only. [high]
* **Relative caps.** Fractions keep the modes ordered on a machine whose firmware is far more
  conservative than Intel's spec (e.g. 35 W firmware PL1 → Leise 15.75 W, Ausgewogen 35 W). [high]

## 5. Mechanisms

### 5.1 Firmware interplay (RAPL)
Baseline tracking (`/run/kristall-power/rapl.json`): the first value seen in a boot is the firmware
value; whenever a limit is not what we last wrote (± 0.25 W rounding), firmware/EC changed it (resume,
plug, platform-profile change): that value becomes the new firmware value, the event is logged as
`drift`, and the mode's target is recomputed from it. A limit locked by firmware (`EACCES`) is
reported `locked` and skipped; a write the hardware rounds is accepted as ours. Re-apply points: tuned
profile start (mode or power-source change; runs after every other tuned unit, i.e. after the
platform profile), 2 s and 8 s later, after every resume, after every mains/USB-PD supply change.
`kristall-power revert` / stopping `kristall-power.service` / tuned's profile `stop` restore the
firmware values. While `kristall-power.service` is stopped (marker `/run/kristall-power/stopped`)
neither the profile hook nor re-apply touches a limit; starting it again resumes management.

### 5.2 Long tail (static, all modes)
| Lever | Mechanism | Choice |
|---|---|---|
| PCI runtime PM | udev on driver bind | `auto` for Intel platform devices; not Ethernet (0x0200), mei_me, xhci_hcd, e1000e, audio, GPU drivers (they manage it or have known trouble) |
| USB autosuspend | udev + `/usr/libexec/kristall/power/usb-autosuspend` | only devices with `removable=fixed` (camera, Bluetooth, fingerprint), never HID or hubs; external mice/keyboards untouched |
| PCIe ASPM | — | left to firmware (`policy=default`); doctor lists devices without L1.2 |
| NVMe | — | kernel APST default kept; doctor reports it |
| Wi-Fi | NetworkManager `wifi.powersave = 3` | power save on |
| Bluetooth, audio | kernel defaults (btusb autosuspend), tuned `[audio] timeout=10` | — |
| Memory | zram as large as RAM; `vm.swappiness=180`, `vm.page-cluster=0`, `vm.watermark_boost_factor=0` | room for Blender scenes before anything is killed |
| Background work | `kristall-background.slice` on E-cores | automatic updates and app provisioning never wake P-cores at turbo |
| Games | GameMode (`/etc/gamemode.ini`): governor writes neutralised (same `powersave` policy, which leaves EPP untouched), iGPU sampling off, no core pinning, split-lock mitigation off while a game runs, reaper every 30 s | the session daemon turns a registered game into a Leistung hold |
| tuned | `sleep_interval = 10` (was 1; dynamic tuning is off, the loop only waits) | fewer idle wake-ups |

### 5.3 Rejected (and why)
* **Kernel arguments**: none shipped. `nosmt` would enable energy-aware scheduling on this hybrid
  CPU (intel_pstate enables EAS only without SMT) at the cost of 6 threads — revisit with doctor data;
  `pcie_aspm=force`/`powersupersave`, forced `i915.enable_psr`/`enable_fbc`/`enable_dc`, `mem_sleep_default=deep`
  can break or black-screen unknown hardware; `rcutree.enable_rcu_lazy` needs `CONFIG_RCU_LAZY`
  (not set in Fedora's kernel).
* **sched_ext (scx_lavd, scx_bpfland)**: the kernel supports it (`CONFIG_SCHED_CLASS_EXT=y`) but no
  scheduler package exists in Fedora 45; building a Rust BPF scheduler in the image for an unmeasured
  gain on Raptor Lake (ITMT + HFI already place work) adds a moving part that the watchdog can eject
  under load. E-core confinement of background slices gets the main battery benefit safely.
* **thermald**: not in the base; on this generation its value is applying the OEM's DPTF tables, which
  is exactly where it fights our RAPL caps and the platform profile. Not installed; doctor reports it
  if present. **intel-lpmd**: polls utilisation and moves all work to E-cores; designed for Meteor
  Lake's LP E-cores, unproven on Raptor Lake, conflicts with "instant". **Turbo off** (stock tuned
  `powersave`): kills instant response. **Stock `throughput-performance`**: `min_perf_pct=100` +
  performance governor pin clocks at maximum (hot at idle). **Undervolting / fan control / thermal
  trip changes**: never.
* **VRR forced to "always"**: varying refresh makes many OLED panels flicker visibly in dark
  scenes; Plasma's default (automatic = full-screen apps only) is kept.

## 6. Display and glass

* **Refresh rate** (session daemon, through `kscreen-doctor`, internal panel only): target "max"
  on mains and in Leistung, "low" on battery otherwise (`power.batteryRefreshRate: "auto"`); `"max"`
  never lowers it. "low" = the lowest mode ≥ 59 Hz *at the current resolution*; nothing happens on a
  panel with a single rate. Evaluated 3 s after the power source/mode settles, never while a game is
  registered (deferred until it ends), and not again in that session after the owner picked a rate
  that is neither ours nor the maximum (`refresh_owner` in `~/.local/state/kristall/power/session.json`).
  Whether the panel switches without a blink depends on the driver doing a seamless refresh change
  (eDP DRRS/fastset); not knowable before the first boot (doctor reports i915 DRRS status).
* **Panel self refresh, FBC, DC states**: driver defaults (VBT), never forced.
* **Dim on battery** (`power.dimOnBattery`, default on): on unplug the internal display goes to 85 %
  of its brightness (not below 25 % of max; not if already ≤ 25 %), without OSD, through PowerDevil's
  `org.kde.ScreenBrightness`; on replug it is restored only if the owner did not change it meanwhile.
  PowerDevil's own low-battery dimming (30 %) stays.
* **Glass quality** (`appearance.glassQuality: "auto"`): the daemon keeps a `glass.sock` connection
  and sends `{"op":"config","qualityHint": "efficient"}` on battery or in Leise, `"high"` otherwise
  (glass contract §4). It connects when the socket appears (inotify), not by polling.

## 7. Interfaces

### 7.1 CLI
`kristall-power <command>`; JSON output is one line, UTF-8.

| Command | Who | Effect / output | Exit |
|---|---|---|---|
| `status [--json] [--measure]` | anyone | §7.2; `--measure` adds RAPL power (root, 0.5 s) | 0 |
| `doctor [--json] [--out DIR] [--idle-seconds N]` | owner | starts `kristall-power-doctor.service` (polkit: no password), adds the session view, writes `DIR/doctor.{json,txt}` (default `~/.local/state/kristall/power/`, mode 0600), prints the bilingual summary | 0 |
| `doctor --local` | root or owner | collect the system part in-process instead | 0 |
| `mode auto\|quiet\|balanced\|performance` | owner | `auto` → `org.kristall.Power1.ResumeAutomatic`; others set the PPD profile (a manual choice) | 0 / 1 unreachable |
| `charge-limit` | anyone | `{"supported","methods","stored"}` | 0 |
| `charge-limit N [--json]` | root (`kristall-power-charge@N.service`) | apply 50..100 (100 = off) | 0 ok / 1 failed / 2 rejected |
| `revert [--charge]` | root | firmware power limits back (and the original charge thresholds with `--charge`) | 0 |
| `tuned-hook`, `reapply [--settle]`, `boot`, `session` | tuned / systemd | internal | — |

### 7.2 `status --json` (schema 1)
```json
{"schema":1,"time":"2026-11-15T10:00:00Z","mode":"balanced","mode_name":{"de":"Ausgewogen","en":"Balanced"},
 "tuned_profile":"kristall-balanced-battery","ppd_base_profile":"balanced",
 "automatic":{"enabled":true,"manual":null,"reason":"auto","hold":null,"game":false,"heavy_app":null},
 "power_source":"battery",
 "battery":{"name":"BAT0","percent":64,"status":"Discharging","health_percent":92.1,"cycle_count":41,
            "energy_wh":58.9,"energy_full_wh":92.0,"energy_full_design_wh":99.9,"power_w":7.4,
            "time_to_empty_s":28654,"time_to_full_s":null,"technology":"Li-poly","manufacturer":"…","model":"…",
            "charge_control_end_threshold":80,"charge_control_start_threshold":75,"charge_types":null},
 "charge_limit":{"supported":true,"methods":[{"battery":"BAT0","method":"threshold","start_threshold":true,
                 "charge_types":null,"charge_type":null}],"value":80},
 "draw":{"watts":7.4,"source":"battery"},
 "temperatures":{"cpu_package":52.0,"cpu_core_max":49.0,"nvme":38.9},
 "fans":{"thinkpad/fan1":0},
 "display":{"refresh_hz":60.0,"available_hz":[60.0,120.0],"managed":true,"target":"low","vrr_policy":"automatic"},
 "glass_quality_hint":"efficient","platform_profile":"balanced",
 "limits":[{"lever":"rapl:intel-rapl:0:pl1","status":"applied","target_uw":28000000,"baseline_uw":45000000}]}
```
`mode` is the *effective* mode (holds included). `power_source`: `battery` | `ac` | `none` (no battery).
`draw` is `null` on mains for unprivileged callers (RAPL energy is root-only); fans/temperatures are
`{}` where not readable; `automatic.manual` = `{"mode","on_battery","since"}`; `automatic.reason`:
`auto`, `auto-battery` *(addition: Leise because on battery with the quiet battery base)*,
`auto-game`, `auto-heavy-app`, `auto-low-battery`, `manual`,
`manual-performance-paused-on-battery`, `automatic-off`, or `session daemon not running`. Unknown
fields must be ignored; new fields may appear without a schema bump.

### 7.3 Session daemon
* D-Bus (session bus) `org.kristall.Power1` at `/org/kristall/Power1`, interface `org.kristall.Power1`:
  `ResumeAutomatic()`, `GetState() → s` (JSON, below), signal `StateChanged(s)`.
* `$XDG_RUNTIME_DIR/kristall/power.json` (0600, atomic rename on change; watch with inotify):
  `{"schema":1,"automatic":bool,"manual":{…}|null,"reason":…,"hold":"performance"|"power-saver"|null,
  "mode":…,"on_battery":bool,"percent":int|null,"low_battery":bool,"game":bool,"heavy_app":str|null,
  "glass_hint":…,"glass_connected":bool,"refresh":{"managed":bool,"target":"max"|"low","panel":{…},"reason"?},
  "dimmed":bool,"game_clients":int,"heavy_apps_running":[…],"sampling":bool}`.
* For the shell: show the PPD mode as today; show "Automatisch" when `automatic && !manual`; offer
  "Automatisch" as a fourth choice that runs `kristall-power mode auto`.

### 7.4 Root-written files (world-readable)
`/run/kristall-power/applied.json` (last applied mode, per-limit results, platform profile expected
vs current, drift), `/run/kristall-power/rapl.json`, `/run/kristall-power/charge.json`,
`/var/lib/kristall/power/charge-limit` (persisted limit), `charge-original.json`,
`events.jsonl` (§9), `doctor-system.{json,txt}`.

## 8. Settings (`power`, defaults in `settings.d/50-power.json`)

| Key | Type | Default | Meaning |
|---|---|---|---|
| `power.automatic` | bool | `true` | §3 |
| `power.batteryBase` | `"quiet"` \| `"balanced"` | `"quiet"` | what automatic means on battery: Leise from the start (default), or Ausgewogen until the battery is low (§3) |
| `power.batteryRefreshRate` | `"auto"` \| `"max"` | `"auto"` | lower the internal panel to ~60 Hz on battery (not in Leistung) |
| `power.dimOnBattery` | bool | `true` | §6 |
| `power.chargeLimit` | int 50..100 | `100` | stop charging at N % (100 = off). Applied through `kristall-power-charge@N`; persisted by root and re-applied at every boot. Supported if `status.charge_limit.supported`; with method `long-life` the firmware decides the level (any N < 100 = on) |
| `power.lowBatteryQuiet` | bool | `true` | automatic Leise at ≤ 20 % on battery (matters with `batteryBase: "balanced"`; with the quiet base the mode is Leise anyway) |
| `power.heavyApps` | array of app ids | Blender, Vinegar/Sober (Roblox), Steam, Heroic, Lutris, Prism | apps whose busy scopes earn an automatic Leistung on mains |

Invalid values are ignored with a journal message (an invalid `chargeLimit` keeps the current limit).

## 9. Logs (owner never sees them; attached to doctor reports)
JSON lines `{"t":"<UTC>","ev":"<event>",…}`, each file ≤ 256 KiB plus one rotated copy.
* `~/.local/state/kristall/power/log.jsonl` (session): `start`, `source`, `battery` (every % change
  on battery, with draw and temperatures), `profile`, `set`, `hold`, `release`, `manual`,
  `manual-end`, `game`, `heavy-app-start/stop`, `workload`, `refresh`, `refresh-owner`, `dim`,
  `undim`, `glass`, `lock`, `suspend`, `resume`, `charge-limit-request`, `automatic`, and `sample`
  (once a minute while the screen is unlocked **and** CPU ≥ 25 % busy, package ≥ 80 °C, a game or a
  boosted app: CPU busy, temperatures, fans, mode, draw). Journal: `journalctl --user -t kristall-power`.
* `/var/lib/kristall/power/events.jsonl` (root): `boot`, `apply`, `drift`, `revert`, `charge-limit`.

## 10. Doctor report
`kind: "kristall-power-doctor"`, `schema: 1`. `levers`: list of `{"lever","status","detail"?,
"expected"?,"actual"?,…}` with status `applied` | `unsupported` | `locked` | `failed` |
`not-applicable` | `skipped` | `warning` | `unknown`. Levers: `epp`, `epb`, `intel-pstate-active`, `turbo`,
`platform-profile`, `rapl:<zone>:pl1|pl2`, `charge-limit`, `pci-runtime-pm`, `pcie-aspm`,
`usb-autosuspend`, `nvme-apst`, `audio-power-save`, `wifi-power-save`, `bluetooth-autosuspend`,
`nmi-watchdog-off`, `panel-self-refresh`, `zram`, `swappiness`, `tuned`, `ppd-mapping`,
`no-conflicting-daemons`, `gamemode`, `background-on-e-cores`, `deep-idle`, `automatic-mode`,
`refresh-rate`, `glass-quality`. Sections: `system` (kernel, cmdline, DMI vendor/model/BIOS — never
serials/UUIDs, CPU, hybrid layout), `cpu` (intel_pstate, per-policy EPP/governor/frequencies, ITMT,
EAS, sched_ext, SMT), `platform_profile` (+ class handlers), `rapl` (zones, limits, maxima, time
windows, lock probe as root, baselines, drift), `battery`, `devices` (PCI with runtime PM and ASPM
link states, USB, NVMe, Wi-Fi), `graphics` (driver, RC6, GT frequencies, i915/xe parameters, PSR and
DRRS status from debugfs as root, panel EDID), `memory` (zram, sysctls, THP, MGLRU), `services`
(tuned, tuned-ppd, conflicting daemons, thermald, lpmd, oomd), `temperatures`, `thermal_zones`,
`hwmon`, `power_w` (root), `idle` (per-state core residency over N s, package C-state residency from
`pmc_core` as root, top processes by context switches/s, top interrupts/s, S0ix residency counters,
`mem_sleep`, suspend statistics), `events`, `session`, `session_log`.

## 11. Safety rules (enforced in code and tests)
Every lever is feature-detected and skipped cleanly; values are never written above what the
firmware set or the hardware reports as maximum; no undervolting, fan or thermal-trip writes; display
features are never forced; charge thresholds only within 50..100 and written in an order that keeps
start < end; every write's errno is reported, none is fatal; all root actions are logged.

## 12. What the owner can expect (estimates for an unknown chassis, ~70–99 Wh battery)
* Light work on battery (browser, Claude Code, editor, calls; automatic = Leise, 60 Hz, OLED with
  dark-ish content): about **6–9 h**, toward the upper end because automatic now runs Leise on
  battery; video playback (hardware decode) **7–10 h**; Blender rendering or games on battery
  **1–2 h** on paper, but in automatic Leise a render runs at roughly half speed (15 W sustained) —
  slower, cooler and quieter, which is the owner's stated priority; choose Leistung (or
  `batteryBase: "balanced"`) to trade that back. A 45 W-class i9 idles and works lightly at several times the power of
  an Apple-silicon Mac; no software closes that gap (an M-series MacBook gets roughly twice this).
* Noise: Leise (automatic on battery) — fans off or at their lowest step for everything but sustained
  heavy work, which is slowed instead; typing, scrolling, app starts and short builds still get full
  turbo bursts. Ausgewogen — quiet in light use; real work (compiles, exports) ramps the fans per the
  vendor's balanced curve. Leistung, and every Blender render or demanding game on mains — **loud**:
  45–80 W through a thin chassis needs the fans at full speed.
* No software can change: fan curves on laptops without a `platform_profile` driver (the EC owns
  them), limits the BIOS locked, the cooling system's capacity, the power an OLED needs for bright
  white content.

## 13. Unverified (no laptop here)
Everything that depends on the real machine: which interfaces exist, whether RAPL is locked or reset
on resume/plug, what the vendor's platform profiles do to limits and fans, whether 60↔120 Hz switches
without a blink, the energy numbers above, whether deep package C-states are reached. The doctor
report after the first install is the measurement; tune `policy.py` from it.
