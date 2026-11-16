# SPDX-License-Identifier: GPL-3.0-or-later
"""Internal panel refresh rate via KScreen (`kscreen-doctor`, part of libkscreen in the base).

Rules (contract §6): only the internal panel; only switch between modes of the *current*
resolution; 'low' = the lowest mode >= 59 Hz (never below 59: some panels flicker or misbehave
at 48/50 Hz and the shell's animation timing assumes >= 60); never force VRR; never act when the
panel offers only one rate; if the owner picked a rate that is neither ours nor the maximum,
leave the panel alone for the rest of the session."""
import json
import re
import subprocess

PANEL_TYPE = 7  # KScreen::Output::Type::Panel
VRR = {0: "never", 1: "always", 2: "automatic"}


def kscreen_json(timeout=10):
    try:
        p = subprocess.run(["kscreen-doctor", "-j"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError):
        return None
    if p.returncode != 0:
        return None
    txt = p.stdout
    i = txt.find("{")
    try:
        return json.loads(txt[i:]) if i >= 0 else None
    except ValueError:
        return None


def internal_outputs(cfg):
    outs = []
    for o in (cfg or {}).get("outputs", []):
        name = o.get("name") or ""
        if not o.get("connected") or not o.get("enabled", True):
            continue
        if o.get("type") == PANEL_TYPE or re.match(r"(eDP|LVDS|DSI)", name):
            outs.append(o)
    return outs


def _modes(o):
    return {str(m.get("id")): m for m in o.get("modes", [])}


def describe(o):
    modes = _modes(o)
    cur = modes.get(str(o.get("currentModeId")))
    if not cur:
        return None
    size = cur.get("size") or {}
    same = sorted({round(m.get("refreshRate", 0), 2) for m in modes.values() if m.get("size") == size})
    return {"name": o.get("name"), "width": size.get("width"), "height": size.get("height"),
            "refresh_hz": round(cur.get("refreshRate", 0), 2), "available_hz": same,
            "vrr_policy": VRR.get(o.get("vrrPolicy")), "mode_id": str(o.get("currentModeId"))}


def choose(o, target: str):
    """Return (mode_id, refresh) the panel should use for target 'max' or 'low', or None if no
    change is possible/needed."""
    modes = _modes(o)
    cur = modes.get(str(o.get("currentModeId")))
    if not cur:
        return None
    size = cur.get("size")
    cands = [m for m in modes.values() if m.get("size") == size and m.get("refreshRate")]
    rates = {round(m["refreshRate"]) for m in cands}
    if len(rates) < 2:
        return None
    if target == "max":
        pick = max(cands, key=lambda m: m["refreshRate"])
    else:
        low = [m for m in cands if m["refreshRate"] >= 59.0]
        if not low:
            return None
        pick = min(low, key=lambda m: m["refreshRate"])
    if str(pick.get("id")) == str(o.get("currentModeId")):
        return None
    if abs(pick["refreshRate"] - cur["refreshRate"]) < 1.0:
        return None
    return str(pick["id"]), round(pick["refreshRate"], 2)


def owner_managed(o, last_set_mode_id):
    """True when the panel runs a rate we did not choose and that is not its maximum: the owner
    (or System Settings) picked it, so we do not touch it again this session."""
    modes = _modes(o)
    cur = modes.get(str(o.get("currentModeId")))
    if not cur:
        return False
    size = cur.get("size")
    rates = [m["refreshRate"] for m in modes.values() if m.get("size") == size and m.get("refreshRate")]
    if not rates or abs(cur["refreshRate"] - max(rates)) < 1.0:
        return False
    return last_set_mode_id is None or str(o.get("currentModeId")) != str(last_set_mode_id)


def set_mode(output_name, mode_id, timeout=15):
    try:
        p = subprocess.run(["kscreen-doctor", f"output.{output_name}.mode.{mode_id}"],
                           capture_output=True, text=True, timeout=timeout)
        return p.returncode == 0, (p.stderr or p.stdout)[-500:]
    except (OSError, subprocess.SubprocessError) as e:
        return False, str(e)
