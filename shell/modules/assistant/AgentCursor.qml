// SPDX-License-Identifier: GPL-3.0-or-later
// The assistant's own cursor on one output (assistant-ipc §5 agent_cursor, hands.md §8).
// A crystal-shard pointer with its own light and a label pill saying what it does. It lives on a
// small click-through Overlay surface (namespace kristall-assistant-cursor, excluded from the
// assistant's screenshots and from agent input) that is moved with layer-shell margins, so a glide
// damages only the cursor's old and new rectangles, never the screen.
//
// Timing: a glide with duration D is anchored to the daemon's timestamp of the event: it starts
// where the cursor is and arrives at ts + D on the wall clock, whatever our own receive latency;
// hands injects the action at D + 40 ms, so the owner sees the cursor settle and then the click.
// Position is computed from the clock every frame (not stepped), so a late frame never delays the
// arrival. The path bends slightly and the pointer lifts a little in flight, like a hand.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

Scope {
    id: ac
    required property var screen
    readonly property string screenName: screen ? screen.name : ""
    readonly property real ox: screen ? screen.x : 0
    readonly property real oy: screen ? screen.y : 0
    readonly property real sw: screen ? screen.width : 0
    readonly property real sh: screen ? screen.height : 0

    // ---- state ----------------------------------------------------------------------------
    property bool shown: false               // wants to be visible
    property real opacityValue: 0
    property real gx: 0                       // current global position (logical)
    property real gy: 0
    property string label: ""
    property string output: ""
    property bool held: false                // between drag_start and drag_end
    readonly property bool here: gx >= ox && gx < ox + sw && gy >= oy && gy < oy + sh
    readonly property bool mapped: here && (shown || opacityValue > 0.01)

    // glide
    property real fromX: 0
    property real fromY: 0
    property real toX: 0
    property real toY: 0
    property real t0: 0
    property real t1: 0
    property real bend: 0
    property real lift: 0
    property bool gliding: false
    property real lastEventMs: 0
    // measurements for the tests: one entry per glide
    property var arrivals: []

    readonly property var curve: [0.42, 0.0, 0.18, 1.0]
    function bezier(t) {
        // cubic-bezier(x1,y1,x2,y2) at time fraction t: solve x(s)=t (Newton), return y(s)
        const x1 = curve[0], y1 = curve[1], x2 = curve[2], y2 = curve[3];
        let s = t;
        for (let i = 0; i < 6; ++i) {
            const x = 3 * (1 - s) * (1 - s) * s * x1 + 3 * (1 - s) * s * s * x2 + s * s * s - t;
            const dx = 3 * (1 - s) * (1 - s) * x1 + 6 * (1 - s) * s * (x2 - x1) + 3 * s * s * (1 - x2);
            if (Math.abs(dx) < 1e-6)
                break;
            s = Math.max(0, Math.min(1, s - x / dx));
        }
        return 3 * (1 - s) * (1 - s) * s * y1 + 3 * (1 - s) * s * s * y2 + s * s * s;
    }

    property real _lastStep: 0
    function step() {
        const now = Date.now();
        const prevStep = _lastStep;
        _lastStep = now;
        if (now >= t1 || t1 <= t0) {
            gx = toX;
            gy = toY;
            lift = 0;
            if (gliding) {
                gliding = false;
                const a = arrivals.slice(-49);
                // prevFrame: the frame before arrival (it must still have been before the target:
                // then the cursor arrived on the first frame at or after it)
                a.push({ target: t1, arrived: now, prevFrame: prevStep, x: toX, y: toY });
                arrivals = a;
            }
            return;
        }
        const p = Math.max(0, (now - t0) / (t1 - t0));
        const e = bezier(p);
        const dx = toX - fromX, dy = toY - fromY;
        const len = Math.max(1, Math.hypot(dx, dy));
        const arc = Math.sin(Math.PI * e) * bend;
        gx = fromX + dx * e + (-dy / len) * arc;
        gy = fromY + dy * e + (dx / len) * arc;
        lift = Math.sin(Math.PI * p);
    }
    FrameAnimation {
        running: ac.gliding
        onTriggered: ac.step()
    }

    function glideTo(x, y, duration, anchorMs) {
        fromX = gx;
        fromY = gy;
        toX = x;
        toY = y;
        const dist = Math.hypot(x - gx, y - gy);
        if (duration <= 0 || dist < 0.5 || Theme.reduceMotion) {
            t0 = t1 = Date.now();
            gliding = true;
            step();
            return;
        }
        t0 = Date.now();
        t1 = Math.max(t0, anchorMs + duration);
        bend = Math.min(36, dist * 0.07) * (x < gx ? -1 : 1);
        gliding = true;
        step();
    }

    // ---- events -------------------------------------------------------------------------------
    function handle(ev, recvMs) {
        if (ev.visible === false) {
            shown = false;
            held = false;
            hideAnim.restart();
            return;
        }
        const hasPos = typeof ev.x === "number" && typeof ev.y === "number";
        if (ev.label !== undefined)
            label = ev.label || "";
        if (ev.output !== undefined)
            output = ev.output || "";
        else if (ev.pulse && ev.pulse !== "type")
            output = "";
        if (hasPos) {
            if (!shown || opacityValue < 0.05) {
                gliding = false;
                gx = toX = ev.x;
                gy = toY = ev.y;
                lift = 0;
                // appear (with an initial glide if one was asked for while hidden)
            } else {
                const dist = Math.hypot(ev.x - gx, ev.y - gy);
                let d;
                const anchor = typeof ev.ts === "number" ? Math.min(ev.ts, recvMs) : recvMs;
                if (typeof ev.duration_ms === "number") {
                    d = Math.max(0, Math.min(5000, ev.duration_ms));
                    glideTo(ev.x, ev.y, d, anchor);
                } else if (recvMs - lastEventMs < 160) {
                    // a stream of positions: follow it smoothly over the interval between events
                    glideTo(ev.x, ev.y, Math.max(16, recvMs - lastEventMs), recvMs);
                } else {
                    d = Math.max(260, Math.min(800, 220 + 0.4 * dist));
                    glideTo(ev.x, ev.y, d, recvMs);
                }
            }
        }
        lastEventMs = recvMs;
        if (!shown) {
            shown = true;
            hideAnim.stop();
            showAnim.restart();
        }
        if (ev.pulse) {
            const px = hasPos ? ev.x : toX, py = hasPos ? ev.y : toY;
            if (ev.pulse === "drag_start")
                held = true;
            else if (ev.pulse === "drag_end")
                held = false;
            ripple(ev.pulse, px, py);
        }
    }

    // ripples are placed in global coordinates; converted to window coordinates when drawn
    property var ripples: []
    property int _rippleId: 0
    property var rippleLog: []               // tests: when and where feedback was shown
    function ripple(kind, x, y) {
        const lg = rippleLog.slice(-49);
        lg.push({ kind: kind, x: x, y: y, at: Date.now() });
        rippleLog = lg;
        const r = ripples.filter(r => Date.now() - r.at < 900);
        r.push({ id: ++_rippleId, kind: kind, x: x, y: y, at: Date.now(), delay: 0 });
        if (kind === "double_click")
            r.push({ id: ++_rippleId, kind: kind, x: x, y: y, at: Date.now(), delay: 130 });
        ripples = r;
    }

    NumberAnimation {
        id: showAnim
        target: ac
        property: "opacityValue"
        to: 1
        duration: Theme.duration("short", true)
        easing.type: Easing.OutQuad
    }
    SequentialAnimation {
        id: hideAnim
        PauseAnimation { duration: 120 }
        NumberAnimation { target: ac; property: "opacityValue"; to: 0; duration: 260; easing.type: Easing.InQuad }
        ScriptAction { script: { ac.label = ""; ac.output = ""; ac.ripples = []; } }
    }

    // ---- the surface ----------------------------------------------------------------------------
    PanelWindow {
        id: win
        screen: ac.screen
        visible: ac.mapped
        color: "transparent"
        WlrLayershell.namespace: "kristall-assistant-cursor"
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        exclusionMode: ExclusionMode.Ignore
        mask: Region {}
        anchors { top: true; left: true }

        readonly property real pad: 40          // room for ripples around the hotspot
        readonly property real pillRoom: 300
        readonly property bool flipX: ac.gx - ac.ox + pillRoom > ac.sw
        readonly property bool flipY: ac.gy - ac.oy + 90 > ac.sh
        readonly property real hotX: flipX ? width - pad : pad
        readonly property real hotY: flipY ? height - pad : pad
        implicitWidth: pad + pillRoom
        implicitHeight: pad + 84
        // the surface stays on the output (margins clamped); near an edge the content shifts
        // inside it instead
        readonly property real wantX: ac.gx - ac.ox - hotX
        readonly property real wantY: ac.gy - ac.oy - hotY
        readonly property int mx: Math.max(0, Math.min(Math.floor(ac.sw - width), Math.round(wantX)))
        readonly property int my: Math.max(0, Math.min(Math.floor(ac.sh - height), Math.round(wantY)))
        margins {
            left: win.mx
            top: win.my
        }
        // new margins take effect with the surface's next commit: make sure there is one even when
        // the content did not change (an appearance without a glide)
        onMxChanged: stage.repaint()
        onMyChanged: stage.repaint()

        Item {
            id: stage
            function repaint() {
                if (Window.window)
                    Window.window.update();
            }
            x: win.wantX - win.mx
            y: win.wantY - win.my
            width: win.width
            height: win.height
            opacity: ac.opacityValue

            // ripples (click feedback) at their own global positions
            Repeater {
                model: ac.ripples
                delegate: Item {
                    id: rp
                    required property var modelData
                    x: modelData.x - ac.gx + win.hotX
                    y: modelData.y - ac.gy + win.hotY
                    property real p: 0
                    readonly property color tint: modelData.kind === "right_click" ? "#B18CFF" : modelData.kind === "scroll" ? "#7FD8FF" : "#8FF0FF"
                    Rectangle {
                        anchors.centerIn: parent
                        width: 8 + 46 * rp.p
                        height: width
                        radius: width / 2
                        color: Qt.alpha(rp.tint, 0.22 * (1 - rp.p))
                        border.width: 2
                        border.color: Qt.alpha(rp.tint, 0.95 * (1 - rp.p))
                    }
                    SequentialAnimation on p {
                        running: true
                        PauseAnimation { duration: rp.modelData.delay }
                        NumberAnimation { from: 0; to: 1; duration: Theme.reduceMotion ? 1 : 520; easing.type: Easing.OutCubic }
                    }
                }
            }

            // the pointer (hotspot = tip at 12,12 of the 48-px artwork)
            Image {
                id: pointer
                source: Qt.resolvedUrl("assets/cursor.svg")
                sourceSize: Qt.size(48 * (win.devicePixelRatio || 1), 48 * (win.devicePixelRatio || 1))
                width: 48
                height: 48
                x: win.hotX - 12
                y: win.hotY - 12
                smooth: true
                transformOrigin: Item.TopLeft
                scale: (ac.held ? 0.9 : 1) * (1 + 0.07 * ac.lift)
                Behavior on scale { enabled: !ac.gliding; NumberAnimation { duration: 120 } }
            }

            // label pill
            Rectangle {
                id: pill
                visible: ac.label !== "" || ac.output !== ""
                readonly property real gap: 30
                x: win.flipX ? win.hotX - gap + 6 - width : win.hotX + gap - 6
                y: win.flipY ? win.hotY - gap - height + 4 : win.hotY + gap - 8
                height: col.implicitHeight + 10
                width: Math.min(win.pillRoom - 40, col.implicitWidth + 22)
                radius: Math.min(height / 2, 13)
                color: Theme.dark ? Qt.rgba(0.07, 0.09, 0.16, 0.86) : Qt.rgba(0.08, 0.10, 0.20, 0.82)
                border.width: 1 / Math.max(1, win.devicePixelRatio || 1)
                border.color: Qt.rgba(0.65, 0.9, 1.0, 0.45)
                Column {
                    id: col
                    x: 11
                    anchors.verticalCenter: parent.verticalCenter
                    spacing: 1
                    Row {
                        spacing: 5
                        visible: ac.label !== ""
                        KIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            size: 11
                            name: "kristall/assistant"
                            color: "#8FF0FF"
                        }
                        KText {
                            anchors.verticalCenter: parent.verticalCenter
                            text: ac.label
                            textStyle: "callout"
                            emphasized: true
                            scheme: "dark"
                            elide: Text.ElideRight
                            width: Math.min(implicitWidth, win.pillRoom - 80)
                        }
                    }
                    Row {
                        spacing: 5
                        visible: ac.output !== ""
                        KIcon {
                            anchors.verticalCenter: parent.verticalCenter
                            size: 11
                            name: "keyboard"
                            color: Qt.rgba(1, 1, 1, 0.6)
                        }
                        Text {
                            anchors.verticalCenter: parent.verticalCenter
                            text: ac.output
                            font.family: "monospace"
                            font.pixelSize: 11
                            color: Qt.rgba(1, 1, 1, 0.85)
                            elide: Text.ElideRight
                            width: Math.min(implicitWidth, win.pillRoom - 80)
                            renderType: Text.NativeRendering
                        }
                    }
                }
            }
        }
    }
}
