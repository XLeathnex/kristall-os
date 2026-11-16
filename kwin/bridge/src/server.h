/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include "util.h"

#include <QHash>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QSet>
#include <QTimer>

#include <functional>
#include <map>
#include <memory>

class QLocalServer;
class QLocalSocket;

namespace Kristall
{

class Server;

// Hard limits (see docs/contracts/bridge.md "Transport")
constexpr qsizetype kMaxLine = 1 << 20; // 1 MiB per line, excluding the newline
constexpr qsizetype kMaxWriteBacklog = 8 << 20; // unread bytes we hold for one client before dropping it
constexpr int kMaxInflight = 32; // requests of one connection awaiting a reply
constexpr int kMaxConnections = 32;
constexpr int kLinesPerTurn = 64; // lines handled per event-loop turn per connection...
constexpr qint64 kTurnBudgetNs = 1000000; // ...or 1 ms of work, whichever comes first

class Connection : public QObject
{
    Q_OBJECT
public:
    Connection(Server *server, QLocalSocket *socket, const PeerInfo &peer, bool privileged);
    ~Connection() override;

    quint64 serial() const
    {
        return m_serial;
    }
    const PeerInfo &peer() const
    {
        return m_peer;
    }
    bool privileged() const
    {
        return m_privileged;
    }
    QString clientName() const
    {
        return m_clientName;
    }
    void setClientName(const QString &name)
    {
        m_clientName = name;
    }
    bool subscribed(const QString &topic) const
    {
        return m_topics.contains(topic);
    }
    void subscribe(const QStringList &topics)
    {
        for (const QString &t : topics) {
            m_topics.insert(t);
        }
    }

    // writes one JSON object as a line (events; replies go through the ordered queue)
    void sendObject(const QJsonObject &obj);
    void sendLine(const QByteArray &line);
    void close(const QString &why);
    bool isClosing() const
    {
        return m_closing;
    }

    // ordered replies
    quint64 allocateSlot();
    // `after` runs right after the reply line was written and may write more lines (used by
    // subscribe: the snapshot is taken and the topics activated exactly when the reply goes out)
    void completeSlot(quint64 seq, QByteArray line, std::function<void(Connection *)> after);

Q_SIGNALS:
    void closed(Kristall::Connection *conn);

private:
    void onReadyRead();
    void processLines();
    void scheduleProcessing();
    void flushReplies();

    Server *m_server;
    QLocalSocket *m_socket;
    PeerInfo m_peer;
    bool m_privileged;
    quint64 m_serial;
    QString m_clientName;
    QSet<QString> m_topics;
    QByteArray m_in;
    qsizetype m_pos = 0;
    bool m_closing = false;
    bool m_processScheduled = false;
    QTimer m_processTimer;
    quint64 m_nextSlot = 0;
    quint64 m_nextToSend = 0;
    std::map<quint64, std::pair<QByteArray, std::function<void(Connection *)>>> m_ready;
    int m_inflight = 0;
};

// Completes one request. Exactly one of ok()/fail() takes effect; if the handle is destroyed
// without either (an async operation was dropped), an "internal" error is sent so that the
// connection's reply order can progress.
class Reply
{
public:
    Reply(Connection *conn, quint64 slot, const QJsonValue &id);
    ~Reply();
    Reply(const Reply &) = delete;
    Reply &operator=(const Reply &) = delete;

    void ok(const QJsonObject &result = {}, std::function<void(Connection *)> after = {});
    void fail(const QString &code, const QString &message);
    void fail(const BridgeError &e)
    {
        fail(e.code, e.message);
    }
    bool done() const
    {
        return m_done;
    }
    Connection *connection() const
    {
        return m_conn.data();
    }
    bool alive() const
    {
        return !m_conn.isNull() && !m_conn->isClosing();
    }

private:
    QPointer<Connection> m_conn;
    quint64 m_slot;
    QJsonValue m_id;
    bool m_done = false;
};
using ReplyPtr = std::shared_ptr<Reply>;

using Handler = std::function<void(Params &params, const ReplyPtr &reply)>;

struct MethodSpec
{
    bool privileged = false;
    QString capability; // empty: always available
    Handler handler;
};

class Server : public QObject
{
    Q_OBJECT
public:
    explicit Server(QObject *parent = nullptr);
    ~Server() override;

    // Creates the socket. Returns false (and logs why) if the path is unusable.
    bool listen(const QString &runtimeDir);
    QString socketPath() const
    {
        return m_path;
    }

    void registerMethod(const QString &name, MethodSpec spec);
    void setCapabilityAvailable(const QString &cap, bool available);
    QStringList capabilities() const;

    // Locked screen: all privileged methods are denied.
    std::function<bool()> isLocked;
    bool devMode() const
    {
        return m_devMode;
    }

    void broadcast(const QString &topic, const QString &event, const QJsonObject &data);
    bool hasSubscribers(const QString &topic) const;
    QList<Connection *> connections() const
    {
        return m_connections;
    }

    // Snapshot producers, called when a client subscribes to a topic.
    void setSnapshotProvider(const QString &topic, std::function<QList<QJsonObject>()> provider);
    QList<QJsonObject> snapshot(const QString &topic) const;
    static const QStringList &topics();

    void dispatch(Connection *conn, const QByteArray &line);

    struct Stats
    {
        quint64 requests = 0;
        quint64 invalid = 0;
        quint64 denied = 0;
        quint64 dropped = 0; // connections closed for misbehaviour
    } stats;

Q_SIGNALS:
    void connectionClosed(Kristall::Connection *conn);
    void subscribersChanged();

private:
    void onNewConnection();

    QLocalServer *m_server = nullptr;
    QString m_path;
    QList<Connection *> m_connections;
    QHash<QString, MethodSpec> m_methods;
    QSet<QString> m_caps;
    QStringList m_capOrder;
    QHash<QString, std::function<QList<QJsonObject>()>> m_snapshots;
    bool m_devMode = false;
    quint64 m_nextSerial = 1;
};

QJsonObject makeEvent(const QString &name, const QJsonObject &data);

} // namespace Kristall
