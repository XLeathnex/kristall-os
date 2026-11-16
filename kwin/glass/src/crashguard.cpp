/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "crashguard.h"
#include "glasslog.h"

#include <QDir>
#include <QFile>
#include <QSaveFile>

namespace Kristall
{

CrashGuard::CrashGuard(QObject *parent)
    : QObject(parent)
{
    const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
    if (runtime.isEmpty()) {
        return;
    }
    QDir().mkpath(runtime + QStringLiteral("/kristall"));
    m_path = runtime + QStringLiteral("/kristall/glass.guard");

    QFile in(m_path);
    if (in.open(QIODevice::ReadOnly)) {
        m_previous = QString::fromLatin1(in.readAll()).trimmed().toInt();
    }
    if (m_previous >= kMaxArmedStarts) {
        m_tripped = true;
        qCCritical(KRISTALL_GLASS) << "KWin stopped" << m_previous
                                   << "times while the glass effect was starting; glass stays disabled for this session."
                                   << "Delete" << m_path << "to retry.";
        return; // keep the file so the decision is stable across further restarts
    }
    QSaveFile out(m_path);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QByteArray::number(m_previous + 1));
        out.commit();
    }
    m_timer.setSingleShot(true);
    m_timer.setInterval(kArmedSeconds * 1000);
    connect(&m_timer, &QTimer::timeout, this, &CrashGuard::disarm);
    m_timer.start();
}

CrashGuard::~CrashGuard()
{
    // a clean unload (effect disabled, KWin quitting normally) is not a crash
    if (!m_tripped) {
        disarm();
    }
}

void CrashGuard::disarm()
{
    if (!m_path.isEmpty()) {
        QFile::remove(m_path);
    }
}

} // namespace Kristall
