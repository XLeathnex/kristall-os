// SPDX-License-Identifier: GPL-3.0-or-later
// The crystal light around the edge of one output while the assistant is active: a bright rim
// that hugs the display's rounded corners and a wide soft glow (≈ 5 % of the short side) in our
// crystal palette — icy cyan → violet → magenta with travelling amber accents — flowing around
// the edge (one hue cycle in ~8 s).
//   listening — the full light; thickness and brightness follow the microphone level
//   thinking  — calmer and thinner, the hues run faster and glints shimmer around the edge
//   acting    — lower intensity, a slow steady flow (the agent cursor is the focus)
//   speaking  — like listening, following the voice, warmer accents
//   error     — a short warm flash, then it fades
// Entry: it blooms in within 450 ms — the light starts at both bottom corners, runs up the sides
// and meets at the top, with a slight brightness overshoot. Exit: fades out in 300 ms. When fully
// faded the four strips are unmapped and the frame clock stops, so an inactive assistant costs
// nothing. Reduce Motion: no flow, no sweep, no level; it simply fades in and out.
// Uniform updates are capped at `assistant.ui.light.maxFps` (default 60, halved on battery).
import QtQuick
import Quickshell
import qs.core
import qs.services

Scope {
    id: light
    required property var screen
    property bool shown: false             // the assistant wants the light here
    property string mode: "listening"
    property real levelTarget: 0           // raw level from the daemon (mic or speech)
    property rect hole: Qt.rect(0, 0, 0, 0) // the panel's glass, in output coordinates (the light goes under it)
    property real holeRadius: 26

    readonly property real screenW: screen ? screen.width : 0
    readonly property real screenH: screen ? screen.height : 0
    readonly property bool enabled: Settings.get("assistant.ui.light.enabled", true) !== false
    readonly property real strength: Math.max(0, Math.min(1, Number(Settings.get("assistant.ui.light.intensity", 1.0))))
    // on battery the light moves at half the rate (it still reads as fluid; it costs half)
    readonly property int maxFps: Math.max(15, (Number(Settings.get("assistant.ui.light.maxFps", 60)) || 60) / (Power.onBattery ? 2 : 1))
    readonly property real cornerRadius: Number(Settings.get("assistant.ui.light.cornerRadius", 14))
    readonly property bool still: Theme.reduceMotion
    // Light or dark variant: what is actually behind the edge counts, not only the theme. The glass
    // effect's legibility signal of the menu bar (the whole top edge) and of the assistant's own
    // panel says whether the content there is bright (a white page in dark mode gets the deep,
    // saturated variant too); without glass, the theme decides.
    readonly property string screenName: screen ? screen.name : ""
    readonly property string sampled: {
        const s = GlassClient.schemes;
        return s["bar-" + screenName + "/strip"] || s["assistant-panel-" + screenName + "/panel"] || "";
    }
    readonly property bool lightBehind: GlassClient.active && sampled !== "" ? sampled === "light" : !Theme.dark
    property real onLight: lightBehind ? 1 : 0
    Behavior on onLight { NumberAnimation { duration: 400 } }
    property bool forceFallback: Quickshell.env("KRISTALL_ASSISTANT_LIGHT_FALLBACK") === "1"

    // ---- geometry ---------------------------------------------------------------------------------
    readonly property real shortSide: Math.max(1, Math.min(screenW, screenH))
    readonly property real reach: Math.round(shortSide * 0.065)       // where the glow's tail ends (visible ≈ 5 %)
    readonly property real rimWidth: 3.5
    // depth of the strips: room for the widest glow (full level + bloom)
    readonly property real depth: Math.ceil(reach * 1.2) + 2

    // ---- visibility: entry bloom, exit fade ------------------------------------------------------
    property real fade: 0
    property real sweep: 1.2               // entry front (0 → 1.2); 1.2 = fully in
    property real bloom: 0                 // brightness overshoot during the entry
    property real entryOverride: -1        // tests: freeze the entry at this progress (0..1)
    readonly property bool want: shown && enabled && strength > 0
    readonly property bool mapped: want || fade > 0.002
    onWantChanged: {
        entry.stop();
        exit.stop();
        if (want) {
            if (still || fade > 0.5) {         // Reduce Motion, or back while still fading out: no sweep
                sweep = 1.2;
                bloom = 0;
                fadeIn.duration = still ? 300 : 150;
                fadeIn.start();
            } else {
                entry.start();
            }
        } else {
            exit.start();
        }
    }
    NumberAnimation { id: fadeIn; target: light; property: "fade"; to: 1; easing.type: Easing.OutQuad }
    property real lastEntryMs: 0           // diagnostics: how long the last entry / exit took
    property real lastExitMs: 0
    property real _t0: 0
    ParallelAnimation {
        id: entry
        onStarted: light._t0 = Date.now()
        onFinished: light.lastEntryMs = Date.now() - light._t0
        PropertyAction { target: light; property: "sweep"; value: 0 }
        NumberAnimation { target: light; property: "fade"; to: 1; duration: 120; easing.type: Easing.OutQuad }
        NumberAnimation { target: light; property: "sweep"; from: 0; to: 1.2; duration: 450; easing.type: Easing.BezierSpline; easing.bezierCurve: [0.25, 0.6, 0.3, 1.0, 1, 1] }
        SequentialAnimation {
            NumberAnimation { target: light; property: "bloom"; from: 0; to: 0.45; duration: 250; easing.type: Easing.InQuad }
            NumberAnimation { target: light; property: "bloom"; to: 0; duration: 200; easing.type: Easing.OutQuad }
        }
    }
    SequentialAnimation {
        id: exit
        onStarted: light._t0 = Date.now()
        onFinished: light.lastExitMs = Date.now() - light._t0
        NumberAnimation { target: light; property: "fade"; to: 0; duration: 300; easing.type: Easing.InOutQuad }
        PropertyAction { target: light; property: "bloom"; value: 0 }
    }
    onEntryOverrideChanged: {
        if (entryOverride < 0)
            return;
        entry.stop();
        fade = Math.min(1, entryOverride * 4);
        sweep = 1.2 * entryOverride;
        bloom = 0.45 * Math.sin(Math.PI * Math.min(1, entryOverride));
    }

    // ---- per-state look -------------------------------------------------------------------------
    // [cyan, violet, magenta, amber]; light appearance: deeper, more saturated variants
    readonly property var palettes: ({
        dark: {
            crystal: ["#3FD8FF", "#7B4DFF", "#FF3FCB", "#FFAA33"],
            error:   ["#FFC14A", "#FF7A3D", "#FF4F6A", "#FFD25E"]
        },
        light: {
            crystal: ["#0096E0", "#5E22F2", "#D80FA0", "#FF9000"],
            error:   ["#F09A00", "#EC5A12", "#DD2A4A", "#F5B000"]
        }
    })
    readonly property var params: ({
        //           reach  flow (cycles/s)  shimmer  accent  power
        listening: { reach: 1.0,  flow: 0.125, shimmer: 0.0,  accent: 0.8, power: 1.0 },
        thinking:  { reach: 0.8,  flow: 0.33,  shimmer: 0.75, accent: 0.6, power: 0.82 },
        acting:    { reach: 0.72, flow: 0.08,  shimmer: 0.0,  accent: 0.5, power: 0.6 },
        speaking:  { reach: 1.0,  flow: 0.125, shimmer: 0.0,  accent: 1.0, power: 1.0 },
        error:     { reach: 0.9,  flow: 0.1,   shimmer: 0.0,  accent: 0.6, power: 1.0 }
    })
    readonly property var pal: (palettes[onLight > 0.5 ? "light" : "dark"])[mode === "error" ? "error" : "crystal"]
    readonly property var par: params[mode] || params.listening

    property color colA: pal[0]
    property color colB: pal[1]
    property color colC: pal[2]
    property color colD: pal[3]
    property real reachScale: par.reach
    property real flowSpeed: still ? 0 : par.flow
    property real shimmer: still ? 0 : par.shimmer
    property real accent: par.accent
    property real power: par.power
    Behavior on colA { ColorAnimation { duration: 450 } }
    Behavior on colB { ColorAnimation { duration: 450 } }
    Behavior on colC { ColorAnimation { duration: 450 } }
    Behavior on colD { ColorAnimation { duration: 450 } }
    Behavior on reachScale { NumberAnimation { duration: 400; easing.type: Easing.InOutQuad } }
    Behavior on shimmer { NumberAnimation { duration: 400 } }
    Behavior on accent { NumberAnimation { duration: 400 } }
    Behavior on power { NumberAnimation { duration: 400; easing.type: Easing.InOutQuad } }
    // the hue position integrates the speed, so a mode change never makes the colours jump
    property real hueTime: 0
    readonly property real intensity: strength * fade * power

    // ---- level (voice-reactive): a spring with a fast attack, a slower release, small overshoot ---
    property real level: 0
    property real pulse: 0
    readonly property bool reactive: !still && (mode === "listening" || mode === "speaking")
    property real _lvl: 0
    property real _vel: 0
    function _stepLevel(dt) {
        const target = reactive ? Math.max(0, Math.min(1, levelTarget)) : 0;
        // natural frequency from the wanted 10–90 % time (attack ≈ 40 ms, release ≈ 250 ms) at a
        // damping ratio of 0.62 (≈ 8 % overshoot); integrated in 4-ms steps (stable at any frame rate)
        const rising = target > _lvl;
        const w = rising ? 42 : 7.5;
        const z = 0.62;
        let t = dt;
        while (t > 0) {
            const h = Math.min(0.004, t);
            const acc = w * w * (target - _lvl) - 2 * z * w * _vel;
            _vel += acc * h;
            _lvl += _vel * h;
            t -= h;
        }
        _lvl = Math.max(-0.05, Math.min(1.15, _lvl));
        level = Math.max(0, _lvl);
        pulse = mode === "error" ? errorFlash : 0;
    }
    property real errorFlash: 0
    SequentialAnimation {
        id: flash
        NumberAnimation { target: light; property: "errorFlash"; to: 1; duration: 140; easing.type: Easing.OutQuad }
        NumberAnimation { target: light; property: "errorFlash"; to: 0; duration: 650; easing.type: Easing.InQuad }
    }
    onModeChanged: if (mode === "error") flash.restart()

    // ---- frame clock (runs only while the light is mapped and moving) -----------------------
    property real time: 0
    property real _acc: 0
    property int updates: 0                  // uniform updates (diagnostics/tests)
    FrameAnimation {
        id: clock
        running: light.mapped && !light.still
        onTriggered: {
            light._acc += frameTime;
            if (light._acc < 1.0 / light.maxFps - 0.002)
                return;
            const dt = Math.min(0.1, light._acc);
            light._acc = 0;
            light.time = (light.time + dt) % 3600;
            light.hueTime = (light.hueTime + dt * light.flowSpeed) % 1000;
            light._stepLevel(dt);
            light.updates++;
        }
    }

    LightStrip { light: light; edge: "top" }
    LightStrip { light: light; edge: "bottom" }
    LightStrip { light: light; edge: "left" }
    LightStrip { light: light; edge: "right" }
}
