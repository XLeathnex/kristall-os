// SPDX-License-Identifier: GPL-3.0-or-later
// One output of the Setup Assistant: a full-output Overlay surface ("kristall-setup-main",
// exclusive keyboard on the main output). The welcome is our own artwork; every other step is a
// glass card over the real, slightly dimmed desktop — so a change of look, glass or size is seen
// at once on the menu bar, Dock and wallpaper around it. Steps whose choice is about looks move
// the card to the left to leave the desktop visible.
import QtQuick
import Quickshell
import Quickshell.Wayland
import qs.core
import qs.services

PanelWindow {
    id: win
    property var ctl: null
    property bool main: true
    readonly property string screenName: screen ? screen.name : ""
    readonly property bool welcome: ctl.step === "welcome" && ctl.mode === "full"
    readonly property var stepItem: body.item
    readonly property string side: stepItem && stepItem.side ? stepItem.side : "center"
    // a step that sends the owner to another app (sign-in in the browser) steps aside: the card
    // moves to the lower right, the desktop is no longer dimmed or blocked, and the keyboard goes
    // to whatever the owner clicks — otherwise the card would cover and lock the browser
    readonly property bool yielding: main && !welcome && stepItem !== null && stepItem.yieldToApps === true

    WlrLayershell.namespace: "kristall-setup-main"
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.keyboardFocus: !main ? WlrKeyboardFocus.None : (yielding ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.Exclusive)
    mask: yielding ? cardOnly : null
    Region { id: cardOnly; item: card }
    exclusionMode: ExclusionMode.Ignore
    anchors { top: true; bottom: true; left: true; right: true }
    color: "transparent"

    GlassSurface {
        id: gs
        key: "setup-" + win.screenName
        layerNamespace: "kristall-setup-main"
        output: win.screenName
    }

    // everything lives in one focus scope whose key handler sees what the focused control leaves
    Item {
        id: keys
        anchors.fill: parent
        focus: win.main
        Keys.onPressed: ev => {
            if (win.welcome) {
                if (ev.key === Qt.Key_Return || ev.key === Qt.Key_Enter) {
                    win.ctl.next();
                    ev.accepted = true;
                }
                return;
            }
            if (win.stepItem && win.stepItem.keyPressed(ev)) {
                ev.accepted = true;
                return;
            }
            // a text field handled Return itself (TextInput emits accepted and lets the key through)
            const fi = keys.Window.activeFocusItem;
            if ((ev.key === Qt.Key_Return || ev.key === Qt.Key_Enter) && fi && fi.cursorPosition !== undefined)
                return;
            if ((ev.key === Qt.Key_Return || ev.key === Qt.Key_Enter) && win.stepItem && win.stepItem.primaryEnabled) {
                win.stepItem.primary();
                ev.accepted = true;
            } else if (ev.key === Qt.Key_Escape) {
                if (win.ctl.mode === "signin")
                    win.ctl.close();
                else if (backButton.visible)
                    win.ctl.back();
                ev.accepted = true;
            }
        }

    // ---- backdrop -------------------------------------------------------------------------------
    Backdrop {
        anchors.fill: parent
        dark: Theme.dark
        opacity: win.welcome ? 1 : 0
        visible: opacity > 0
        Behavior on opacity { NumberAnimation { duration: Theme.duration("long", true); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("easeInOut") } }
    }
    Rectangle {            // the desktop behind the card, dimmed (less when the card shows the looks)
        anchors.fill: parent
        color: Qt.rgba(0, 0, 0, Theme.dark ? 0.45 : 0.28)
        opacity: win.welcome || win.yielding ? 0 : (win.side === "left" ? 0.35 : 1)
        Behavior on opacity { NumberAnimation { duration: Theme.duration("medium", true) } }
    }
    MouseArea { anchors.fill: parent; acceptedButtons: Qt.AllButtons }   // the desktop is not operated meanwhile

    // ---- the welcome (main output only) ----------------------------------------------------------
    Loader {
        id: welcomeLoader
        anchors.fill: parent
        active: win.main && win.welcome
        sourceComponent: StepWelcome { ctl: win.ctl; scheme: Theme.scheme }
    }

    // ---- the card --------------------------------------------------------------------------------
    readonly property real cardW: stepItem ? stepItem.cardWidth : 600
    readonly property real pad: 40
    readonly property real footerH: 76
    readonly property real cardH: Math.min(win.height - Theme.size.bar - 32,
                                           Math.max(460, header.height + body.height + footerH + pad + 24))
    GlassShape {
        id: card
        objectName: "setup.card"
        shapeId: "setup-card"
        surface: gs
        role: "panel"
        // a card full of text over any background: more tint than a Control Center panel, and
        // almost solid while it sits over the owner's apps (sign-in next to the browser: no dim
        // there, and a white page of text showed through and fought with the card's own text)
        tintAmount: win.yielding ? 0.97 : Math.max(Theme.glassTint("panel"), 0.93)
        KGlassRim {            // a crisp edge where the card meets a white window
            radius: card.radius
            scheme: card.scheme
            visible: card.glassDrawn
        }
        visible: win.main && !win.welcome
        width: keys.cardW
        height: keys.cardH
        x: win.yielding ? win.width - width - 24 : (win.side === "left" ? Math.max(32, Math.round(win.width * 0.06)) : Math.round((win.width - width) / 2))
        y: win.yielding ? win.height - height - 24 : Math.round(Theme.size.bar + (win.height - Theme.size.bar - height) / 2)
        Behavior on y { NumberAnimation { duration: Theme.duration("long"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        Behavior on x { NumberAnimation { duration: Theme.duration("long"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        Behavior on height { NumberAnimation { duration: Theme.duration("medium"); easing.type: Easing.BezierSpline; easing.bezierCurve: Theme.curve("smooth") } }
        MouseArea { anchors.fill: parent }

        Column {
            id: header
            x: keys.pad
            y: keys.pad - 4
            width: card.width - 2 * keys.pad
            spacing: 0
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                width: 64
                height: 64
                radius: 32
                color: Qt.rgba(Theme.accentFor(card.scheme).r, Theme.accentFor(card.scheme).g, Theme.accentFor(card.scheme).b, card.scheme === "dark" ? 0.24 : 0.14)
                visible: win.stepItem && win.stepItem.icon !== ""
                KIcon {
                    anchors.centerIn: parent
                    name: win.stepItem ? win.stepItem.icon : ""
                    size: 32
                    color: Theme.accentFor(card.scheme)
                }
            }
            Item { width: 1; height: 16 }
            KText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                text: win.stepItem ? win.stepItem.title : ""
                textStyle: "largeTitle"
                emphasized: true
                scheme: card.scheme
            }
            Item { width: 1; height: 8 }
            KText {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                visible: text !== ""
                text: win.stepItem ? win.stepItem.subtitle : ""
                textStyle: "title3"
                level: "secondaryLabel"
                lineHeightMode: Text.ProportionalHeight
                lineHeight: 1.08
                scheme: card.scheme
            }
            Item { width: 1; height: 24 }
        }

        Loader {
            id: body
            x: keys.pad
            y: header.y + header.height
            width: card.width - 2 * keys.pad
            height: item ? item.implicitHeight : 0
            focus: true
            readonly property string stepName: win.welcome ? "" : win.ctl.step
            source: stepName !== "" ? "Step" + stepName.charAt(0).toUpperCase() + stepName.slice(1) + ".qml" : ""
            onLoaded: {
                item.ctl = win.ctl;
                item.scheme = Qt.binding(() => card.scheme);
                item.surface = gs;
                item.opacity = 0;
                fade.restart();
            }
            NumberAnimation {
                id: fade
                target: body.item
                property: "opacity"
                from: 0
                to: 1
                duration: Theme.duration("medium", true)
                easing.type: Easing.BezierSpline
                easing.bezierCurve: Theme.curve("easeOut")
            }
        }

        // footer: Back · progress · secondary · Continue
        Item {
            id: footer
            x: keys.pad - 12
            width: card.width - 2 * (keys.pad - 12)
            height: keys.footerH
            anchors.bottom: parent.bottom
            KButton {
                id: backButton
                objectName: "setup.back"
                anchors.left: parent.left
                anchors.verticalCenter: parent.verticalCenter
                visible: win.ctl.mode === "full" && win.stepItem !== null && win.stepItem.showBack && win.ctl.stepIndex > 0
                text: Strings.t("setup.back")
                icon: "caret-left"
                variant: "plain"
                scheme: card.scheme
                onClicked: win.ctl.back()
            }
            Row {        // progress: centred, but never under the buttons (long German labels)
                id: dots
                readonly property real leftEdge: backButton.visible ? backButton.x + backButton.width + 12 : 0
                readonly property real rightEdge: buttons.x - 12
                x: Math.round(Math.max(leftEdge, Math.min((footer.width - width) / 2, rightEdge - width)))
                anchors.verticalCenter: parent.verticalCenter
                spacing: 6
                visible: win.ctl.mode === "full" && rightEdge - leftEdge >= width
                Repeater {
                    model: win.ctl.visibleSteps.length - 1      // the welcome has no dot
                    Rectangle {
                        required property int index
                        width: index === win.ctl.stepIndex - 1 ? 16 : 6
                        height: 6
                        radius: 3
                        color: index === win.ctl.stepIndex - 1 ? Theme.accentFor(card.scheme) : Theme.color(card.scheme, "quaternaryLabel")
                        Behavior on width { NumberAnimation { duration: Theme.duration("medium") } }
                    }
                }
            }
            Row {
                id: buttons
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                spacing: 8
                KButton {
                    id: secondaryButton
                    objectName: "setup.secondary"
                    visible: win.stepItem !== null && win.stepItem.secondaryText !== ""
                    text: win.stepItem ? win.stepItem.secondaryText : ""
                    variant: "plain"
                    scheme: card.scheme
                    onClicked: win.stepItem.secondary()
                }
                KButton {
                    id: primaryButton
                    objectName: "setup.primary"
                    text: win.stepItem ? win.stepItem.primaryText : ""
                    enabled: win.stepItem !== null && win.stepItem.primaryEnabled
                    variant: "accent"
                    minWidth: 112
                    scheme: card.scheme
                    onClicked: win.stepItem.primary()
                }
            }
        }
    }

    }
    // Return is the step's primary action (the Mac's default button) whichever button has the
    // keyboard focus — after a click on "Noch einmal" the focus stays on that button, and Return
    // used to press it again instead of Weiter. Space still presses the focused button. A text
    // field keeps Return (it uses it itself: the name, the Wi-Fi password). A shortcut runs before
    // the focused control sees the key; the key handler above stays for the welcome.
    readonly property bool _textFocused: {
        const fi = keys.Window.activeFocusItem;
        return fi !== null && fi.cursorPosition !== undefined;
    }
    Shortcut {
        sequences: ["Return", "Enter"]
        context: Qt.WindowShortcut
        enabled: win.main && !win.welcome && !win._textFocused && win.stepItem !== null && win.stepItem.primaryEnabled
        onActivated: win.stepItem.primary()
    }

    // keep keyboard focus in the window when the step changes
    Connections {
        target: win.ctl
        function onStepChanged() { Qt.callLater(() => { if (win.main) keys.forceActiveFocus(); }); }
    }
    Component.onCompleted: {
        if (main) {
            ctl.mainWindow = win;
            keys.forceActiveFocus();
        }
    }
    Component.onDestruction: if (ctl && ctl.mainWindow === win) ctl.mainWindow = null
}
