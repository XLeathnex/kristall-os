/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include "server.h"

#include <QElapsedTimer>
#include <QObject>
#include <QPointer>
#include <QPointF>
#include <QRectF>
#include <QTimer>

#include <functional>
#include <memory>
#include <optional>

namespace KWin
{
class Window;
class SurfaceInterface;
}

namespace Kristall
{

class WindowModel;
class LayerScopes;
class HelperClient;
class AgentKeyboard;
class OwnerWatch;

// What lies under a point, as the agent's input will see it.
struct PointTarget
{
    QPointer<KWin::Window> window;
    QPointer<KWin::SurfaceInterface> surface; // main surface of the window; null for decoration/internal
    bool decoration = false;
    bool internal = false;
};

// Agent input that never touches the owner's pointer. See docs/contracts/bridge.md and README.md:
// events are delivered to the target surface through the Wayland seat (enter / motion / button /
// axis / frame) while the global cursor position is never changed; the seat's pointer focus is
// handed back to the surface under the owner's pointer before control returns to the event loop.
class Agent : public QObject
{
    Q_OBJECT
public:
    Agent(Server *server, WindowModel *windows, LayerScopes *scopes, HelperClient *helper, QObject *parent);
    ~Agent() override;

    bool sessionActive() const
    {
        return !m_token.isEmpty();
    }
    void endSession(const QString &label);
    // returns false (and fails the reply) when the session token is not the active one
    bool checkSession(Params &p, const ReplyPtr &reply);
    void touchSession();

    // owner priority
    bool ownerPointerBusy() const;
    bool ownerKeyboardBusy() const;
    // runs `proceed` as soon as the owner is not holding a button/dragging; `busy` after 1 s
    void whenOwnerIdle(bool keyboard, const ReplyPtr &reply, std::function<void()> proceed);

    PointTarget resolve(const QPointF &pos) const;
    void broadcastPointer(const QJsonObject &data);

    // called by OwnerWatch
    void ownerPointerActivity();
    void ownerEscape();
    void ownerKey(quint32 scanCode);

    struct DebugStats
    {
        quint64 cursorMovesDuringAgent = 0;
        quint64 agentCalls = 0;
        quint64 framesDuringAgent = 0;
        quint64 framesCursorDisplaced = 0;
        bool tracing = false;
        QList<QJsonObject> frames;
        QElapsedTimer loopClock;
        double loopWorstMs = 0;
        quint64 loopTicks = 0;
    } debug;
    bool inAgentCall() const
    {
        return m_inCall > 0 || m_hold.has_value() || m_hoverTimer.isActive();
    }

private:
    friend class AgentKeyboard;
    struct Hold
    {
        PointTarget target;
        quint32 button = 0; // evdev code
        Qt::MouseButton qtButton = Qt::NoButton;
        QPointF pos;
        QPointF pressPos;
        quint32 pressSerial = 0;
        // window move/resize performed by the agent (title-bar drag, or a client-requested move)
        bool manualMove = false;
        bool manualResize = false;
        int resizeGravity = 0;
        QRectF startGeometry;
        bool dnd = false;
        ReplyPtr pendingReply; // a drag in progress
    };

    void registerMethods();
    void beginSession(Params &p, const ReplyPtr &reply);
    void pointer(Params &p, const ReplyPtr &reply);
    void drag(Params &p, const ReplyPtr &reply);

    // seat-level primitives
    void enterTarget(const PointTarget &t, const QPointF &pos);
    void restoreOwnerFocus();
    void sendButton(quint32 button, bool pressed);
    void releaseButtonSilently(quint32 button);
    void sendModifiers(const PointTarget &t, const QStringList &mods);
    void restoreModifiers(const PointTarget &t);
    void decorationEvent(const PointTarget &t, int type, const QPointF &global, Qt::MouseButton button, Qt::MouseButtons buttons);
    void decorationRestore(const PointTarget &t);

    bool dismissPopupsFor(const PointTarget &t);
    bool activateOnPress(const PointTarget &t, Qt::MouseButton button, const QPointF &pos);
    void releaseCommand(const PointTarget &t, Qt::MouseButton button, const QPointF &pos);
    QJsonObject targetJson(const PointTarget &t) const;

    void clickAt(const PointTarget &t, const QPointF &pos, quint32 button, Qt::MouseButton qtButton, int count, const QStringList &mods, QJsonObject &extra);
    void scrollAt(const PointTarget &t, const QPointF &pos, double dx, double dy, const QStringList &mods);
    bool startHold(const PointTarget &t, const QPointF &pos, quint32 button, Qt::MouseButton qtButton, const QStringList &mods, QString *error);
    void holdMotion(const QPointF &pos);
    void finishHold(bool interrupted, const QString &why = QString());
    void onInteractiveMoveResizeStarted(KWin::Window *w);
    std::chrono::microseconds nextTimestamp();

    Server *m_server;
    WindowModel *m_windows;
    LayerScopes *m_scopes;
    HelperClient *m_helper;
    std::unique_ptr<OwnerWatch> m_watch;
    std::unique_ptr<AgentKeyboard> m_keyboard;

    QString m_token;
    QString m_label;
    QPointer<Connection> m_sessionConn;
    QTimer m_idleTimer;

    std::optional<Hold> m_hold;
    bool m_forcedPointer = false;
    bool m_forcedKeyboard = false;
    QPointF m_hoverPos; // for move with hoverMs
    QTimer m_hoverTimer;
    std::function<void()> m_hoverFinish;
    QTimer m_dragTimer;
    QTimer m_loopTimer; // development mode only: event-loop lateness probe
    int m_inCall = 0;
    std::chrono::microseconds m_lastTimestamp{0};
    QList<QMetaObject::Connection> m_holdConnections;
};

} // namespace Kristall
