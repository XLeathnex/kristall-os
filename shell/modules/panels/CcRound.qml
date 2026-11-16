// SPDX-License-Identifier: GPL-3.0-or-later
// Control Center's round toggle: a 36-px circle, accent-filled with a white symbol when on, a
// quiet fill when off (KButton; its state is always the service's, never toggled locally).
import QtQuick
import qs.core

KButton {
    id: rb
    property bool on: false
    property string name: ""
    size: "large"
    variant: on ? "accent" : "fill"
    Accessible.role: Accessible.CheckBox
    Accessible.name: name
    Accessible.checkable: true
    Accessible.checked: on
}
