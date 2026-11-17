/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "onscreenkeyboard.h"
#include "keysettings.h"

#include "core/inputdevice.h"
#include "input.h"
#include "inputmethod.h"
#include "main.h"

#include <KConfig>
#include <KConfigGroup>
#include <KDesktopFile>
#include <KSharedConfig>

#include <QFileInfo>
#include <QStandardPaths>

namespace Kristall
{

OnScreenKeyboard::OnScreenKeyboard(QObject *parent)
    : QObject(parent)
{
}

OnScreenKeyboard::~OnScreenKeyboard()
{
    stop();
}

void OnScreenKeyboard::start()
{
    if (m_running || !KWin::input() || !KWin::kwinApp() || !KWin::kwinApp()->inputMethod()) {
        return;
    }
    m_running = true;
    connect(KWin::input(), &KWin::InputRedirection::deviceAdded, this, &OnScreenKeyboard::update);
    connect(KWin::input(), &KWin::InputRedirection::deviceRemoved, this, &OnScreenKeyboard::update);
    // KWin sets the command again whenever kwinrc's InputMethod changes (System Settings)
    connect(KWin::kwinApp()->inputMethod(), &KWin::InputMethod::availableChanged, this, &OnScreenKeyboard::update);
    update();
}

void OnScreenKeyboard::stop()
{
    if (!m_running) {
        return;
    }
    m_running = false;
    disconnect(KWin::input(), nullptr, this, nullptr);
    if (KWin::kwinApp() && KWin::kwinApp()->inputMethod()) {
        disconnect(KWin::kwinApp()->inputMethod(), nullptr, this, nullptr);
        if (m_applied) {
            // back to what the configuration says (nothing): as if we had never been loaded
            KWin::kwinApp()->inputMethod()->setInputMethodCommand(QString());
        }
    }
    m_applied = false;
}

bool OnScreenKeyboard::realTouchscreen()
{
    // tests only: the headless KWin has no libinput, so let fake input stand in for a touchscreen
    const bool fakeCounts = qEnvironmentVariableIntValue("KRISTALL_KEYBOARD_TEST_TOUCH") == 1;
    const auto devices = KWin::input()->devices();
    for (KWin::InputDevice *d : devices) {
        if (d->isTouch() && (fakeCounts || !d->sysPath().isEmpty())) {
            return true;
        }
    }
    return false;
}

bool OnScreenKeyboard::ownerChose() const
{
    const QString user = QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + QStringLiteral("/kwinrc");
    KConfig cfg(user, KConfig::SimpleConfig);
    return cfg.group(QStringLiteral("Wayland")).hasKey("InputMethod");
}

QString OnScreenKeyboard::touchCommand() const
{
    const QString file = KWin::kwinApp()->config()->group(QStringLiteral("Wayland")).readPathEntry("KristallTouchInputMethod", QString());
    if (file.isEmpty() || !KDesktopFile::isDesktopFile(file) || !QFileInfo::exists(file)) {
        return QString();
    }
    return KDesktopFile(file).desktopGroup().readEntry("Exec", QString());
}

void OnScreenKeyboard::update()
{
    if (!m_running) {
        return;
    }
    KWin::InputMethod *im = KWin::kwinApp()->inputMethod();
    const QString configured = KWin::kwinApp()->config()->group(QStringLiteral("Wayland")).readPathEntry("InputMethod", QString());
    if (ownerChose() || !configured.isEmpty()) {
        // the owner (or the machine's administrator) configured an input method: KWin's own
        // handling applies
        m_applied = false;
        return;
    }
    const QString command = touchCommand();
    const bool touch = realTouchscreen();
    const bool want = touch && !command.isEmpty();
    if (want && !im->isAvailable()) {
        qCInfo(KRISTALL_KEYBOARD) << "touchscreen present: on-screen keyboard available" << command;
        m_applied = true;
        im->setInputMethodCommand(command);
    } else if (!want && im->isAvailable()) {
        qCInfo(KRISTALL_KEYBOARD) << "no touchscreen: on-screen keyboard off";
        m_applied = false;
        im->setInputMethodCommand(QString());
    }
}

} // namespace Kristall
