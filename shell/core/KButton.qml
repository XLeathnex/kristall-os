// SPDX-License-Identifier: GPL-3.0-or-later
// Push button, thick-capsule style.
// variant: "fill" (translucent fill, sits on glass or a material) | "accent" (prominent, accent
//          fill — the default action) | "plain" (no fill until hovered) | "destructive" |
//          "glass" (its own glass shape; set glassSurface) ;  size: "small" | "regular" | "large"
// Icon-only buttons (text "") are circles. `checked` + `checkable` turns it into a toggle button
// (accent fill when on, like Control Center's round buttons).
import QtQuick
import qs.services

Item {
    id: b
    property string text: ""
    property string icon: ""
    property string variant: "fill"
    property string size: "regular"
    property string scheme: Theme.scheme
    property bool checkable: false
    property bool checked: false
    property GlassSurface glassSurface: null
    property string shapeId: "button-" + text + icon
    property real minWidth: 0
    property string showState: ""     // gallery: "hover" | "pressed" | "focus"
    readonly property bool hovered: hover.hovered || showState === "hover"
    readonly property bool down: tap.pressed || showState === "pressed"
    signal clicked()

    readonly property real h: size === "small" ? Theme.size.controlSmall : size === "large" ? Theme.size.controlLarge : Theme.size.control
    readonly property real padH: size === "small" ? 10 : size === "large" ? 18 : 14
    readonly property bool iconOnly: text === "" && icon !== ""
    readonly property bool prominent: variant === "accent" || variant === "destructive" || (checkable && checked)
    readonly property string contentScheme: prominent ? "dark" : (variant === "glass" && glassShape.item ? glassShape.item.scheme : scheme)

    implicitHeight: h
    implicitWidth: iconOnly ? h : Math.max(minWidth, row.implicitWidth + 2 * padH, h * 2)
    activeFocusOnTab: true
    opacity: enabled ? 1 : 0.45
    Accessible.role: Accessible.Button
    Accessible.name: text
    Accessible.onPressAction: b.clicked()

    function _activate() {
        if (!enabled)
            return;
        if (checkable)
            checked = !checked;
        clicked();
    }
    Keys.onSpacePressed: _activate()
    Keys.onReturnPressed: _activate()

    Loader {
        id: glassShape
        anchors.fill: parent
        active: b.variant === "glass" && b.glassSurface !== null
        sourceComponent: GlassShape {
            shapeId: b.shapeId
            surface: b.glassSurface
            role: "control"
            kind: "capsule"
            pressed: b.down
            pointerActive: hover.hovered
            pointer: hover.point.position
        }
    }

    Rectangle {
        id: bg
        anchors.fill: parent
        radius: height / 2
        visible: b.variant !== "glass" || !glassShape.active
        color: {
            if (b.variant === "destructive")
                return Theme.color(b.scheme, "destructive");
            if (b.prominent)
                return Theme.accentFor(b.scheme);
            if (b.variant === "plain")
                return "transparent";
            return Theme.color(b.scheme, "fill");
        }
        Behavior on color { ColorAnimation { duration: Theme.duration("micro", true) } }
    }
    // hover / press veil (the same for every variant)
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: b.down ? Theme.color(b.prominent ? "light" : b.scheme, "pressed") : Theme.color(b.prominent ? "light" : b.scheme, "hover")
        visible: b.enabled && (b.down || b.hovered)
    }

    Row {
        id: row
        anchors.centerIn: parent
        spacing: 6
        KIcon {
            visible: b.icon !== ""
            anchors.verticalCenter: parent.verticalCenter
            name: b.icon
            size: b.size === "large" ? 18 : b.size === "small" ? 13 : 15
            scheme: b.contentScheme
            color: Theme.color(b.contentScheme, "label")
        }
        KText {
            visible: b.text !== ""
            anchors.verticalCenter: parent.verticalCenter
            text: b.text
            textStyle: b.size === "small" ? "controlSmall" : "control"
            emphasized: b.variant === "accent"
            scheme: b.contentScheme
        }
    }

    KFocusRing { targetRadius: b.height / 2; scheme: b.scheme }

    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        id: tap
        onTapped: { b.forceActiveFocus(Qt.MouseFocusReason); b._activate(); }
    }
}
