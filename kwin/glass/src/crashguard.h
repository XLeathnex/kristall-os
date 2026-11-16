/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    Crash-loop breaker for the whole login session. KWin itself never disables an effect that
    crashed it; kwin_wayland_wrapper restarts KWin after each crash (up to 10 times), which with a
    faulty effect would mean a crash loop with black screens in between.

    The guard keeps a small record in $XDG_RUNTIME_DIR/kristall/glass.guard (JSON, written
    atomically): `armed` while the effect is loaded and drawing, and the times KWin went away
    while it was armed (`crashes`). A clean unload (effect switched off, KWin quitting normally)
    clears `armed`. When KWin starts and finds the record still armed, the previous KWin died with
    the effect active: that is a crash. Two such crashes within kWindowSeconds (10 minutes) — at
    start-up or at any later time — and the effect starts disabled (`disabled: true`) for the
    rest of the login session; `kristall-glass-ctl status` and the clients' `state` event report
    it (reason `crash-guard`). The file lives on the runtime tmpfs: the next boot (or log-in) starts
    with glass on again.
*/
#pragma once

#include <QJsonObject>
#include <QList>
#include <QObject>
#include <QString>

namespace Kristall
{

class CrashGuard : public QObject
{
    Q_OBJECT

public:
    static constexpr int kWindowSeconds = 600;
    static constexpr int kMaxCrashes = 2;

    explicit CrashGuard(QObject *parent = nullptr);
    ~CrashGuard() override;

    /// true if KWin crashed often enough while the effect was active that glass must stay off
    bool tripped() const { return m_tripped; }
    int previousArmedStarts() const { return int(m_crashes.size()); }
    /// the record for status output: {disabled, crashes (epoch s), windowSeconds, path}
    QJsonObject status() const;

private:
    void write(bool armed) const;

    QString m_path;
    QList<qint64> m_crashes;
    bool m_tripped = false;
};

} // namespace Kristall
