/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QHash>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QSet>
#include <QTimer>

namespace KWin
{
class Window;
class SurfaceInterface;
class LogicalOutput;
}

namespace Kristall
{

class Server;
class HelperClient;

// Layer-shell namespaces by surface. KWin does not export LayerShellV1Window, so the bridge records
// each layer surface's namespace when the surface is created (plugins load before the Wayland
// server accepts clients, so no surface is missed).
class LayerScopes : public QObject
{
    Q_OBJECT
public:
    explicit LayerScopes(QObject *parent);
    // namespace of the window's layer surface, or a null QString if it is not a layer surface
    QString scopeOf(const KWin::Window *window) const;
    bool isAssistantOverlay(const KWin::Window *window) const; // namespace starts with kristall-assistant
    bool isBridgeInternal(const KWin::Window *window) const; // our own helper surfaces
    bool isShell(const KWin::Window *window) const; // namespace starts with kristall-

private:
    QHash<const KWin::SurfaceInterface *, QString> m_scopes;
};

class WindowModel : public QObject
{
    Q_OBJECT
public:
    WindowModel(Server *server, LayerScopes *scopes, QObject *parent);
    ~WindowModel() override;

    void setHelper(HelperClient *helper)
    {
        m_helper = helper;
    }

    static QString idOf(const KWin::Window *window);
    KWin::Window *find(const QString &id) const;
    bool tracked(const KWin::Window *window) const;
    QJsonObject serialize(KWin::Window *window) const;
    QJsonObject outputsData() const;
    QJsonObject desktopsData() const;
    QJsonArray windowsArray() const;
    QJsonArray stackingArray() const;

private:
    void registerMethods();
    void track(KWin::Window *window, bool announce);
    void untrack(KWin::Window *window);
    void markDirty(KWin::Window *window);
    void watchConstraints(KWin::Window *window);
    void scheduleFlush();
    void flush();
    bool shouldTrack(KWin::Window *window) const;
    int frameIntervalMs() const;

    Server *m_server;
    LayerScopes *m_scopes;
    HelperClient *m_helper = nullptr;
    QHash<QString, QPointer<KWin::Window>> m_byId;
    QHash<KWin::Window *, QJsonObject> m_lastSent;
    QSet<KWin::Window *> m_dirty;
    QHash<KWin::Window *, QList<QMetaObject::Connection>> m_connections;
    QHash<KWin::Window *, QList<QMetaObject::Connection>> m_constraintConnections; // on the window's current surface
    bool m_stackingDirty = false;
    bool m_outputsDirty = false;
    QJsonObject m_lastOutputs; // what outputs subscribers were last told
    bool m_desktopsDirty = false;
    QTimer m_flushTimer;
    QList<QMetaObject::Connection> m_outputConnections;
};

} // namespace Kristall
