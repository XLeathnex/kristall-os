/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "crashguard.h"
#include "glasslog.h"

#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
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

    const qint64 now = QDateTime::currentSecsSinceEpoch();
    bool wasArmed = false;
    bool wasDisabled = false;
    QFile in(m_path);
    if (in.open(QIODevice::ReadOnly)) {
        const QByteArray data = in.readAll().trimmed();
        const QJsonDocument doc = QJsonDocument::fromJson(data);
        if (doc.isObject()) {
            const QJsonObject o = doc.object();
            wasArmed = o.value(QStringLiteral("armed")).toBool();
            wasDisabled = o.value(QStringLiteral("disabled")).toBool();
            for (const QJsonValue &v : o.value(QStringLiteral("crashes")).toArray()) {
                m_crashes.append(qint64(v.toDouble()));
            }
        } else if (!data.isEmpty()) {
            // the earlier format: a bare count of armed start-ups
            const int n = QString::fromLatin1(data).toInt();
            wasArmed = n > 0;
            for (int i = 1; i < n; ++i) {
                m_crashes.append(now);
            }
        }
    }
    if (wasArmed) {
        m_crashes.append(now); // the previous KWin went away while the effect was active
    }
    // only crashes within the window count
    QList<qint64> recent;
    for (qint64 t : std::as_const(m_crashes)) {
        if (now - t <= kWindowSeconds) {
            recent.append(t);
        }
    }
    m_crashes = recent;
    m_tripped = wasDisabled || m_crashes.size() >= kMaxCrashes;
    if (m_tripped) {
        qCCritical(KRISTALL_GLASS) << "KWin stopped" << m_crashes.size() << "times within" << kWindowSeconds / 60
                                   << "minutes while the glass effect was active; glass stays off for this session."
                                   << "Delete" << m_path << "to retry.";
        write(false);
        return;
    }
    if (wasArmed) {
        qCWarning(KRISTALL_GLASS) << "KWin stopped while the glass effect was active (" << m_crashes.size()
                                  << "time(s) in the last" << kWindowSeconds / 60 << "minutes)";
    }
    write(true);
}

CrashGuard::~CrashGuard()
{
    // a clean unload (effect disabled, KWin quitting normally) is not a crash
    if (!m_path.isEmpty()) {
        write(false);
    }
}

void CrashGuard::write(bool armed) const
{
    if (m_path.isEmpty()) {
        return;
    }
    QJsonArray crashes;
    for (qint64 t : m_crashes) {
        crashes.append(double(t));
    }
    QJsonObject o;
    o[QStringLiteral("schema")] = 2;
    o[QStringLiteral("armed")] = armed && !m_tripped;
    o[QStringLiteral("disabled")] = m_tripped;
    o[QStringLiteral("crashes")] = crashes;
    QSaveFile out(m_path);
    if (out.open(QIODevice::WriteOnly)) {
        out.write(QJsonDocument(o).toJson(QJsonDocument::Compact));
        out.commit();
    }
}

QJsonObject CrashGuard::status() const
{
    QJsonArray crashes;
    for (qint64 t : m_crashes) {
        crashes.append(double(t));
    }
    QJsonObject o;
    o[QStringLiteral("disabled")] = m_tripped;
    o[QStringLiteral("crashes")] = crashes;
    o[QStringLiteral("windowSeconds")] = kWindowSeconds;
    o[QStringLiteral("path")] = m_path;
    return o;
}

} // namespace Kristall
