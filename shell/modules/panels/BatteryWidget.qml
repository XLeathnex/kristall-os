// SPDX-License-Identifier: GPL-3.0-or-later
// Battery (small widget): a ring with the computer in it and the charge below, like the Mac's
// Batteries widget. Only shown when there is a battery.
import QtQuick
import QtQuick.Shapes
import qs.core
import qs.services

NcWidget {
    id: bw
    width: PanelMetrics.widgetSmall
    height: PanelMetrics.widgetSmall
    shapeId: "widget-battery"
    readonly property real level: Power.percent / 100
    readonly property color ringColor: Power.charging || !Power.onBattery ? Theme.color(bw.scheme, "success")
                                        : Power.percent <= 20 ? Theme.color(bw.scheme, "destructive") : Theme.color(bw.scheme, "label")

    Item {
        id: ring
        anchors.horizontalCenter: parent.horizontalCenter
        y: 18
        width: 92
        height: 92
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: Theme.color(bw.scheme, "trackOff")
                strokeWidth: 9
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: 46; centerY: 46; radiusX: 41; radiusY: 41; startAngle: 0; sweepAngle: 360 }
            }
            ShapePath {
                strokeColor: bw.ringColor
                strokeWidth: 9
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc { centerX: 46; centerY: 46; radiusX: 41; radiusY: 41; startAngle: -90; sweepAngle: 360 * Math.max(0.01, bw.level) }
            }
        }
        KIcon {
            anchors.centerIn: parent
            size: 30
            name: Power.charging ? "fill/lightning" : "laptop"
            color: Theme.color(bw.scheme, "label")
        }
    }
    KText {
        anchors.horizontalCenter: parent.horizontalCenter
        y: ring.y + ring.height + 12
        text: Power.percent + " %"
        textStyle: "title3"
        emphasized: true
        tabular: true
        scheme: bw.scheme
    }
}
