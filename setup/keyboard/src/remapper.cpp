/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "remapper.h"
#include "keysettings.h"

#include "core/inputdevice.h"
#include "input.h"
#include "keyboard_input.h"
#include "wayland/seat.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QJsonObject>
#include <QRegularExpression>
#include <QSaveFile>
#include <QTimer>

#include <linux/input-event-codes.h>

#include <functional>

using KWin::KeyboardKeyState;

namespace Kristall
{

// ------------------------------------------------------------------------------------ app classes

// Terminals: Command+letter becomes Control+Shift+letter (the terminal's copy, paste, new tab …),
// so the physical Control key keeps meaning Control (Control-C interrupts). Same list as the
// bridge's terminal detection, plus `keyboard.terminalApps`.
static const QStringList s_terminals = {
    QStringLiteral("org.kde.konsole"), QStringLiteral("konsole"), QStringLiteral("foot"), QStringLiteral("footclient"),
    QStringLiteral("org.gnome.console"), QStringLiteral("kgx"), QStringLiteral("org.gnome.terminal"), QStringLiteral("gnome-terminal-server"),
    QStringLiteral("kitty"), QStringLiteral("alacritty"), QStringLiteral("org.wezfurlong.wezterm"), QStringLiteral("com.mitchellh.ghostty"),
    QStringLiteral("app.devsuite.ptyxis"), QStringLiteral("org.gnome.ptyxis"), QStringLiteral("xterm"), QStringLiteral("org.kde.yakuake"),
    QStringLiteral("tilix"), QStringLiteral("com.gexperts.tilix"), QStringLiteral("io.elementary.terminal"), QStringLiteral("blackbox"),
    QStringLiteral("com.raggesilver.blackbox")};

// Ordinary PC keys: games, Wine/Proton (Roblox Studio runs in Wine: its windows are "*.exe"),
// emulators, virtual machines and remote desktops. Wildcards allowed; plus
// `keyboard.passthroughApps`. Apps that inhibit compositor shortcuts (VMs, remote desktops) and
// the lock screen are passthrough too.
static const QStringList s_passthrough = {
    QStringLiteral("*.exe"), QStringLiteral("wine"), QStringLiteral("wine-*"), QStringLiteral("winecfg"), QStringLiteral("steam_app_*"),
    QStringLiteral("steam_proton"), QStringLiteral("gamescope"), QStringLiteral("org.vinegarhq.sober"), QStringLiteral("sober"),
    QStringLiteral("org.vinegarhq.vinegar"), QStringLiteral("roblox*"), QStringLiteral("minecraft*"), QStringLiteral("org.libretro.retroarch"),
    QStringLiteral("retroarch"), QStringLiteral("dosbox*"), QStringLiteral("org.dolphin_emu.dolphin-emu"), QStringLiteral("dolphin-emu"),
    QStringLiteral("virt-manager"), QStringLiteral("org.virt_manager.virt-manager"), QStringLiteral("virt-viewer"), QStringLiteral("remote-viewer"),
    QStringLiteral("org.remmina.remmina"), QStringLiteral("remmina"), QStringLiteral("org.kde.krdc"), QStringLiteral("krdc"),
    QStringLiteral("xfreerdp"), QStringLiteral("wlfreerdp"), QStringLiteral("sdl-freerdp"), QStringLiteral("org.gnome.boxes"),
    QStringLiteral("virtualbox*"), QStringLiteral("vmware*"), QStringLiteral("com.moonlight_stream.moonlight"), QStringLiteral("moonlight"),
    QStringLiteral("com.parsecgaming.parsec"), QStringLiteral("parsecd")};

static bool matches(const QStringList &patterns, const QStringList &ids)
{
    for (const QString &p : patterns) {
        if (p.contains(QLatin1Char('*'))) {
            const QRegularExpression re(QRegularExpression::wildcardToRegularExpression(p), QRegularExpression::CaseInsensitiveOption);
            for (const QString &id : ids) {
                if (re.match(id).hasMatch()) {
                    return true;
                }
            }
        } else if (ids.contains(p)) {
            return true;
        }
    }
    return false;
}

static const char *className(AppClass c)
{
    switch (c) {
    case AppClass::Normal:
        return "app";
    case AppClass::Terminal:
        return "terminal";
    case AppClass::Passthrough:
        return "passthrough";
    }
    return "?";
}

static bool isModifierKey(quint32 k)
{
    switch (k) {
    case KEY_LEFTSHIFT:
    case KEY_RIGHTSHIFT:
    case KEY_LEFTCTRL:
    case KEY_RIGHTCTRL:
    case KEY_LEFTALT:
    case KEY_RIGHTALT: // AltGr on the German layout: never touched
    case KEY_LEFTMETA:
    case KEY_RIGHTMETA:
    case KEY_CAPSLOCK:
    case KEY_NUMLOCK:
        return true;
    default:
        return false;
    }
}

static bool isLetterKey(quint32 k)
{
    return (k >= KEY_Q && k <= KEY_P) || (k >= KEY_A && k <= KEY_L) || (k >= KEY_Z && k <= KEY_M);
}

// ------------------------------------------------------------------------------------ status & guard

static QString runtimePath(const QString &name)
{
    const QString dir = qEnvironmentVariable("XDG_RUNTIME_DIR") + QStringLiteral("/kristall");
    QDir().mkpath(dir);
    QFile::setPermissions(dir, QFileDevice::ReadOwner | QFileDevice::WriteOwner | QFileDevice::ExeOwner);
    return dir + QLatin1Char('/') + name;
}

void Remapper::writeStatus(bool running, bool active, const QString &reason, int devices)
{
    if (qEnvironmentVariableIsEmpty("XDG_RUNTIME_DIR")) {
        return;
    }
    QSaveFile f(runtimePath(QStringLiteral("keyboard.json")));
    if (!f.open(QIODevice::WriteOnly)) {
        return;
    }
    const QJsonObject o{{QStringLiteral("version"), 1},
                        {QStringLiteral("running"), running},
                        {QStringLiteral("active"), active},
                        {QStringLiteral("reason"), reason},
                        {QStringLiteral("devices"), devices}};
    f.write(QJsonDocument(o).toJson(QJsonDocument::Compact) + "\n");
    f.commit();
}

// A KWin plugin that crashes the compositor takes the session down with it. Three compositor
// starts within three minutes that never reached a minute of uptime with us loaded: we stay out of
// the way for the rest of the session (keys behave as stock) and say so in the status file.
static bool guardTripped()
{
    if (qEnvironmentVariableIsEmpty("XDG_RUNTIME_DIR")) {
        return false;
    }
    const QString path = runtimePath(QStringLiteral("keyboard.guard"));
    const qint64 now = QDateTime::currentSecsSinceEpoch();
    QList<qint64> starts;
    QFile f(path);
    if (f.open(QIODevice::ReadOnly)) {
        for (const QByteArray &line : f.readAll().split('\n')) {
            bool ok = false;
            const qint64 t = line.trimmed().toLongLong(&ok);
            if (ok && now - t < 180) {
                starts << t;
            }
        }
        f.close();
    }
    starts << now;
    QSaveFile out(path);
    if (out.open(QIODevice::WriteOnly)) {
        for (qint64 t : std::as_const(starts)) {
            out.write(QByteArray::number(t) + "\n");
        }
        out.commit();
    }
    return starts.size() > 3;
}

// ------------------------------------------------------------------------------------ lifecycle

Remapper::Remapper(KeySettings *settings, QObject *parent)
    : QObject(parent)
    , m_settings(settings)
{
    connect(m_settings, &KeySettings::changed, this, &Remapper::updateStatus);
}

Remapper::~Remapper()
{
    stop();
}

bool Remapper::start()
{
    if (!KWin::input() || !KWin::input()->keyboard() || !KWin::waylandServer()) {
        qCWarning(KRISTALL_KEYBOARD) << "disabled: KWin is not running as a Wayland compositor";
        writeStatus(false, false, QStringLiteral("no-input"));
        return false;
    }
    if (guardTripped()) {
        m_guardTripped = true;
        qCWarning(KRISTALL_KEYBOARD) << "the compositor restarted repeatedly with Mac shortcuts loaded; keys behave as stock for this session";
        writeStatus(true, false, QStringLiteral("crash-guard"));
        return true; // loaded, but nothing is rerouted
    }
    QTimer::singleShot(60 * 1000, this, []() {
        QFile::remove(runtimePath(QStringLiteral("keyboard.guard")));
    });
    const auto devices = KWin::input()->devices();
    for (KWin::InputDevice *d : devices) {
        attach(d);
    }
    m_deviceAdded = connect(KWin::input(), &KWin::InputRedirection::deviceAdded, this, &Remapper::attach);
    m_deviceRemoved = connect(KWin::input(), &KWin::InputRedirection::deviceRemoved, this, [this](KWin::InputDevice *d) {
        // keys still held on a device that goes away are released
        const auto held = m_physical;
        if (d == m_device) {
            for (quint32 k : held) {
                onRelease(k);
                m_physical.remove(k);
            }
        }
        detach(d);
    });
    m_running = true;
    updateStatus();
    qCInfo(KRISTALL_KEYBOARD) << "started; devices" << m_attached.size() << "macShortcuts" << m_settings->macShortcuts();
    return true;
}

void Remapper::stop()
{
    if (!m_running) {
        return;
    }
    releaseAll();
    disconnect(m_deviceAdded);
    disconnect(m_deviceRemoved);
    const auto attached = m_attached;
    for (const auto &d : attached) {
        if (d) {
            detach(d);
        }
    }
    m_attached.clear();
    m_running = false;
    writeStatus(false, false, QStringLiteral("stopped"));
}

void Remapper::attach(KWin::InputDevice *device)
{
    if (!device || !KWin::input() || !KWin::input()->keyboard()) {
        return;
    }
    for (const auto &p : std::as_const(m_attached)) {
        if (p == device) {
            return;
        }
    }
    // Only take over a device KWin connected the way we expect; otherwise leave it alone (stock).
    const bool was = QObject::disconnect(device, &KWin::InputDevice::keyChanged, KWin::input()->keyboard(), &KWin::KeyboardInputRedirection::processKey);
    if (!was) {
        qCWarning(KRISTALL_KEYBOARD) << "device" << device->name() << "is not connected to KWin's keyboard as expected; left as stock";
        return;
    }
    connect(device, &KWin::InputDevice::keyChanged, this, &Remapper::onKey);
    m_attached << device;
    qCDebug(KRISTALL_KEYBOARD) << "attached" << device->name();
    if (m_running) {
        updateStatus();
    }
}

bool Remapper::detach(KWin::InputDevice *device)
{
    bool found = false;
    for (int i = m_attached.size() - 1; i >= 0; --i) {
        if (!m_attached[i] || m_attached[i] == device) {
            m_attached.removeAt(i);
            found = true;
        }
    }
    if (!found || !device) {
        return false;
    }
    disconnect(device, &KWin::InputDevice::keyChanged, this, &Remapper::onKey);
    if (KWin::input() && KWin::input()->keyboard()) {
        connect(device, &KWin::InputDevice::keyChanged, KWin::input()->keyboard(), &KWin::KeyboardInputRedirection::processKey);
    }
    return true;
}

bool Remapper::enabled() const
{
    return m_settings->macShortcuts() && !m_guardTripped;
}

void Remapper::updateStatus()
{
    if (!m_running && !m_guardTripped) {
        return;
    }
    const QString reason = m_guardTripped ? QStringLiteral("crash-guard") : (m_settings->macShortcuts() ? QStringLiteral("on") : QStringLiteral("off"));
    writeStatus(m_running, enabled() && !m_attached.isEmpty(), reason, m_attached.size());
}

// ------------------------------------------------------------------------------------ downstream

void Remapper::forward(quint32 key, bool pressed)
{
    if (KWin::input() && KWin::input()->keyboard()) {
        KWin::input()->keyboard()->processKey(key, pressed ? KeyboardKeyState::Pressed : KeyboardKeyState::Released, m_time, m_device);
    }
}

void Remapper::down(quint32 key)
{
    if (m_down[key]++ == 0) {
        forward(key, true);
    }
}

void Remapper::up(quint32 key)
{
    auto it = m_down.find(key);
    if (it == m_down.end()) {
        return;
    }
    if (--it.value() <= 0) {
        m_down.erase(it);
        forward(key, false);
    }
}

void Remapper::tap(quint32 key)
{
    down(key);
    up(key);
}

void Remapper::releaseAll()
{
    const auto keys = m_down.keys();
    for (quint32 k : keys) {
        forward(k, false);
    }
    m_down.clear();
    m_held.clear();
    m_physical.clear();
    m_cmd = m_opt = m_cmdModDown = m_optModDown = m_cmdSticky = m_cmdPass = false;
    m_cmdSuppress = m_optSuppress = 0;
    m_cmdMod = m_optMod = Mod::None;
}

quint32 Remapper::modKey(Mod mod)
{
    switch (mod) {
    case Mod::Ctrl:
        return KEY_LEFTCTRL;
    case Mod::Meta:
        return KEY_LEFTMETA;
    case Mod::Alt:
        return KEY_LEFTALT;
    case Mod::None:
        break;
    }
    return 0;
}

void Remapper::syncCommand()
{
    const bool want = m_cmd && m_cmdSuppress == 0 && m_cmdMod != Mod::None;
    if (want && !m_cmdModDown) {
        down(modKey(m_cmdMod));
        m_cmdModDown = true;
    } else if (!want && m_cmdModDown) {
        up(modKey(m_cmdMod));
        m_cmdModDown = false;
    }
}

void Remapper::syncOption()
{
    const bool want = m_opt && m_optSuppress == 0 && m_optMod != Mod::None;
    if (want && !m_optModDown) {
        down(modKey(m_optMod));
        m_optModDown = true;
    } else if (!want && m_optModDown) {
        up(modKey(m_optMod));
        m_optModDown = false;
    }
}

void Remapper::setCommandMod(Mod mod)
{
    if (mod == m_cmdMod) {
        return;
    }
    if (m_cmdModDown) {
        up(modKey(m_cmdMod));
        m_cmdModDown = false;
    }
    m_cmdMod = mod;
    syncCommand();
}

// ------------------------------------------------------------------------------------ classification

AppClass Remapper::classify(QString *idOut) const
{
    auto *server = KWin::waylandServer();
    if (!server) {
        return AppClass::Normal;
    }
    if (server->isScreenLocked() || server->isKeyboardShortcutsInhibited()) {
        return AppClass::Passthrough;
    }
    KWin::Window *w = nullptr;
    if (auto *seat = server->seat()) {
        if (auto *surface = seat->focusedKeyboardSurface()) {
            w = server->findWindow(surface);
        }
    }
    if (!w && KWin::workspace()) {
        w = KWin::workspace()->activeWindow();
    }
    if (!w) {
        return AppClass::Normal;
    }
    if (w->isLockScreen()) {
        return AppClass::Passthrough;
    }
    QString dfn = w->desktopFileName();
    if (dfn.endsWith(QLatin1String(".desktop"))) {
        dfn.chop(8);
    }
    QStringList ids;
    for (const QString &s : {dfn, w->resourceClass(), w->resourceName()}) {
        if (!s.isEmpty()) {
            ids << s.toLower();
        }
    }
    if (idOut) {
        *idOut = ids.value(0);
    }
    if (matches(s_passthrough, ids) || matches(m_settings->passthroughApps(), ids)) {
        return AppClass::Passthrough;
    }
    if (matches(s_terminals, ids) || matches(m_settings->terminalApps(), ids)) {
        return AppClass::Terminal;
    }
    return AppClass::Normal;
}

// ------------------------------------------------------------------------------------ translation

void Remapper::onKey(quint32 key, KeyboardKeyState state, std::chrono::microseconds time, KWin::InputDevice *device)
{
    m_device = device;
    m_time = time;
    if (state == KeyboardKeyState::Repeated) {
        const auto it = m_held.constFind(key);
        const quint32 k = (it != m_held.constEnd() && !it->keys.isEmpty()) ? it->keys.last() : key;
        if (KWin::input() && KWin::input()->keyboard()) {
            KWin::input()->keyboard()->processKey(k, KeyboardKeyState::Repeated, time, device);
        }
        return;
    }
    if (state == KeyboardKeyState::Pressed) {
        if (m_physical.contains(key)) {
            onRelease(key); // a press without a release: balance it first
        }
        m_physical.insert(key);
        onPress(key);
    } else {
        onRelease(key);
        m_physical.remove(key);
    }
}

void Remapper::onPress(quint32 key)
{
    const bool on = enabled();
    if (key == KEY_F23 && (physical(KEY_LEFTMETA) || physical(KEY_RIGHTMETA)) && (physical(KEY_LEFTSHIFT) || physical(KEY_RIGHTSHIFT))) {
        copilotKey(key);
        return;
    }
    if (on && key == KEY_LEFTALT) {
        QString id;
        const AppClass cls = classify(&id);
        const bool controlFirst = physical(KEY_LEFTCTRL) || physical(KEY_RIGHTCTRL);
        m_cmd = true;
        m_cmdSticky = false;
        m_cmdSuppress = 0;
        // Control held first (Ctrl+Alt+Del, Ctrl+Alt+F2 …) or an app with PC keys: plain Alt
        m_cmdPass = cls == AppClass::Passthrough || controlFirst;
        m_cmdMod = m_cmdPass ? Mod::Alt : Mod::Ctrl;
        Held h;
        h.kind = Kind::Command;
        m_held.insert(key, h);
        syncCommand();
        qCDebug(KRISTALL_KEYBOARD) << "command down; focus" << id << className(cls) << (m_cmdPass ? "-> alt" : "-> ctrl");
        return;
    }
    if (on && key == KEY_LEFTMETA) {
        const AppClass cls = classify();
        m_opt = true;
        m_optSuppress = 0;
        m_optMod = cls == AppClass::Passthrough ? Mod::Meta : Mod::Alt;
        Held h;
        h.kind = Kind::Option;
        m_held.insert(key, h);
        syncOption();
        return;
    }
    if (on && m_cmd && !isModifierKey(key)) {
        QString id;
        const AppClass cls = classify(&id);
        commandChord(key, cls, id);
        return;
    }
    if (on && m_opt && m_optMod == Mod::Alt && !m_cmd && !isModifierKey(key)) {
        optionChord(key);
        return;
    }
    Held h;
    h.kind = Kind::Identity;
    h.keys = {key};
    m_held.insert(key, h);
    down(key);
}

void Remapper::onRelease(quint32 key)
{
    const auto it = m_held.find(key);
    if (it == m_held.end()) {
        // pressed before we were attached (or released twice): let KWin balance it
        if (!isDown(key)) {
            forward(key, false);
        }
        return;
    }
    const Held h = it.value();
    m_held.erase(it);
    switch (h.kind) {
    case Kind::Command:
        m_cmd = false;
        syncCommand();
        m_cmdMod = Mod::None;
        m_cmdSticky = m_cmdPass = false;
        m_cmdSuppress = 0;
        return;
    case Kind::Option:
        m_opt = false;
        syncOption();
        m_optMod = Mod::None;
        m_optSuppress = 0;
        return;
    case Kind::Identity:
    case Kind::Mapped:
        break;
    }
    for (auto k = h.keys.crbegin(); k != h.keys.crend(); ++k) {
        up(*k);
    }
    if (h.suppressCmd && m_cmdSuppress > 0) {
        --m_cmdSuppress;
        syncCommand();
    }
    if (h.suppressOpt && m_optSuppress > 0) {
        --m_optSuppress;
        syncOption();
    }
}

void Remapper::commandChord(quint32 key, AppClass cls, const QString &id)
{
    const bool shift = physical(KEY_LEFTSHIFT) || physical(KEY_RIGHTSHIFT);
    const bool control = physical(KEY_LEFTCTRL) || physical(KEY_RIGHTCTRL);
    Held h;
    h.kind = Kind::Mapped;
    auto consumed = [&](const char *what) {
        m_held.insert(key, h);
        qCDebug(KRISTALL_KEYBOARD) << "command chord" << key << "in" << id << className(cls) << "->" << what;
    };
    // lift keys downstream for a moment (raw, the reference counts stay as they are)
    auto lift = [this](std::initializer_list<quint32> keys, const std::function<void()> &fn) {
        QList<quint32> lifted;
        for (quint32 k : keys) {
            if (isDown(k)) {
                forward(k, false);
                lifted << k;
            }
        }
        fn();
        for (quint32 k : lifted) {
            forward(k, true);
        }
    };

    if (cls != AppClass::Passthrough && control) {
        // Control-Command chords (whether Command came first or second)
        if (key == KEY_Q) {
            QTimer::singleShot(0, this, &Remapper::lockScreen);
            consumed("lock screen");
            return;
        }
        if (key == KEY_F) {
            QTimer::singleShot(0, this, &Remapper::toggleFullScreen);
            consumed("full screen");
            return;
        }
        if (key == KEY_SPACE) { // character viewer → Plasma's emoji picker (Meta+.)
            ++m_cmdSuppress;
            syncCommand();
            lift({KEY_LEFTCTRL, KEY_RIGHTCTRL}, [this]() {
                down(KEY_LEFTMETA);
                tap(KEY_DOT);
                up(KEY_LEFTMETA);
            });
            --m_cmdSuppress;
            syncCommand();
            consumed("emoji (meta+.)");
            return;
        }
    }
    if (m_cmdPass || m_cmdSticky) {
        // PC keys for this app (or the switcher / Search is held open): keys go as they are
        h.keys = {key};
        m_held.insert(key, h);
        down(key);
        return;
    }

    switch (key) {
    case KEY_SPACE: // Search
    case KEY_TAB: // app switcher (held: KWin's switcher sees Meta held until Command is released)
    case KEY_GRAVE: // windows of the front app (US key position)
    case KEY_102ND: // … German keyboards (the key left of Y), as on a German Mac
        setCommandMod(Mod::Meta);
        m_cmdSticky = true;
        h.keys = {key};
        m_held.insert(key, h);
        down(key);
        qCDebug(KRISTALL_KEYBOARD) << "command chord" << key << "-> meta (system)";
        return;
    case KEY_3:
    case KEY_4:
    case KEY_5:
        if (shift) {
            // Spectacle's own global shortcuts: Shift+Print = whole screen, Meta+Shift+Print =
            // a region, Print = the screenshot tool
            ++m_cmdSuppress;
            syncCommand();
            if (key == KEY_3) {
                tap(KEY_SYSRQ);
            } else if (key == KEY_4) {
                down(KEY_LEFTMETA);
                tap(KEY_SYSRQ);
                up(KEY_LEFTMETA);
            } else {
                lift({KEY_LEFTSHIFT, KEY_RIGHTSHIFT}, [this]() {
                    tap(KEY_SYSRQ);
                });
            }
            --m_cmdSuppress;
            syncCommand();
            consumed(key == KEY_3 ? "screenshot: screen" : key == KEY_4 ? "screenshot: region" : "screenshot: tool");
            return;
        }
        break;
    case KEY_H:
        if (!shift) {
            QTimer::singleShot(0, this, &Remapper::hideActiveApp);
            consumed("hide app");
            return;
        }
        break;
    case KEY_M:
        if (!shift) {
            QTimer::singleShot(0, this, &Remapper::minimizeActiveWindow);
            consumed("minimise window");
            return;
        }
        break;
    case KEY_LEFT:
    case KEY_RIGHT: // beginning / end of the line (Shift selects)
        h.suppressCmd = true;
        ++m_cmdSuppress;
        syncCommand();
        h.keys = {key == KEY_LEFT ? quint32(KEY_HOME) : quint32(KEY_END)};
        m_held.insert(key, h);
        down(h.keys.first());
        return;
    case KEY_UP:
    case KEY_DOWN: // beginning / end of the document: Control (held) + Home/End
        h.keys = {key == KEY_UP ? quint32(KEY_HOME) : quint32(KEY_END)};
        m_held.insert(key, h);
        down(h.keys.first());
        return;
    case KEY_BACKSPACE: // delete to the beginning of the line
        if (cls == AppClass::Terminal) {
            h.keys = {KEY_U}; // Control (held) + U: the shell's "kill line"
        } else {
            h.suppressCmd = true;
            ++m_cmdSuppress;
            syncCommand();
            if (!shift) {
                down(KEY_LEFTSHIFT);
                tap(KEY_HOME);
                up(KEY_LEFTSHIFT);
            } else {
                tap(KEY_HOME);
            }
            h.keys = {KEY_BACKSPACE};
        }
        m_held.insert(key, h);
        down(h.keys.first());
        return;
    case KEY_COMMA: // Settings: KDE apps use Control+Shift+Comma, the others Control+Comma
        if (!shift && id.startsWith(QLatin1String("org.kde."))) {
            h.keys = {KEY_LEFTSHIFT, KEY_COMMA};
            m_held.insert(key, h);
            down(KEY_LEFTSHIFT);
            down(KEY_COMMA);
            return;
        }
        break;
    default:
        break;
    }
    if (cls == AppClass::Terminal && isLetterKey(key) && !shift) {
        h.keys = {KEY_LEFTSHIFT, key};
        m_held.insert(key, h);
        down(KEY_LEFTSHIFT);
        down(key);
        qCDebug(KRISTALL_KEYBOARD) << "command chord" << key << "in terminal" << id << "-> ctrl+shift";
        return;
    }
    // everything else: Control (already held) + the key — copy, paste, cut, undo, redo, select
    // all, save, quit, close, new tab, find, reload, zoom, print …
    h.keys = {key};
    m_held.insert(key, h);
    down(key);
}

void Remapper::optionChord(quint32 key)
{
    Held h;
    h.kind = Kind::Mapped;
    switch (key) {
    case KEY_LEFT:
    case KEY_RIGHT:
    case KEY_BACKSPACE:
    case KEY_DELETE: // by word: Control instead of Alt
        h.suppressOpt = true;
        ++m_optSuppress;
        syncOption();
        h.keys = {KEY_LEFTCTRL, key};
        m_held.insert(key, h);
        down(KEY_LEFTCTRL);
        down(key);
        return;
    case KEY_F23: // the Copilot key sends Meta+Shift+F23: keep it Meta (the assistant's shortcut)
        if (m_optModDown) {
            up(modKey(m_optMod));
            m_optModDown = false;
        }
        m_optMod = Mod::Meta;
        syncOption();
        break;
    default:
        break;
    }
    h.keys = {key};
    m_held.insert(key, h);
    down(key);
}

// The Copilot key: the keyboard sends Meta+Shift+F23. xkeyboard-config (2.44 and later, Fedora
// 45) gives F23 with Shift+Super the keysym XF86Assistant (type PC_SHIFT_SUPER_LEVEL2), and Qt
// has no key for that keysym, so KWin hands its global shortcuts key 0 and no binding can match:
// measured in the integrated session, Meta+Shift+F23, Meta+Shift+TouchpadOff and …TouchpadOn
// never fire, Meta+F23 does. So KWin is shown Meta+F23: Shift is let go downstream while F23 is
// down, and the Meta key stands for Meta (with Mac shortcuts on it is Option = Alt otherwise).
// Independent of the Mac-shortcuts setting: a fix for a key, not a preference. The shell helper
// binds Meta+F23 to the assistant's hold-to-talk (docs/contracts/shell.md §6).
void Remapper::copilotKey(quint32 key)
{
    qCInfo(KRISTALL_KEYBOARD) << "Copilot key (Meta+Shift+F23) -> Meta+F23 for the assistant; option" << m_opt
                              << "optionMod" << int(m_optMod) << "shift down" << isDown(KEY_LEFTSHIFT) << isDown(KEY_RIGHTSHIFT);
    if (m_opt && m_optMod != Mod::Meta) {
        if (m_optModDown) {
            up(modKey(m_optMod));
            m_optModDown = false;
        }
        m_optMod = Mod::Meta;
        syncOption();
    }
    for (quint32 shift : {KEY_LEFTSHIFT, KEY_RIGHTSHIFT}) {
        while (isDown(shift)) {
            up(shift);
        }
    }
    if (!isDown(KEY_LEFTMETA) && !isDown(KEY_RIGHTMETA)) {
        qCWarning(KRISTALL_KEYBOARD) << "Copilot key: no Meta downstream; the assistant's shortcut will not match";
    }
    Held h;
    h.kind = Kind::Mapped;
    h.keys = {key};
    m_held.insert(key, h);
    down(key);
}

// ------------------------------------------------------------------------------------ window actions

static QString appKey(const KWin::Window *w)
{
    const QString d = w->desktopFileName();
    return d.isEmpty() ? w->resourceClass() : d;
}

void Remapper::hideActiveApp()
{
    auto *ws = KWin::workspace();
    KWin::Window *a = ws ? ws->activeWindow() : nullptr;
    if (!a) {
        return;
    }
    const QString key = appKey(a);
    const auto windows = ws->windows();
    for (KWin::Window *w : windows) {
        if (w->isClient() && appKey(w) == key && w->isMinimizable()) {
            w->setMinimized(true);
        }
    }
}

void Remapper::minimizeActiveWindow()
{
    auto *ws = KWin::workspace();
    KWin::Window *a = ws ? ws->activeWindow() : nullptr;
    if (a && a->isMinimizable()) {
        a->setMinimized(true);
    }
}

void Remapper::toggleFullScreen()
{
    auto *ws = KWin::workspace();
    KWin::Window *a = ws ? ws->activeWindow() : nullptr;
    if (a && a->isFullScreenable()) {
        a->setFullScreen(!a->isFullScreen());
    }
}

void Remapper::lockScreen()
{
    QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.ScreenSaver"), QStringLiteral("/ScreenSaver"),
                                                      QStringLiteral("org.freedesktop.ScreenSaver"), QStringLiteral("Lock"));
    QDBusConnection::sessionBus().asyncCall(msg);
}

} // namespace Kristall
