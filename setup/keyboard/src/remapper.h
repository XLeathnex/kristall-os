/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QHash>
#include <QList>
#include <QObject>
#include <QPointer>
#include <QSet>
#include <QString>

#include <chrono>

namespace KWin
{
class InputDevice;
class Window;
enum class KeyboardKeyState;
}

namespace Kristall
{

class KeySettings;

enum class AppClass {
    Normal, // Command = Control; text navigation like a Mac
    Terminal, // Command+letter = Control+Shift+letter, Control stays the terminal's Control
    Passthrough, // games, Wine, VMs, remote desktops, the lock screen: ordinary PC keys
};

// Rewrites the owner's physical keys *before* KWin sees them.
//
// Every keyboard device's keyChanged signal is disconnected from KWin's
// KeyboardInputRedirection::processKey and connected to us; we call processKey ourselves with the
// translated keys. So KWin's own xkb state, the modifiers clients receive, global shortcuts,
// the window switcher's hold-and-release and everything else see one consistent, translated
// keyboard — as if the keyboard had a Command key. The keymap is never changed: every character
// printed on the German keys (AltGr included) is produced by xkb exactly as before. Input that
// does not come from a device (the assistant's injected typing through the bridge, the
// virtual keyboard) never passes through here.
//
// Fail-safe: if anything is missing at start, nothing is rerouted; stop() hands every device back
// and releases everything we hold; a crash guard disables us after repeated compositor crashes.
class Remapper : public QObject
{
    Q_OBJECT
public:
    explicit Remapper(KeySettings *settings, QObject *parent = nullptr);
    ~Remapper() override;

    bool start();
    void stop();

    static void writeStatus(bool running, bool active, const QString &reason, int devices = 0);

private:
    enum class Mod { None, Ctrl, Meta, Alt };
    enum class Kind { Identity, Command, Option, Mapped };
    struct Held {
        Kind kind = Kind::Identity;
        QList<quint32> keys; // downstream keys this physical key holds (released in reverse)
        bool suppressCmd = false;
        bool suppressOpt = false;
    };

    void attach(KWin::InputDevice *device);
    bool detach(KWin::InputDevice *device);
    void onKey(quint32 key, KWin::KeyboardKeyState state, std::chrono::microseconds time, KWin::InputDevice *device);
    void onPress(quint32 key);
    void onRelease(quint32 key);
    void commandChord(quint32 key, AppClass cls, const QString &id);
    void optionChord(quint32 key);
    void copilotKey(quint32 key);

    // downstream (what KWin sees); reference-counted so two sources of one key stay balanced
    void down(quint32 key);
    void up(quint32 key);
    void tap(quint32 key);
    void forward(quint32 key, bool pressed);
    bool isDown(quint32 key) const { return m_down.value(key) > 0; }

    void syncCommand();
    void syncOption();
    void setCommandMod(Mod mod);
    static quint32 modKey(Mod mod);

    AppClass classify(QString *idOut = nullptr) const;
    bool physical(quint32 key) const { return m_physical.contains(key); }
    bool enabled() const;
    void releaseAll();
    void updateStatus();

    // window actions (run after the current input event, outside KWin's input processing)
    void hideActiveApp();
    void minimizeActiveWindow();
    void toggleFullScreen();
    void lockScreen();

    KeySettings *m_settings;
    QList<QPointer<KWin::InputDevice>> m_attached;
    QMetaObject::Connection m_deviceAdded;
    QMetaObject::Connection m_deviceRemoved;
    bool m_running = false;
    bool m_guardTripped = false;

    KWin::InputDevice *m_device = nullptr; // the device of the event being translated
    std::chrono::microseconds m_time{0};
    QHash<quint32, int> m_down;
    QHash<quint32, Held> m_held;
    QSet<quint32> m_physical;

    bool m_cmd = false; // physical Command held and translated
    bool m_cmdPass = false; // ... but producing plain Alt (passthrough app, or Control held first)
    Mod m_cmdMod = Mod::None;
    bool m_cmdModDown = false;
    bool m_cmdSticky = false; // switched to Meta for the switcher / Search: stays until released
    int m_cmdSuppress = 0;

    bool m_opt = false;
    Mod m_optMod = Mod::None;
    bool m_optModDown = false;
    int m_optSuppress = 0;
};

} // namespace Kristall
