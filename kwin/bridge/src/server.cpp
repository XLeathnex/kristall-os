/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "server.h"

#include <QDir>
#include <QJsonDocument>
#include <QJsonParseError>
#include <QLocalServer>
#include <QElapsedTimer>
#include <QLocalSocket>

#include <cerrno>
#include <cmath>
#include <cstring>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace Kristall
{

QJsonObject makeEvent(const QString &name, const QJsonObject &data)
{
    return QJsonObject{{QStringLiteral("event"), name}, {QStringLiteral("data"), data}};
}

static QByteArray toLine(const QJsonObject &obj)
{
    return QJsonDocument(obj).toJson(QJsonDocument::Compact);
}

// ------------------------------------------------------------------------------------ Reply

Reply::Reply(Connection *conn, quint64 slot, const QJsonValue &id)
    : m_conn(conn)
    , m_slot(slot)
    , m_id(id)
{
}

Reply::~Reply()
{
    if (!m_done) {
        fail(Err::Internal, QStringLiteral("request was dropped"));
    }
}

void Reply::ok(const QJsonObject &result, std::function<void(Connection *)> after)
{
    if (m_done) {
        return;
    }
    m_done = true;
    if (!m_conn) {
        return;
    }
    m_conn->completeSlot(m_slot, toLine(QJsonObject{{QStringLiteral("id"), m_id}, {QStringLiteral("result"), result}}), std::move(after));
}

void Reply::fail(const QString &code, const QString &message)
{
    if (m_done) {
        return;
    }
    m_done = true;
    if (!m_conn) {
        return;
    }
    const QJsonObject err{{QStringLiteral("code"), code}, {QStringLiteral("message"), message}};
    m_conn->completeSlot(m_slot, toLine(QJsonObject{{QStringLiteral("id"), m_id}, {QStringLiteral("error"), err}}), {});
}

// ------------------------------------------------------------------------------------ Connection

Connection::Connection(Server *server, QLocalSocket *socket, const PeerInfo &peer, bool privileged)
    : QObject(server)
    , m_server(server)
    , m_socket(socket)
    , m_peer(peer)
    , m_privileged(privileged)
{
    static quint64 s_serial = 0;
    m_serial = ++s_serial;
    m_socket->setParent(this);
    // Qt stops reading from the kernel once this much is buffered; a flooding client then
    // blocks in its own write() instead of growing our memory.
    m_socket->setReadBufferSize(kMaxLine + 65536);
    connect(m_socket, &QLocalSocket::readyRead, this, &Connection::onReadyRead);
    // one reused zero-interval timer: yielding must not create a timer object per turn
    m_processTimer.setSingleShot(true);
    m_processTimer.setInterval(0);
    connect(&m_processTimer, &QTimer::timeout, this, &Connection::processLines);
    connect(m_socket, &QLocalSocket::disconnected, this, [this]() {
        m_closing = true;
        Q_EMIT closed(this);
    });
    connect(m_socket, &QLocalSocket::errorOccurred, this, [this](QLocalSocket::LocalSocketError) {
        if (m_socket->state() != QLocalSocket::ConnectedState && !m_closing) {
            m_closing = true;
            Q_EMIT closed(this);
        }
    });
}

Connection::~Connection() = default;

void Connection::sendLine(const QByteArray &line)
{
    if (m_closing) {
        return;
    }
    m_socket->write(line);
    m_socket->write("\n", 1);
    if (m_socket->bytesToWrite() > kMaxWriteBacklog) {
        m_server->stats.dropped++;
        logWarning(QStringLiteral("dropping client %1 (pid %2): it stopped reading (%3 bytes unread)")
                       .arg(m_clientName, QString::number(m_peer.pid), QString::number(m_socket->bytesToWrite())));
        m_closing = true;
        m_socket->abort();
        Q_EMIT closed(this);
    }
}

void Connection::sendObject(const QJsonObject &obj)
{
    sendLine(toLine(obj));
}

void Connection::close(const QString &why)
{
    if (m_closing) {
        return;
    }
    m_server->stats.dropped++;
    logWarning(QStringLiteral("closing client %1 (pid %2): %3").arg(m_clientName, QString::number(m_peer.pid), why));
    m_closing = true;
    // let the last error line drain, but never wait for a client that does not read
    m_socket->disconnectFromServer();
    QTimer::singleShot(2000, this, [this]() {
        m_socket->abort();
    });
    if (m_socket->state() == QLocalSocket::UnconnectedState) {
        Q_EMIT closed(this);
    }
}

quint64 Connection::allocateSlot()
{
    m_inflight++;
    return m_nextSlot++;
}

void Connection::completeSlot(quint64 seq, QByteArray line, std::function<void(Connection *)> after)
{
    m_ready.emplace(seq, std::make_pair(std::move(line), std::move(after)));
    flushReplies();
}

void Connection::flushReplies()
{
    bool progressed = false;
    while (!m_ready.empty() && m_ready.begin()->first == m_nextToSend) {
        auto node = m_ready.extract(m_ready.begin());
        m_inflight--;
        m_nextToSend++;
        progressed = true;
        sendLine(node.mapped().first);
        if (node.mapped().second && !m_closing) {
            node.mapped().second(this);
        }
    }
    if (progressed && !m_processScheduled && !m_closing && (m_in.indexOf('\n', m_pos) >= 0 || m_socket->bytesAvailable() > 0)) {
        scheduleProcessing();
    }
}

void Connection::scheduleProcessing()
{
    m_processScheduled = true;
    m_processTimer.start();
}

void Connection::onReadyRead()
{
    if (m_processScheduled) {
        return;
    }
    processLines();
}

void Connection::processLines()
{
    m_processScheduled = false;
    int handled = 0;
    QElapsedTimer turn;
    turn.start();
    // m_in[m_pos..] is unconsumed input; consumed bytes are dropped in one go, not per line
    auto compact = [this]() {
        if (m_pos > 0) {
            m_in.remove(0, m_pos);
            m_pos = 0;
        }
    };
    auto tooLong = [this]() {
        m_server->stats.invalid++;
        sendObject(QJsonObject{{QStringLiteral("id"), QJsonValue()},
                               {QStringLiteral("error"), QJsonObject{{QStringLiteral("code"), Err::Invalid}, {QStringLiteral("message"), QStringLiteral("line longer than 1 MiB")}}}});
        close(QStringLiteral("line longer than 1 MiB"));
    };
    while (!m_closing) {
        qsizetype nl = m_in.indexOf('\n', m_pos);
        if (nl < 0) {
            compact();
            const qint64 room = kMaxLine + 65536 - m_in.size();
            const qint64 avail = m_socket->bytesAvailable();
            if (room > 0 && avail > 0) {
                m_in += m_socket->read(std::min(room, avail));
                nl = m_in.indexOf('\n');
            }
            if (nl < 0) {
                if (m_in.size() > kMaxLine) {
                    tooLong();
                }
                return;
            }
        }
        if (nl - m_pos > kMaxLine) {
            tooLong();
            return;
        }
        if (m_inflight >= kMaxInflight) {
            return; // resumed from flushReplies()
        }
        if (handled >= kLinesPerTurn || turn.nsecsElapsed() > kTurnBudgetNs) {
            // yield to the compositor; continue in the next event-loop turn
            scheduleProcessing();
            return;
        }
        QByteArray line = m_in.mid(m_pos, nl - m_pos);
        m_pos = nl + 1;
        if (line.endsWith('\r')) {
            line.chop(1);
        }
        if (line.trimmed().isEmpty()) {
            continue;
        }
        handled++;
        m_server->dispatch(this, line);
    }
}

// ------------------------------------------------------------------------------------ Server

const QStringList &Server::topics()
{
    static const QStringList t = {QStringLiteral("windows"), QStringLiteral("active"), QStringLiteral("stacking"),
                                  QStringLiteral("outputs"), QStringLiteral("desktops"), QStringLiteral("agent"),
                                  QStringLiteral("menus")};
    return t;
}

Server::Server(QObject *parent)
    : QObject(parent)
{
    m_devMode = qEnvironmentVariable("KRISTALL_BRIDGE_DEV") == QLatin1String("1");
}

Server::~Server()
{
    if (m_server) {
        m_server->close();
    }
    if (!m_path.isEmpty()) {
        ::unlink(QFile::encodeName(m_path).constData());
    }
}

static bool ensurePrivateDir(const QString &dir, QString *why)
{
    const QByteArray d = QFile::encodeName(dir);
    if (::mkdir(d.constData(), 0700) != 0 && errno != EEXIST) {
        *why = QStringLiteral("cannot create %1: %2").arg(dir, QString::fromLocal8Bit(strerror(errno)));
        return false;
    }
    struct stat st;
    if (::lstat(d.constData(), &st) != 0 || !S_ISDIR(st.st_mode)) {
        *why = QStringLiteral("%1 is not a directory").arg(dir);
        return false;
    }
    if (st.st_uid != ::getuid()) {
        *why = QStringLiteral("%1 is owned by another user").arg(dir);
        return false;
    }
    if ((st.st_mode & 0077) != 0) {
        ::chmod(d.constData(), 0700);
    }
    return true;
}

bool Server::listen(const QString &runtimeDir)
{
    QString why;
    if (runtimeDir.isEmpty() || !QDir::isAbsolutePath(runtimeDir)) {
        logWarning(QStringLiteral("disabled: XDG_RUNTIME_DIR is not set"));
        return false;
    }
    const QString dir = runtimeDir + QStringLiteral("/kristall");
    if (!ensurePrivateDir(dir, &why)) {
        logWarning(QStringLiteral("disabled: %1").arg(why));
        return false;
    }
    const QString path = dir + QStringLiteral("/bridge.sock");
    const QByteArray p = QFile::encodeName(path);
    if (p.size() >= int(sizeof(sockaddr_un::sun_path))) {
        logWarning(QStringLiteral("disabled: socket path too long: %1").arg(path));
        return false;
    }
    struct stat st;
    if (::lstat(p.constData(), &st) == 0) {
        if (!S_ISSOCK(st.st_mode)) {
            logWarning(QStringLiteral("disabled: %1 exists and is not a socket").arg(path));
            return false;
        }
        // a live bridge (e.g. a nested KWin) keeps its socket; a stale one is replaced
        const int probe = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0);
        sockaddr_un addr{};
        addr.sun_family = AF_UNIX;
        memcpy(addr.sun_path, p.constData(), p.size());
        const bool live = probe >= 0 && ::connect(probe, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0;
        if (probe >= 0) {
            ::close(probe);
        }
        if (live) {
            logWarning(QStringLiteral("disabled: another bridge is already serving %1").arg(path));
            return false;
        }
        ::unlink(p.constData());
    }
    m_server = new QLocalServer(this);
    m_server->setMaxPendingConnections(16);
    if (!m_server->listen(path)) {
        logWarning(QStringLiteral("disabled: cannot listen on %1: %2").arg(path, m_server->errorString()));
        delete m_server;
        m_server = nullptr;
        return false;
    }
    ::chmod(p.constData(), 0600);
    m_path = path;
    connect(m_server, &QLocalServer::newConnection, this, &Server::onNewConnection);
    logInfo(QStringLiteral("listening on %1%2").arg(path, m_devMode ? QStringLiteral(" (development mode: privileged methods open to all same-user peers)") : QString()));
    return true;
}

void Server::onNewConnection()
{
    while (QLocalSocket *sock = m_server->nextPendingConnection()) {
        if (m_connections.size() >= kMaxConnections) {
            logOnce(QStringLiteral("maxconn"), QStringLiteral("refusing connection: %1 clients already connected").arg(kMaxConnections));
            sock->abort();
            sock->deleteLater();
            continue;
        }
        const PeerInfo peer = identifyPeer(int(sock->socketDescriptor()));
        if (peer.uid != ::getuid()) {
            stats.denied++;
            logWarning(QStringLiteral("refusing connection from uid %1 (pid %2)").arg(peer.uid).arg(peer.pid));
            sock->abort();
            sock->deleteLater();
            continue;
        }
        auto conn = new Connection(this, sock, peer, m_devMode || peer.trusted);
        m_connections << conn;
        connect(conn, &Connection::closed, this, [this](Connection *c) {
            if (!m_connections.removeOne(c)) {
                return;
            }
            Q_EMIT connectionClosed(c);
            Q_EMIT subscribersChanged();
            c->deleteLater();
        });
    }
}

void Server::registerMethod(const QString &name, MethodSpec spec)
{
    m_methods.insert(name, std::move(spec));
}

void Server::setCapabilityAvailable(const QString &cap, bool available)
{
    if (!m_capOrder.contains(cap)) {
        m_capOrder << cap;
    }
    if (available) {
        m_caps.insert(cap);
    } else {
        m_caps.remove(cap);
    }
}

QStringList Server::capabilities() const
{
    QStringList out;
    for (const QString &c : m_capOrder) {
        if (m_caps.contains(c)) {
            out << c;
        }
    }
    return out;
}

void Server::setSnapshotProvider(const QString &topic, std::function<QList<QJsonObject>()> provider)
{
    m_snapshots.insert(topic, std::move(provider));
}

QList<QJsonObject> Server::snapshot(const QString &topic) const
{
    const auto it = m_snapshots.find(topic);
    return it == m_snapshots.end() ? QList<QJsonObject>() : it.value()();
}

bool Server::hasSubscribers(const QString &topic) const
{
    for (Connection *c : m_connections) {
        if (c->subscribed(topic)) {
            return true;
        }
    }
    return false;
}

void Server::broadcast(const QString &topic, const QString &event, const QJsonObject &data)
{
    QByteArray line;
    for (Connection *c : std::as_const(m_connections)) {
        if (!c->subscribed(topic) || c->isClosing()) {
            continue;
        }
        if (line.isEmpty()) {
            line = toLine(makeEvent(event, data));
        }
        c->sendLine(line);
    }
}

void Server::dispatch(Connection *conn, const QByteArray &line)
{
    stats.requests++;
    QJsonParseError pe{};
    const QJsonDocument doc = QJsonDocument::fromJson(line, &pe);
    const quint64 slot = conn->allocateSlot();
    auto badRequest = [&](const QJsonValue &id, const QString &msg) {
        stats.invalid++;
        Reply r(conn, slot, id);
        r.fail(Err::Invalid, msg);
    };
    if (pe.error != QJsonParseError::NoError || !doc.isObject()) {
        badRequest(QJsonValue(), pe.error != QJsonParseError::NoError ? QStringLiteral("malformed JSON: %1").arg(pe.errorString())
                                                                       : QStringLiteral("request must be a JSON object"));
        return;
    }
    const QJsonObject req = doc.object();
    const QJsonValue id = req.value(QStringLiteral("id"));
    if (!(id.isString() && id.toString().size() <= 256) && !(id.isDouble() && std::isfinite(id.toDouble()))) {
        badRequest(QJsonValue(), QStringLiteral("'id' must be a number or a string of at most 256 characters"));
        return;
    }
    const QJsonValue methodV = req.value(QStringLiteral("method"));
    if (!methodV.isString() || methodV.toString().size() > 64) {
        badRequest(id, QStringLiteral("'method' must be a string"));
        return;
    }
    const QString method = methodV.toString();
    const QJsonValue paramsV = req.value(QStringLiteral("params"));
    if (!paramsV.isUndefined() && !paramsV.isNull() && !paramsV.isObject()) {
        badRequest(id, QStringLiteral("'params' must be an object"));
        return;
    }
    const auto it = m_methods.constFind(method);
    if (it == m_methods.constEnd()) {
        badRequest(id, QStringLiteral("unknown method '%1'").arg(method.left(64)));
        return;
    }
    auto reply = std::make_shared<Reply>(conn, slot, id);
    const MethodSpec &spec = it.value();
    if (!spec.capability.isEmpty() && !m_caps.contains(spec.capability)) {
        reply->fail(Err::Unsupported, QStringLiteral("capability '%1' is not available").arg(spec.capability));
        return;
    }
    if (spec.privileged) {
        if (!conn->privileged()) {
            stats.denied++;
            logOnce(QStringLiteral("deny-%1").arg(conn->peer().exe), QStringLiteral("denied privileged method %1 to %2 (%3)").arg(method, conn->peer().exe, conn->peer().reason));
            reply->fail(Err::Denied, QStringLiteral("'%1' is only available to Kristall's own programs").arg(method));
            return;
        }
        if (isLocked && isLocked()) {
            stats.denied++;
            reply->fail(Err::Denied, QStringLiteral("the screen is locked"));
            return;
        }
    }
    Params params(paramsV.toObject());
    try {
        spec.handler(params, reply);
    } catch (const std::exception &e) {
        logOnce(QStringLiteral("exc-%1").arg(method), QStringLiteral("method %1 threw: %2").arg(method, QString::fromUtf8(e.what())));
        reply->fail(Err::Internal, QStringLiteral("internal error"));
    } catch (...) {
        reply->fail(Err::Internal, QStringLiteral("internal error"));
    }
    if (!reply->done() && params.failed()) {
        stats.invalid++;
        reply->fail(params.error());
    }
}

} // namespace Kristall
