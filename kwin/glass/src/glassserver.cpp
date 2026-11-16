/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "glassserver.h"
#include "glasslog.h"

#include <QDir>
#include <QFile>
#include <QJsonArray>
#include <QJsonDocument>
#include <QLocalSocket>

#include <cerrno>
#include <sys/socket.h>
#include <sys/stat.h>
#include <sys/un.h>
#include <unistd.h>

namespace Kristall
{

QJsonObject SurfaceMatch::toJson() const
{
    QJsonObject o;
    if (!layerNamespace.isEmpty()) {
        o[QStringLiteral("namespace")] = layerNamespace;
    }
    if (!appId.isEmpty()) {
        o[QStringLiteral("appId")] = appId;
    }
    if (!title.isEmpty()) {
        o[QStringLiteral("title")] = title;
    }
    if (!output.isEmpty()) {
        o[QStringLiteral("output")] = output;
    }
    if (pid >= 0) {
        o[QStringLiteral("pid")] = pid;
    }
    return o;
}

GlassServer::GlassServer(QObject *parent)
    : QObject(parent)
{
    m_server.setMaxPendingConnections(16);
    connect(&m_server, &QLocalServer::newConnection, this, &GlassServer::handleNewConnection);
}

GlassServer::~GlassServer()
{
    // Tell clients explicitly before the socket goes away so they fall back at once.
    for (auto &[id, client] : m_clients) {
        client->socket->disconnect(this);
        client->socket->abort();
    }
    m_clients.clear();
    m_server.close();
    if (!m_path.isEmpty()) {
        QFile::remove(m_path);
    }
}

static bool someoneListens(const QString &path)
{
    const int fd = ::socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
    if (fd < 0) {
        return false;
    }
    sockaddr_un addr{};
    addr.sun_family = AF_UNIX;
    const QByteArray p = QFile::encodeName(path);
    if (size_t(p.size()) >= sizeof(addr.sun_path)) {
        ::close(fd);
        return false;
    }
    memcpy(addr.sun_path, p.constData(), p.size());
    // connect() on a unix socket completes or fails immediately; it never blocks the compositor
    const bool live = ::connect(fd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) == 0;
    ::close(fd);
    return live;
}

bool GlassServer::listen()
{
    m_path = qEnvironmentVariable("KRISTALL_GLASS_SOCKET");
    if (m_path.isEmpty()) {
        const QString runtime = qEnvironmentVariable("XDG_RUNTIME_DIR");
        if (runtime.isEmpty()) {
            qCWarning(KRISTALL_GLASS) << "XDG_RUNTIME_DIR is not set; the glass socket is unavailable";
            return false;
        }
        const QString dir = runtime + QStringLiteral("/kristall");
        QDir().mkpath(dir);
        ::chmod(QFile::encodeName(dir).constData(), 0700);
        m_path = dir + QStringLiteral("/glass.sock");
    }
    if (QFile::exists(m_path)) {
        if (someoneListens(m_path)) {
            // e.g. a nested test compositor in the same session; never steal a live socket
            qCWarning(KRISTALL_GLASS) << "another glass server already listens on" << m_path;
            m_path.clear();
            return false;
        }
        QLocalServer::removeServer(m_path); // stale socket of a crashed KWin
    }
    m_server.setSocketOptions(QLocalServer::UserAccessOption);
    if (!m_server.listen(m_path)) {
        qCWarning(KRISTALL_GLASS) << "cannot listen on" << m_path << m_server.errorString();
        m_path.clear();
        return false;
    }
    ::chmod(QFile::encodeName(m_path).constData(), 0600);
    qCInfo(KRISTALL_GLASS) << "listening on" << m_path;
    return true;
}

void GlassServer::handleNewConnection()
{
    while (QLocalSocket *socket = m_server.nextPendingConnection()) {
        ucred cred{};
        socklen_t len = sizeof(cred);
        if (::getsockopt(socket->socketDescriptor(), SOL_SOCKET, SO_PEERCRED, &cred, &len) != 0 || cred.uid != ::getuid()) {
            qCWarning(KRISTALL_GLASS) << "rejecting glass client that is not the session user";
            socket->abort();
            socket->deleteLater();
            continue;
        }
        if (int(m_clients.size()) >= maxClients) {
            qCWarning(KRISTALL_GLASS) << "too many glass clients, rejecting pid" << cred.pid;
            socket->write(R"({"event":"error","code":"limit","message":"too many clients"})" "\n");
            socket->flush();
            socket->disconnectFromServer();
            socket->deleteLater();
            continue;
        }
        auto client = std::make_unique<GlassClient>();
        client->socket = socket;
        client->id = m_nextClientId++;
        client->pid = cred.pid;
        socket->setParent(client.get());
        GlassClient *c = client.get();
        connect(socket, &QLocalSocket::readyRead, this, [this, c]() {
            handleReadyRead(c);
        });
        connect(socket, &QLocalSocket::disconnected, this, [this, c]() {
            handleDisconnect(c);
        }, Qt::QueuedConnection);
        m_clients.emplace(c->id, std::move(client));
        qCDebug(KRISTALL_GLASS) << "client connected, pid" << c->pid;
        send(c, helloObject());
        if (c->socket->bytesAvailable() > 0) {
            handleReadyRead(c);
        }
    }
}

void GlassServer::handleDisconnect(GlassClient *client)
{
    auto it = m_clients.find(client->id);
    if (it == m_clients.end()) {
        return;
    }
    qCDebug(KRISTALL_GLASS) << "client disconnected, pid" << client->pid << client->name;
    const QList<quint64> ids = client->bindings.values();
    for (quint64 id : ids) {
        removeBinding(id);
    }
    const bool hadHint = client->qualityHint.has_value();
    const bool hadTiming = client->timing;
    client->socket->disconnect(this);
    std::unique_ptr<GlassClient> owned = std::move(it->second);
    m_clients.erase(it);
    owned.release()->deleteLater();
    if (hadHint) {
        Q_EMIT qualityHintChanged();
    }
    if (hadTiming) {
        Q_EMIT debugChanged();
    }
}

void GlassServer::handleReadyRead(GlassClient *client)
{
    // Read everything that is available, then process complete lines in order. All changes of
    // one batch reach the effect before it paints again, which coalesces bursts of updates.
    client->buffer += client->socket->readAll();
    qsizetype start = 0;
    while (true) {
        const qsizetype nl = client->buffer.indexOf('\n', start);
        if (nl < 0) {
            break;
        }
        QByteArray line = client->buffer.mid(start, nl - start);
        start = nl + 1;
        if (line.endsWith('\r')) {
            line.chop(1);
        }
        if (line.size() > maxLineBytes) {
            sendError(client, QStringLiteral("too-long"), QStringLiteral("line exceeds 1 MiB"));
            continue;
        }
        if (!line.trimmed().isEmpty()) {
            handleLine(client, line);
        }
        if (m_clients.find(client->id) == m_clients.end()) {
            return; // the client was dropped while handling the line
        }
    }
    client->buffer.remove(0, start);
    if (client->buffer.size() > maxLineBytes) {
        qCWarning(KRISTALL_GLASS) << "dropping client pid" << client->pid << "that sent more than 1 MiB without a newline";
        client->socket->abort();
    }
}

void GlassServer::send(GlassClient *client, const QJsonObject &object)
{
    if (!client->socket || client->socket->state() != QLocalSocket::ConnectedState) {
        return;
    }
    if (client->socket->bytesToWrite() > maxPendingOutputBytes) {
        // a client that never reads must not make the compositor buffer without bound
        qCWarning(KRISTALL_GLASS) << "dropping client pid" << client->pid << "that does not read its socket";
        client->socket->abort();
        return;
    }
    QByteArray data = QJsonDocument(object).toJson(QJsonDocument::Compact);
    data.append('\n');
    client->socket->write(data);
}

void GlassServer::sendError(GlassClient *client, const QString &code, const QString &message, const QJsonObject &context)
{
    QJsonObject o = context;
    o[QStringLiteral("event")] = QStringLiteral("error");
    o[QStringLiteral("code")] = code;
    o[QStringLiteral("message")] = message;
    send(client, o);
}

QJsonObject GlassServer::helloObject() const
{
    QJsonObject o{
        {QStringLiteral("event"), QStringLiteral("hello")},
        {QStringLiteral("server"), QStringLiteral("kristall-glass")},
        {QStringLiteral("protocol"), protocolVersion},
        {QStringLiteral("state"), m_state},
    };
    if (!m_reason.isEmpty()) {
        o[QStringLiteral("reason")] = m_reason;
    }
    for (auto it = m_config.begin(); it != m_config.end(); ++it) {
        o[it.key()] = *it;
    }
    return o;
}

void GlassServer::setState(const QString &state, const QString &reason)
{
    if (state == m_state && reason == m_reason) {
        return;
    }
    m_state = state;
    m_reason = reason;
    QJsonObject o = helloObject();
    o[QStringLiteral("event")] = QStringLiteral("state");
    for (auto &[id, client] : m_clients) {
        send(client.get(), o);
    }
}

void GlassServer::setEffectiveConfig(const QJsonObject &config)
{
    if (config == m_config) {
        return;
    }
    m_config = config;
    QJsonObject o = helloObject();
    o[QStringLiteral("event")] = QStringLiteral("state");
    for (auto &[id, client] : m_clients) {
        send(client.get(), o);
    }
}

void GlassServer::handleLine(GlassClient *client, const QByteArray &line)
{
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(line, &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        sendError(client, QStringLiteral("bad-json"), err.error != QJsonParseError::NoError ? err.errorString() : QStringLiteral("each line must be a JSON object"));
        return;
    }
    const QJsonObject o = doc.object();
    const QString op = o.value(QLatin1String("op")).toString();
    if (op == QLatin1String("shapes")) {
        opShapes(client, o, false);
    } else if (op == QLatin1String("patch")) {
        opShapes(client, o, true);
    } else if (op == QLatin1String("bind")) {
        opBind(client, o);
    } else if (op == QLatin1String("unbind")) {
        opUnbind(client, o);
    } else if (op == QLatin1String("hello")) {
        const QJsonValue name = o.value(QLatin1String("client"));
        if (name.isString()) {
            client->name = name.toString().left(64);
        }
        send(client, helloObject());
    } else if (op == QLatin1String("ping")) {
        QJsonObject pong{{QStringLiteral("event"), QStringLiteral("pong")}};
        if (o.contains(QLatin1String("token"))) {
            pong[QStringLiteral("token")] = o.value(QLatin1String("token"));
        }
        send(client, pong);
    } else if (op == QLatin1String("status")) {
        QJsonObject status = statusProvider ? statusProvider() : QJsonObject();
        status[QStringLiteral("event")] = QStringLiteral("status");
        status[QStringLiteral("state")] = m_state;
        status[QStringLiteral("clients")] = int(m_clients.size());
        status[QStringLiteral("bindings")] = int(m_bindings.size());
        send(client, status);
    } else if (op == QLatin1String("config")) {
        opConfig(client, o);
    } else if (op == QLatin1String("debug")) {
        opDebug(client, o);
    } else {
        sendError(client, QStringLiteral("unknown-op"), QStringLiteral("unknown op '%1'").arg(op), {{QStringLiteral("op"), op}});
    }
}

static bool readMatch(const QJsonObject &m, SurfaceMatch &out, QString *error)
{
    const auto str = [&](const char *key, QString &dst) {
        const QJsonValue v = m.value(QLatin1String(key));
        if (v.isUndefined() || v.isNull()) {
            return true;
        }
        if (!v.isString() || v.toString().size() > 256) {
            *error = QStringLiteral("match.%1 must be a string").arg(QLatin1String(key));
            return false;
        }
        dst = v.toString();
        return true;
    };
    if (!str("namespace", out.layerNamespace) || !str("appId", out.appId) || !str("title", out.title) || !str("output", out.output)) {
        return false;
    }
    const QJsonValue pid = m.value(QLatin1String("pid"));
    if (!pid.isUndefined() && !pid.isNull()) {
        if (!pid.isDouble() || pid.toDouble() < 0) {
            *error = QStringLiteral("match.pid must be a non-negative integer");
            return false;
        }
        out.pid = qint64(pid.toDouble());
    }
    if (out.layerNamespace.isEmpty() && out.appId.isEmpty()) {
        *error = QStringLiteral("match needs 'namespace' (layer-shell) or 'appId' (xdg-toplevel)");
        return false;
    }
    return true;
}

static bool readSurfaceKey(const QJsonObject &o, QString &key)
{
    const QJsonValue v = o.value(QLatin1String("surface"));
    if (!v.isString() || v.toString().isEmpty() || v.toString().size() > 128) {
        return false;
    }
    key = v.toString();
    return true;
}

void GlassServer::opBind(GlassClient *c, const QJsonObject &o)
{
    QString key;
    if (!readSurfaceKey(o, key)) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("'surface' must be a non-empty string of at most 128 characters"), {{QStringLiteral("op"), QStringLiteral("bind")}});
        return;
    }
    const QJsonObject ctx{{QStringLiteral("op"), QStringLiteral("bind")}, {QStringLiteral("surface"), key}};
    SurfaceMatch match;
    QString error;
    if (!o.value(QLatin1String("match")).isObject()) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("'match' must be an object"), ctx);
        return;
    }
    if (!readMatch(o.value(QLatin1String("match")).toObject(), match, &error)) {
        sendError(c, QStringLiteral("bad-request"), error, ctx);
        return;
    }
    if (auto it = c->bindings.find(key); it != c->bindings.end()) {
        SurfaceBinding &b = *m_bindings.at(*it);
        b.match = match;
        b.windows = -1; // report the (possibly new) window count again
        Q_EMIT bindingChanged(b.id, true);
        return;
    }
    if (c->bindings.size() >= maxBindingsPerClient) {
        sendError(c, QStringLiteral("limit"), QStringLiteral("at most 64 surfaces per connection"), ctx);
        return;
    }
    auto b = std::make_unique<SurfaceBinding>();
    b->id = m_nextBindingId++;
    b->client = c;
    b->key = key;
    b->match = match;
    b->peerPid = c->pid;
    const quint64 id = b->id;
    c->bindings.insert(key, id);
    m_bindings.emplace(id, std::move(b));
    Q_EMIT bindingChanged(id, true);
}

void GlassServer::applyShapes(SurfaceBinding &b, QList<ShapeSpec> &&shapes)
{
    b.shapes = std::move(shapes);
    b.version++;
    Q_EMIT bindingChanged(b.id, false);
}

void GlassServer::opShapes(GlassClient *c, const QJsonObject &o, bool patch)
{
    const QString op = patch ? QStringLiteral("patch") : QStringLiteral("shapes");
    QString key;
    if (!readSurfaceKey(o, key)) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("'surface' must be a non-empty string"), {{QStringLiteral("op"), op}});
        return;
    }
    const QJsonObject ctx{{QStringLiteral("op"), op}, {QStringLiteral("surface"), key}};
    const auto bit = c->bindings.constFind(key);
    if (bit == c->bindings.constEnd()) {
        sendError(c, QStringLiteral("unknown-surface"), QStringLiteral("surface '%1' was not bound on this connection").arg(key), ctx);
        return;
    }
    SurfaceBinding &b = *m_bindings.at(*bit);
    const QJsonValue shapesValue = o.value(QLatin1String("shapes"));
    if (!shapesValue.isArray()) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("'shapes' must be an array"), ctx);
        return;
    }
    const QJsonArray array = shapesValue.toArray();
    if (array.size() > Limits::maxShapesPerSurface) {
        sendError(c, QStringLiteral("limit"), QStringLiteral("at most 64 shapes per surface"), ctx);
        return;
    }
    const QString sync = o.value(QLatin1String("sync")).toString(QStringLiteral("immediate"));
    if (sync != QLatin1String("immediate") && sync != QLatin1String("commit")) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("'sync' must be \"immediate\" or \"commit\""), ctx);
        return;
    }

    // Validate everything first; a message is applied entirely or not at all.
    QList<ShapeSpec> result;
    QString error;
    if (patch) {
        result = b.pending.value_or(b.shapes);
        for (const QJsonValue &v : array) {
            const QJsonObject so = v.toObject();
            const QString id = so.value(QLatin1String("id")).toString();
            auto it = std::find_if(result.begin(), result.end(), [&](const ShapeSpec &s) {
                return s.id == id;
            });
            if (!v.isObject() || it == result.end()) {
                sendError(c, QStringLiteral("bad-request"), QStringLiteral("patch refers to unknown shape id '%1'").arg(id), ctx);
                return;
            }
            if (!patchShape(*it, so, &error)) {
                sendError(c, QStringLiteral("bad-request"), error, ctx);
                return;
            }
        }
    } else {
        result.reserve(array.size());
        QSet<QString> ids;
        for (const QJsonValue &v : array) {
            if (!v.isObject()) {
                sendError(c, QStringLiteral("bad-request"), QStringLiteral("each shape must be an object"), ctx);
                return;
            }
            auto shape = parseShape(v.toObject(), &error);
            if (!shape) {
                sendError(c, QStringLiteral("bad-request"), error, ctx);
                return;
            }
            if (ids.contains(shape->id)) {
                sendError(c, QStringLiteral("bad-request"), QStringLiteral("duplicate shape id '%1'").arg(shape->id), ctx);
                return;
            }
            ids.insert(shape->id);
            result.append(std::move(*shape));
        }
    }

    if (sync == QLatin1String("commit") && b.windows > 0) {
        b.pending = std::move(result);
        if (!b.pendingTimer) {
            b.pendingTimer = std::make_unique<QTimer>();
            b.pendingTimer->setSingleShot(true);
            b.pendingTimer->setInterval(commitSyncTimeoutMs);
            const quint64 id = b.id;
            connect(b.pendingTimer.get(), &QTimer::timeout, this, [this, id]() {
                surfaceCommitted(id);
            });
        }
        if (!b.pendingTimer->isActive()) {
            b.pendingTimer->start();
        }
        return;
    }
    b.pending.reset();
    if (b.pendingTimer) {
        b.pendingTimer->stop();
    }
    applyShapes(b, std::move(result));
}

void GlassServer::surfaceCommitted(quint64 bindingId)
{
    auto it = m_bindings.find(bindingId);
    if (it == m_bindings.end() || !it->second->pending) {
        return;
    }
    SurfaceBinding &b = *it->second;
    if (b.pendingTimer) {
        b.pendingTimer->stop();
    }
    QList<ShapeSpec> shapes = std::move(*b.pending);
    b.pending.reset();
    applyShapes(b, std::move(shapes));
}

void GlassServer::opUnbind(GlassClient *c, const QJsonObject &o)
{
    QString key;
    if (!readSurfaceKey(o, key) || !c->bindings.contains(key)) {
        sendError(c, QStringLiteral("unknown-surface"), QStringLiteral("surface was not bound on this connection"), {{QStringLiteral("op"), QStringLiteral("unbind")}});
        return;
    }
    removeBinding(c->bindings.value(key));
}

void GlassServer::removeBinding(quint64 id)
{
    auto it = m_bindings.find(id);
    if (it == m_bindings.end()) {
        return;
    }
    std::unique_ptr<SurfaceBinding> b = std::move(it->second);
    m_bindings.erase(it);
    b->client->bindings.remove(b->key);
    Q_EMIT bindingRemoved(id);
}

void GlassServer::opConfig(GlassClient *c, const QJsonObject &o)
{
    const QJsonValue hint = o.value(QLatin1String("qualityHint"));
    if (hint.isUndefined()) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("config needs 'qualityHint'"), {{QStringLiteral("op"), QStringLiteral("config")}});
        return;
    }
    std::optional<QString> value;
    if (hint.isString() && (hint.toString() == QLatin1String("high") || hint.toString() == QLatin1String("efficient"))) {
        value = hint.toString();
    } else if (!hint.isNull()) {
        sendError(c, QStringLiteral("bad-request"), QStringLiteral("qualityHint must be \"high\", \"efficient\" or null"), {{QStringLiteral("op"), QStringLiteral("config")}});
        return;
    }
    // the most recent hint wins; it is dropped again when its client disconnects
    for (auto &[id, other] : m_clients) {
        other->qualityHint.reset();
    }
    c->qualityHint = value;
    Q_EMIT qualityHintChanged();
}

std::optional<QString> GlassServer::qualityHint() const
{
    for (const auto &[id, client] : m_clients) {
        if (client->qualityHint) {
            return client->qualityHint;
        }
    }
    return std::nullopt;
}

bool GlassServer::timingEnabled() const
{
    for (const auto &[id, client] : m_clients) {
        if (client->timing) {
            return true;
        }
    }
    return qEnvironmentVariableIntValue("KRISTALL_GLASS_TIMING") != 0;
}

void GlassServer::opDebug(GlassClient *c, const QJsonObject &o)
{
    if (o.contains(QLatin1String("timing"))) {
        c->timing = o.value(QLatin1String("timing")).toBool();
    }
    if (o.contains(QLatin1String("isolate"))) {
        const QString iso = o.value(QLatin1String("isolate")).toString();
        if (iso != QLatin1String("none") && iso != QLatin1String("refraction")) {
            sendError(c, QStringLiteral("bad-request"), QStringLiteral("isolate must be \"none\" or \"refraction\""), {{QStringLiteral("op"), QStringLiteral("debug")}});
            return;
        }
        m_isolate = iso;
    }
    Q_EMIT debugChanged();
    send(c, {{QStringLiteral("event"), QStringLiteral("debug")}, {QStringLiteral("timing"), c->timing}, {QStringLiteral("isolate"), m_isolate}});
}

const SurfaceBinding *GlassServer::binding(quint64 id) const
{
    auto it = m_bindings.find(id);
    return it == m_bindings.end() ? nullptr : it->second.get();
}

QList<quint64> GlassServer::bindingIds() const
{
    QList<quint64> ret;
    ret.reserve(m_bindings.size());
    for (const auto &[id, b] : m_bindings) {
        ret.append(id);
    }
    return ret;
}

void GlassServer::setBoundWindows(quint64 bindingId, int windows)
{
    auto it = m_bindings.find(bindingId);
    if (it == m_bindings.end() || it->second->windows == windows) {
        return;
    }
    SurfaceBinding &b = *it->second;
    b.windows = windows;
    send(b.client, {{QStringLiteral("event"), QStringLiteral("bound")}, {QStringLiteral("surface"), b.key}, {QStringLiteral("windows"), windows}});
}

void GlassServer::sendLegibility(quint64 bindingId, const QString &shapeId, const QString &scheme, double luminance)
{
    auto it = m_bindings.find(bindingId);
    if (it == m_bindings.end()) {
        return;
    }
    const SurfaceBinding &b = *it->second;
    send(b.client, {
                       {QStringLiteral("event"), QStringLiteral("legibility")},
                       {QStringLiteral("surface"), b.key},
                       {QStringLiteral("shape"), shapeId},
                       {QStringLiteral("scheme"), scheme},
                       {QStringLiteral("luminance"), std::round(luminance * 1000.0) / 1000.0},
                   });
}

void GlassServer::sendTiming(const QJsonObject &timing)
{
    QJsonObject o = timing;
    o[QStringLiteral("event")] = QStringLiteral("timing");
    for (auto &[id, client] : m_clients) {
        if (client->timing) {
            send(client.get(), o);
        }
    }
}

} // namespace Kristall
