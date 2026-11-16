// SPDX-License-Identifier: GPL-3.0-or-later
// The microphone check: the owner says something and sees their own words, recognised on the
// laptop (MicCheck: the daemon's transcribe-only request — no Claude, works before sign-in).
import QtQuick
import qs.core
import qs.services

StepBase {
    id: st
    readonly property string name: ctl ? ctl.assistantName : "Kristall"
    icon: "microphone"
    title: Strings.t("setup.mic.title")
    subtitle: Strings.t("setup.mic.subtitle", { name: name })
    cardWidth: 600
    implicitHeight: col.implicitHeight
    primaryText: mic.phase === "heard" ? Strings.t("setup.continue") : (mic.ready ? Strings.t("setup.continue") : Strings.t("setup.skip"))

    MicCheck { id: mic; active: true }
    property alias micCheck: mic

    readonly property string blocked: !mic.connected || !mic.haveSnapshot ? "unavailable"
                                      : !mic.voiceInput ? "noMic"
                                      : !mic.ready ? "needSignIn" : ""
    function primary() {
        mic.active = false;
        ctl.next();
    }

    Column {
        id: col
        width: parent.width
        spacing: 16

        Rectangle {
            width: parent.width
            height: 132
            radius: 14
            color: Theme.color(st.scheme, "fill")
            // level meter: five bars that follow the microphone while listening
            Row {
                id: bars
                anchors.horizontalCenter: parent.horizontalCenter
                y: 18
                spacing: 5
                visible: mic.phase === "listening"
                Repeater {
                    model: 5
                    Rectangle {
                        required property int index
                        anchors.verticalCenter: parent.verticalCenter
                        width: 6
                        radius: 3
                        height: 8 + 26 * Math.max(0, Math.min(1, mic.level * (1 - Math.abs(index - 2) * 0.22)))
                        color: Theme.accentFor(st.scheme)
                        Behavior on height { NumberAnimation { duration: 80 } }
                    }
                }
            }
            KIcon {
                visible: mic.phase !== "listening"
                anchors.horizontalCenter: parent.horizontalCenter
                y: 18
                name: mic.phase === "heard" ? "fill/check-circle" : st.blocked !== "" ? "microphone-slash" : "fill/microphone"
                size: 34
                color: mic.phase === "heard" ? Theme.color(st.scheme, "success") : Theme.color(st.scheme, "secondaryLabel")
            }
            KText {
                objectName: "setup.mic.text"
                x: 20
                y: 66
                width: parent.width - 40
                horizontalAlignment: Text.AlignHCenter
                wrapMode: Text.WordWrap
                maximumLineCount: 2
                elide: Text.ElideRight
                scheme: st.scheme
                textStyle: mic.transcript !== "" ? "title3" : "body"
                emphasized: mic.transcript !== ""
                level: mic.transcript !== "" ? "label" : "secondaryLabel"
                text: mic.transcript !== "" ? "„" + mic.transcript + "“"
                      : mic.phase === "listening" ? Strings.t("setup.mic.listening")
                      : mic.phase === "nothing" ? Strings.t("setup.mic.nothing")
                      : st.blocked === "unavailable" ? Strings.t("setup.mic.unavailable")
                      : st.blocked === "noMic" ? Strings.t("setup.mic.noMic", { name: st.name })
                      : st.blocked === "needSignIn" ? Strings.t("setup.mic.needSignIn")
                      : Strings.t("setup.mic.local")
            }
        }
        Row {
            anchors.horizontalCenter: parent.horizontalCenter
            spacing: 10
            KButton {
                objectName: "setup.mic.listen"
                visible: st.blocked === ""
                text: mic.phase === "idle" ? Strings.t("setup.mic.start") : Strings.t("setup.mic.again")
                icon: "microphone"
                enabled: mic.phase !== "listening"
                scheme: st.scheme
                onClicked: mic.listen()
            }
            KButton {
                visible: st.blocked === "noMic" || mic.errorCode === "mic_unavailable"
                text: Strings.t("setup.mic.soundSettings")
                scheme: st.scheme
                onClicked: Session.openSystemSettings("kcm_pulseaudio")
            }
        }
        KText {
            visible: mic.phase === "heard"
            width: parent.width
            horizontalAlignment: Text.AlignHCenter
            text: Strings.t("setup.mic.ok") + " " + Strings.t("setup.mic.local")
            textStyle: "caption1"
            level: "secondaryLabel"
            scheme: st.scheme
        }
    }
}
