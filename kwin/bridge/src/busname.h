/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QObject>
#include <QString>

namespace Kristall
{

// Owns a well-known name on the session bus while it is wanted. Uses a private connection of the
// bridge, not KWin's: KWin releases org.kde.kappmenuview on its own connection whenever its
// decoration settings say no title-bar menu button is configured (ApplicationMenu::setViewEnabled),
// which would drop a name the bridge requested on that same connection. The private connection is
// opened on a worker thread and requests are asynchronous (the compositor never blocks); a request
// queues behind another owner instead of failing. One that could not be made (bus not reachable
// yet, an error reply) is retried every second for 30 s, then every 30 s.
class BusNameClaim : public QObject
{
    Q_OBJECT
public:
    BusNameClaim(const QString &name, QObject *parent);

    void setWanted(bool wanted);
    bool wanted() const
    {
        return m_wanted;
    }

private:
    void sync();
    void connectBus();
    void retry();

    const QString m_name;
    bool m_wanted = false;
    bool m_held = false; // requested successfully (primary owner or in the queue)
    bool m_releasable = false; // false when KWin's connection already owned it (e.g. KWin itself)
    bool m_inFlight = false;
    bool m_retryPending = false;
    bool m_connecting = false;
    int m_retries = 0;
};

} // namespace Kristall
