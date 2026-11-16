/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    Crash-loop breaker. KWin itself never disables an effect that crashed it; kwin_wayland_wrapper
    restarts KWin up to 10 times and then gives up, which would leave the owner with a dead session.
    The guard writes $XDG_RUNTIME_DIR/kristall/glass.guard ("armed" counter) when the effect starts
    and clears it once the effect has run for kArmedSeconds. If KWin dies while the guard is armed,
    the counter survives; at the second consecutive armed start-up the effect stays inert for the
    rest of the login session (the file lives on a tmpfs and is gone after logout/reboot).
*/
#pragma once

#include <QObject>
#include <QString>
#include <QTimer>

namespace Kristall
{

class CrashGuard : public QObject
{
    Q_OBJECT

public:
    static constexpr int kArmedSeconds = 30;
    static constexpr int kMaxArmedStarts = 2;

    explicit CrashGuard(QObject *parent = nullptr);
    ~CrashGuard() override;

    /// true if previous start-ups crashed while armed often enough that glass must stay off
    bool tripped() const { return m_tripped; }
    int previousArmedStarts() const { return m_previous; }

private:
    void disarm();

    QString m_path;
    QTimer m_timer;
    bool m_tripped = false;
    int m_previous = 0;
};

} // namespace Kristall
