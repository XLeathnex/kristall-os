/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "busname.h"
#include "util.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QFutureWatcher>
#include <QTimer>
#include <QtConcurrentRun>

namespace Kristall
{

static const QString s_connectionName = QStringLiteral("kristall-bridge-names");

BusNameClaim::BusNameClaim(const QString &name, QObject *parent)
    : QObject(parent)
    , m_name(name)
{
}

void BusNameClaim::setWanted(bool wanted)
{
    m_wanted = wanted;
    sync();
}

void BusNameClaim::sync()
{
    if (m_inFlight || m_connecting || m_wanted == m_held) {
        return; // a finished request calls sync() again
    }
    QDBusConnection bus(s_connectionName);
    if (m_wanted) {
        if (!bus.isConnected()) {
            connectBus();
            return;
        }
        m_inFlight = true;
        QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.DBus"), QStringLiteral("/org/freedesktop/DBus"),
                                                          QStringLiteral("org.freedesktop.DBus"), QStringLiteral("RequestName"));
        msg << m_name << uint(0); // no flags: queue behind another owner, nobody can take it from us
        auto *watcher = new QDBusPendingCallWatcher(bus.asyncCall(msg), this);
        connect(watcher, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *w) {
            const QDBusPendingReply<uint> reply = *w;
            w->deleteLater();
            m_inFlight = false;
            if (!reply.isValid()) {
                logWarning(QStringLiteral("could not request %1: %2").arg(m_name, reply.error().message()));
                retry();
                return;
            }
            m_held = true;
            m_releasable = reply.value() != 4; // 4 = already owned by this connection: never release that
            m_retries = 0;
            sync(); // wanted may have changed meanwhile
        });
    } else {
        m_held = false;
        if (m_releasable && bus.isConnected()) {
            QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.DBus"), QStringLiteral("/org/freedesktop/DBus"),
                                                              QStringLiteral("org.freedesktop.DBus"), QStringLiteral("ReleaseName"));
            msg << m_name;
            bus.asyncCall(msg);
        }
        m_releasable = false;
    }
}

void BusNameClaim::connectBus()
{
    m_connecting = true;
    auto *watcher = new QFutureWatcher<bool>(this);
    connect(watcher, &QFutureWatcher<bool>::finished, this, [this, watcher]() {
        watcher->deleteLater();
        m_connecting = false;
        if (!watcher->result()) {
            retry();
            return;
        }
        sync();
    });
    watcher->setFuture(QtConcurrent::run([]() {
        // shared by every claim; a failed attempt leaves a dead connection under the name: drop it
        if (QDBusConnection(s_connectionName).isConnected()) {
            return true;
        }
        QDBusConnection::disconnectFromBus(s_connectionName);
        return QDBusConnection::connectToBus(QDBusConnection::SessionBus, s_connectionName).isConnected();
    }));
}

void BusNameClaim::retry()
{
    if (m_retryPending) {
        return;
    }
    m_retryPending = true;
    const int delay = m_retries < 30 ? 1000 : 30000;
    ++m_retries;
    QTimer::singleShot(delay, this, [this]() {
        m_retryPending = false;
        sync();
    });
}

} // namespace Kristall
