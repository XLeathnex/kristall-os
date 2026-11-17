// SPDX-License-Identifier: GPL-3.0-or-later
// The assistant in two sentences, and "Sign in with Claude": Claude Code is installed with
// Anthropic's official installer and signed in through the daemon's account commands — the
// browser opens, the owner signs in there, we show progress and success. Every failure says what
// happened in plain words and offers "Try Again"; "Not Now" is always possible. Also opened on its
// own (request setup claude-signin) from the assistant's interface.
import QtQuick
import Quickshell
import qs.core
import qs.services

StepBase {
    id: st
    readonly property var acc: ctl ? ctl.account : null
    readonly property string name: ctl ? ctl.assistantName : "Kristall"
    readonly property string phase: acc ? acc.phase : "idle"
    readonly property bool signin: ctl && ctl.mode === "signin"
    icon: "sparkle"
    title: signin ? Strings.t("setup.signin.title") : Strings.t("setup.assistant.title")
    subtitle: signin ? Strings.t("setup.signin.subtitle", { name: name }) : Strings.t("setup.assistant.subtitle", { name: name })
    cardWidth: 600
    implicitHeight: col.implicitHeight
    showBack: !busyNow

    readonly property bool busyNow: phase === "working" || phase === "browser" || phase === "checking"
    yieldToApps: phase === "browser"          // the owner signs in in the browser: get out of its way
    primaryText: phase === "ready" ? (signin ? Strings.t("setup.done") : Strings.t("setup.continue"))
                 : phase === "failed" ? Strings.t("setup.tryAgain")
                 : Strings.t("setup.assistant.signin")
    primaryEnabled: !busyNow
    secondaryText: phase === "ready" ? "" : busyNow ? Strings.t("setup.assistant.cancel") : (signin ? Strings.t("setup.later") : Strings.t("setup.later"))

    // ctl arrives just after creation (the card sets it when the step is loaded)
    onAccChanged: if (acc && !busyNow) acc.check()

    function primary() {
        if (phase === "ready") {
            if (signin)
                ctl.close();
            else
                ctl.next();
            return;
        }
        acc.signIn();
    }
    function secondary() {
        if (busyNow) {
            acc.cancel();
            return;
        }
        acc.cancel();
        if (signin)
            ctl.close();
        else
            ctl.next();
    }
    function failText() {
        const e = acc ? acc.error : null;
        if (e && e.message && (e.message.de || e.message.en) && e.code !== "failed")
            return Strings.pick(e.message);
        if (e && e.code === "offline")
            return Strings.t("setup.assistant.fail.offline");
        if (acc && (acc.failedStep === "install" || acc.failedStep === "update"))
            return Strings.t("setup.assistant.fail.install");
        if (acc && acc.failedStep === "login")
            return Strings.t("setup.assistant.fail.login");
        return Strings.t("setup.assistant.fail.generic");
    }

    Column {
        id: col
        width: parent.width
        spacing: 16

        // what is happening
        Rectangle {
            width: parent.width
            height: inner.implicitHeight + 32
            radius: 14
            color: Theme.color(st.scheme, "fill")
            Column {
                id: inner
                x: 20
                y: 16
                width: parent.width - 40
                spacing: 10

                Row {          // the state line with its symbol
                    spacing: 10
                    width: parent.width
                    Item {
                        width: 22
                        height: 22
                        anchors.verticalCenter: parent.verticalCenter
                        KIcon {
                            anchors.centerIn: parent
                            visible: !st.busyNow
                            name: st.phase === "ready" ? "fill/check-circle" : st.phase === "failed" ? "fill/warning-circle" : "fill/user-circle"
                            size: 22
                            color: st.phase === "ready" ? Theme.color(st.scheme, "success") : st.phase === "failed" ? Theme.color(st.scheme, "warning") : Theme.accentFor(st.scheme)
                        }
                        Spinner { anchors.centerIn: parent; visible: st.busyNow; running: visible; scheme: st.scheme }
                    }
                    KText {
                        objectName: "setup.assistant.state"
                        width: parent.width - 32
                        anchors.verticalCenter: parent.verticalCenter
                        wrapMode: Text.WordWrap
                        emphasized: true
                        scheme: st.scheme
                        text: st.phase === "ready" ? Strings.t("setup.assistant.ready", { name: st.name })
                              : st.phase === "failed" ? st.failText()
                              : st.phase === "cancelled" ? Strings.t("setup.assistant.cancelled")
                              : st.phase === "checking" ? Strings.t("setup.assistant.stage.verifying")
                              : st.busyNow && st.acc.stage !== "" ? Strings.t("setup.assistant.stage." + st.acc.stage)
                              : Strings.t("setup.assistant.signinNote", { name: st.name })
                    }
                }
                Rectangle {          // installer progress
                    visible: st.busyNow && st.acc.percent >= 0
                    width: parent.width
                    height: 6
                    radius: 3
                    color: Theme.color(st.scheme, "trackOff")
                    Rectangle {
                        width: Math.max(6, parent.width * Math.min(1, st.acc ? st.acc.percent / 100 : 0))
                        height: parent.height
                        radius: 3
                        color: Theme.accentFor(st.scheme)
                        Behavior on width { NumberAnimation { duration: Theme.duration("medium") } }
                    }
                }
                KText {
                    visible: st.phase === "browser"
                    width: parent.width
                    wrapMode: Text.WordWrap
                    text: Strings.t("setup.assistant.browserNote")
                    textStyle: "callout"
                    level: "secondaryLabel"
                    scheme: st.scheme
                }
                KButton {
                    objectName: "setup.assistant.openBrowser"
                    visible: st.phase === "browser" && st.acc.url !== ""
                    text: Strings.t("setup.assistant.openBrowser")
                    size: "small"
                    scheme: st.scheme
                    onClicked: st.acc.openBrowser()
                }
                Column {          // a code from the browser, if it shows one
                    visible: st.phase === "browser" && st.acc.needCode
                    width: parent.width
                    spacing: 8
                    KText { text: Strings.t("setup.assistant.code"); textStyle: "callout"; scheme: st.scheme }
                    Row {
                        spacing: 8
                        KTextField {
                            id: codeField
                            objectName: "setup.assistant.code"
                            width: 300
                            placeholder: Strings.t("setup.assistant.codeField")
                            scheme: st.scheme
                            onAccepted: { st.acc.sendCode(text); text = ""; }
                        }
                        KButton {
                            text: Strings.t("setup.assistant.codeSend")
                            variant: "accent"
                            scheme: st.scheme
                            onClicked: { st.acc.sendCode(codeField.text); codeField.text = ""; }
                        }
                    }
                }
            }
        }
        KText {
            visible: st.phase !== "ready"
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            wrapMode: Text.WordWrap
            text: Strings.t("setup.assistant.later", { name: st.name })
            textStyle: "caption1"
            level: "tertiaryLabel"
            scheme: st.scheme
        }
    }
}
