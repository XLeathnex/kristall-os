/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QObject>
#include <QString>

namespace Kristall
{

// The on-screen keyboard only where a finger is the keyboard.
//
// Fedora's kde-settings make KWin start an input method (plasma-keyboard, ~330 MB resident) in
// every session, and the lock screen then shows a "Virtual Keyboard" button. On a laptop without
// a touchscreen neither is wanted. Our /etc/xdg/kwinrc therefore sets [Wayland] InputMethod to
// nothing, so KWin starts none by itself, and names the one to use with a touchscreen in
// [Wayland] KristallTouchInputMethod. This class gives KWin that input method while a real
// touchscreen is attached and takes it away when the last one goes (hot-plug included).
//
// "Real": KWin counts every fake-input client (KDE Connect, test drivers) as a touch device;
// hardware that libinput opened has a sysfs path, fake devices have none.
// The owner's own choice wins: if ~/.config/kwinrc has [Wayland] InputMethod (System Settings'
// Virtual Keyboard page writes it), KWin's own handling applies and we do nothing.
// Without this plugin KWin starts no input method (documented limit in setup.md).
class OnScreenKeyboard : public QObject
{
    Q_OBJECT
public:
    explicit OnScreenKeyboard(QObject *parent = nullptr);
    ~OnScreenKeyboard() override;

    void start();
    void stop();

    static bool realTouchscreen();

private:
    void update();
    bool ownerChose() const;
    QString touchCommand() const;

    bool m_running = false;
    bool m_applied = false; // we set KWin's input method command
};

} // namespace Kristall
