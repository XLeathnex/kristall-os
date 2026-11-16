/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    $XDG_RUNTIME_DIR/kristall/glass.sock — newline-delimited JSON. The protocol is specified in
    docs/contracts/glass.md; keep the two in sync.
*/
#pragma once

#include "glassshape.h"

#include <QHash>
#include <QJsonObject>
#include <QList>
#include <QLocalServer>
#include <QObject>
#include <QPointer>
#include <QTimer>

#include <functional>
#include <map>
#include <memory>
#include <optional>

class QLocalSocket;

namespace Kristall
{

class GlassClient;

struct SurfaceMatch
{
    QString layerNamespace;
    QString appId;
    QString title;
    QString output;
    qint64 pid = -1; ///< -1: the connecting peer's pid; 0: any pid
    QJsonObject toJson() const;
};

struct SurfaceBinding
{
    quint64 id = 0;
    GlassClient *client = nullptr;
    QString key; ///< client-chosen name ("surface" field)
    SurfaceMatch match;
    qint64 peerPid = 0;
    QList<ShapeSpec> shapes;
    quint64 version = 0; ///< increments on every applied change
    std::optional<QList<ShapeSpec>> pending; ///< waiting for a commit (sync:"commit")
    std::unique_ptr<QTimer> pendingTimer;
    int windows = -1; ///< last count reported to the client
};

class GlassClient : public QObject
{
    Q_OBJECT
public:
    QLocalSocket *socket = nullptr;
    QByteArray buffer;
    quint64 id = 0;
    qint64 pid = 0;
    QString name;
    QHash<QString, quint64> bindings; ///< key -> binding id
    std::optional<QString> qualityHint;
    bool timing = false;
};

class GlassServer : public QObject
{
    Q_OBJECT

public:
    static constexpr int protocolVersion = 1;
    static constexpr int maxClients = 32;
    static constexpr int maxBindingsPerClient = 64;
    static constexpr qsizetype maxLineBytes = 1024 * 1024;
    static constexpr qsizetype maxPendingOutputBytes = 4 * 1024 * 1024;
    static constexpr int commitSyncTimeoutMs = 100;

    explicit GlassServer(QObject *parent = nullptr);
    ~GlassServer() override;

    bool listen();
    QString socketPath() const { return m_path; }

    /// "active" | "disabled" | "failed"; changes are broadcast as a "state" event
    void setState(const QString &state, const QString &reason);
    QString state() const { return m_state; }
    void setEffectiveConfig(const QJsonObject &config); ///< broadcast as part of "state"

    const SurfaceBinding *binding(quint64 id) const;
    QList<quint64> bindingIds() const;

    void setBoundWindows(quint64 bindingId, int windows);
    void sendLegibility(quint64 bindingId, const QString &shapeId, const QString &scheme, double luminance);
    void sendTiming(const QJsonObject &timing);
    /// the bound surface committed: apply shapes that were sent with sync:"commit"
    void surfaceCommitted(quint64 bindingId);

    std::optional<QString> qualityHint() const;
    bool timingEnabled() const;
    QString isolate() const { return m_isolate; }

    std::function<QJsonObject()> statusProvider;

Q_SIGNALS:
    void bindingChanged(quint64 id, bool matchChanged);
    void bindingRemoved(quint64 id);
    void qualityHintChanged();
    void debugChanged();

private:
    void handleNewConnection();
    void handleReadyRead(GlassClient *client);
    void handleDisconnect(GlassClient *client);
    void handleLine(GlassClient *client, const QByteArray &line);
    void send(GlassClient *client, const QJsonObject &object);
    void sendError(GlassClient *client, const QString &code, const QString &message, const QJsonObject &context = {});
    QJsonObject helloObject() const;
    void removeBinding(quint64 id);
    void applyShapes(SurfaceBinding &b, QList<ShapeSpec> &&shapes);

    void opBind(GlassClient *c, const QJsonObject &o);
    void opShapes(GlassClient *c, const QJsonObject &o, bool patch);
    void opUnbind(GlassClient *c, const QJsonObject &o);
    void opConfig(GlassClient *c, const QJsonObject &o);
    void opDebug(GlassClient *c, const QJsonObject &o);

    QLocalServer m_server;
    QString m_path;
    QString m_state = QStringLiteral("active");
    QString m_reason;
    QJsonObject m_config;
    QString m_isolate = QStringLiteral("none");
    std::map<quint64, std::unique_ptr<GlassClient>> m_clients;
    std::map<quint64, std::unique_ptr<SurfaceBinding>> m_bindings;
    quint64 m_nextClientId = 1;
    quint64 m_nextBindingId = 1;
};

} // namespace Kristall
