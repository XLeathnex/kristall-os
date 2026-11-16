// SPDX-License-Identifier: GPL-3.0-or-later
// Month calendar (small widget): month name, weekday initials, today in an accent circle. Weeks
// start on the locale's first day. Changes only when the date changes (the shell's clock).
import QtQuick
import qs.core
import qs.services

NcWidget {
    id: cal
    width: PanelMetrics.widgetSmall
    height: PanelMetrics.widgetSmall
    shapeId: "widget-calendar"

    readonly property date today: Clock.date
    readonly property int year: today.getFullYear()
    readonly property int month: today.getMonth()
    readonly property int first: Strings.locale.firstDayOfWeek          // 0 = Sunday … 6
    readonly property var cells: {
        const start = new Date(year, month, 1);
        const lead = (start.getDay() - first + 7) % 7;
        const days = new Date(year, month + 1, 0).getDate();
        const out = [];
        for (let i = 0; i < lead; ++i)
            out.push(0);
        for (let d = 1; d <= days; ++d)
            out.push(d);
        while (out.length % 7)
            out.push(0);
        return out;
    }

    Column {
        x: 12
        y: 10
        width: parent.width - 24
        spacing: 2
        KText {
            text: Strings.locale.standaloneMonthName(cal.month, Locale.LongFormat).toUpperCase()
            textStyle: "caption2"
            emphasized: true
            color: Theme.color(cal.scheme, "destructive")
            scheme: cal.scheme
        }
        Grid {
            columns: 7
            columnSpacing: 0
            rowSpacing: 0
            Repeater {
                model: 7
                KText {
                    required property int index
                    width: 144 / 7
                    height: 16
                    horizontalAlignment: Text.AlignHCenter
                    text: Strings.locale.dayName((cal.first + index) % 7, Locale.NarrowFormat)
                    textStyle: "caption2"
                    level: "secondaryLabel"
                    scheme: cal.scheme
                }
            }
            Repeater {
                model: cal.cells
                Item {
                    required property int modelData
                    width: 144 / 7
                    height: 18
                    readonly property bool isToday: modelData === cal.today.getDate()
                    Rectangle {
                        anchors.centerIn: parent
                        width: 17; height: 17; radius: 8.5
                        visible: parent.isToday
                        color: Theme.color(cal.scheme, "destructive")
                    }
                    KText {
                        anchors.centerIn: parent
                        visible: parent.modelData > 0
                        text: parent.modelData
                        textStyle: "caption1"
                        emphasized: parent.isToday
                        tabular: true
                        color: parent.isToday ? "#FFFFFF" : Theme.color(cal.scheme, "label")
                        scheme: cal.scheme
                    }
                }
            }
        }
    }
}
