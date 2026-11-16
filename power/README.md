# power — performance, battery, heat, noise

Makes the laptop quiet and cool in light work, long-lived on battery, instantly responsive, and at
full strength when real work asks for it, without the owner having to think about it. Automatic
mode (the default) runs **Leise on battery from the start** (turbo bursts stay), Ausgewogen on mains,
and Leistung on mains for games and busy heavy apps; `power.batteryBase: "balanced"` makes battery
use Ausgewogen until 20 % for owners who prefer speed.
Interface for everyone else: [`docs/contracts/power.md`](../docs/contracts/power.md).

## What is where

| Path | What |
|---|---|
| `lib/kristall_power/policy.py` | **The policy table**: per mode and power source — power limits, EPP/EPB, platform profile, refresh, glass, automatic-mode thresholds |
| `lib/kristall_power/{rapl,charge,system}.py` | Root side: firmware-relative power limits, charge limit, tuned hook / re-apply / boot / revert |
| `lib/kristall_power/{auto,session,workload,display}.py` | Session daemon: automatic mode (PPD holds), heavy-app sampling, refresh rate, dimming, glass hint, log |
| `lib/kristall_power/{status,doctor,hw,logbook,cli}.py` | `status --json`, `doctor`, hardware detection, bounded logs, CLI |
| `tuned/` | Six tuned profiles (+ `kristall-common`) and the `[script]` hook copied into each |
| `config/` | `ppd.conf`, `gamemode.ini`, sysctl, zram drop-in, NetworkManager Wi-Fi power save, settings defaults `50-power.json` |
| `systemd/`, `udev/`, `polkit/`, `libexec/` | Units, presets, generator, sleep hook, udev rules, USB helper, polkit rule |
| `image/install.sh` | Image-build installer (component contract) |
| `tests/` | `run.sh`, fake-hardware fixtures, unit/integration tests, fake D-Bus services |

## Build and test

Nothing is compiled. In the dev container (everything, including tuned's own parser, private D-Bus
buses and the polkit rule):

```sh
docker run --rm --name kristall-power-tests -v /home/user/kristall:/work:ro kristall-devenv:latest bash /work/power/tests/run.sh
# plus the real tuned 2.28 + tuned-ppd daemons driving our hook (installs into the throwaway container):
docker run --rm --name kristall-power-tests -e KRISTALL_POWER_REAL_TUNED=1 -v /home/user/kristall:/work:ro kristall-devenv:latest bash /work/power/tests/run.sh
```

On a plain host with Python 3 the same script runs everything that does not need tuned or D-Bus.

What the tests cover:
* `test_levers.py` — six fake laptops (`tests/fixtures.py`: thin OLED with platform profile and both
  RAPL interfaces; locked MSR limits; firmware that resets limits on resume/plug; 60 Hz LCD without
  platform profile or charge limit; Lenovo-style Long_Life; desktop without battery): every mode,
  relative caps and floors, reported maxima, locked/failed writes, firmware drift and re-apply,
  hardware rounding, live session, revert; charge limits (orders, invalid values, unsupported,
  boot re-apply, revert); `status` and `doctor` on every personality; generator and USB helper.
* `test_auto.py` — automatic mode against a fake tuned-ppd with tuned 2.28's hold semantics,
  including Leise from the start on battery (`power.batteryBase`, both values, switched live),
  unplug during a game, manual choice then replug, paused Leistung, battery thresholds,
  suspend/resume, tuned-ppd restart, external holds, transient attribution.
* `test_display.py` — refresh-rate choice on KScreen output descriptions, EDID parsing, RAPL targets
  never above firmware for any firmware value.
* `validate_tuned.py` — loads the profiles with tuned's own Loader, checks every option against the
  plugin's declared options and against `policy.py`, parses `ppd.conf` with tuned-ppd's own parser
  (plus a negative control). Also run by `install.sh` at image build.
* `test_session_dbus.py` — the real session daemon on two private buses with fake UPower, tuned-ppd,
  logind, GameMode, systemd and PowerDevil brightness, fake `kscreen-doctor`, a fake glass socket
  and the real `kristall-settings`: a whole day of events, and a check that it does not wake up
  when idle.
* `test_real_tuned.py` — real `tuned` + `tuned-ppd` with our profiles: PPD mode and battery changes
  reach the right tuned profile and our hook programs the (fake) limits; stopping tuned restores them.

## On the real machine

`kristall-power status`, `kristall-power doctor` (report in `~/.local/state/kristall/power/doctor.{json,txt}`;
the root part is also written 15 min after every boot to `/var/lib/kristall/power/doctor-system.json`),
`journalctl -t kristall-power`, `journalctl --user -t kristall-power`.

## Known limits

* Nothing here has run on the laptop: interfaces present, firmware behaviour (locks, resets on resume
  or plug), what the vendor's platform profiles do, refresh switching without a blink, and every
  energy figure in the contract are unverified until the first doctor report.
* Detecting "busy" heavy apps relies on the XDG systemd scope naming that Flatpak and Plasma use;
  apps started some other way are invisible to the automatic boost (GameMode still works).
* Steam games ask for GameMode only with `gamemoderun %command%` (or a game that links it); without
  that, a Steam game on mains is boosted only when Steam's scope is busy enough (§3 of the contract).
* GameMode 1.8 writes the CPU governor at game start/end; it writes `powersave`, the policy tuned
  already uses on intel_pstate, which the kernel treats as no change. If intel_pstate ran in passive
  mode that would instead mean minimum clock: doctor flags `intel_pstate.status != active`.
* `status --json` reports power draw on mains only for root (RAPL energy counters are root-only).
