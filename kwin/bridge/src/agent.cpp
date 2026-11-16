/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "agent.h"
#include "agentkeyboard.h"
#include "helperclient.h"
#include "windows.h"

#include "core/backendoutput.h"
#include "core/output.h"
#include "core/renderloop.h"
#include "cursor.h"
#include "effect/effecthandler.h"
#include "input.h"
#include "input_event.h"
#include "input_event_spy.h"
#include "keyboard_input.h"
#include "main.h"
#include "options.h"
#include "pointer_input.h"
#include "scene/item.h"
#include "scene/workspacescene.h"
#include "virtualdesktops.h"
#include "wayland/clientconnection.h"
#include "wayland/keyboard.h"
#include "wayland/pointer.h"
#include "wayland/seat.h"
#include "wayland/surface.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"
#include "xkb.h"

#include <KDecoration3/Decoration>

#include <QCoreApplication>
#include <QHoverEvent>
#include <QJsonArray>
#include <QMouseEvent>

#include <linux/input-event-codes.h>
#include <xkbcommon/xkbcommon.h>

#include <cmath>

using namespace KWin;
using namespace std::chrono_literals;

namespace Kristall
{

constexpr int kSessionIdleMs = 120 * 1000;
constexpr int kOwnerWaitMs = 1000;

// ------------------------------------------------------------------------------------ OwnerWatch

// Observes the owner's real input (all devices, before any other filter). It never consumes an
// event. Its jobs: Escape ends the agent session; owner pointer activity interrupts a gesture the
// agent is holding (owner priority); in development mode it records presented frames.
class OwnerWatch : public InputEventFilter
{
public:
    explicit OwnerWatch(Agent *agent)
        : InputEventFilter(InputFilterOrder::PlaceholderOutput)
        , m_agent(agent)
    {
        input()->installInputEventFilter(this);
    }
    ~OwnerWatch() override
    {
        if (input()) {
            input()->uninstallInputEventFilter(this);
        }
    }
    bool pointerMotion(PointerMotionEvent *) override
    {
        m_agent->ownerPointerActivity();
        return false;
    }
    bool pointerButton(PointerButtonEvent *) override
    {
        m_agent->ownerPointerActivity();
        return false;
    }
    bool pointerAxis(PointerAxisEvent *) override
    {
        m_agent->ownerPointerActivity();
        return false;
    }
    bool keyboardKey(KeyboardKeyEvent *event) override
    {
        if (event->state == KeyboardKeyState::Pressed) {
            m_agent->ownerKey(event->nativeScanCode);
            if (event->key == Qt::Key_Escape) {
                m_agent->ownerEscape();
            }
        }
        return false;
    }

private:
    Agent *m_agent;
};

// ------------------------------------------------------------------------------------ helpers

static bool parseButton(const QString &name, quint32 *code, Qt::MouseButton *qt)
{
    if (name == QLatin1String("left")) {
        *code = BTN_LEFT;
        *qt = Qt::LeftButton;
    } else if (name == QLatin1String("right")) {
        *code = BTN_RIGHT;
        *qt = Qt::RightButton;
    } else if (name == QLatin1String("middle")) {
        *code = BTN_MIDDLE;
        *qt = Qt::MiddleButton;
    } else if (name == QLatin1String("back")) {
        *code = BTN_SIDE;
        *qt = Qt::BackButton;
    } else if (name == QLatin1String("forward")) {
        *code = BTN_EXTRA;
        *qt = Qt::ForwardButton;
    } else {
        return false;
    }
    return true;
}

static bool validModifiers(const QStringList &mods)
{
    static const QSet<QString> ok = {QStringLiteral("ctrl"), QStringLiteral("shift"), QStringLiteral("alt"), QStringLiteral("meta")};
    for (const QString &m : mods) {
        if (!ok.contains(m)) {
            return false;
        }
    }
    return true;
}

xkb_mod_mask_t modifierMask(const QStringList &mods)
{
    xkb_keymap *keymap = input()->keyboard()->xkb()->keymap();
    if (!keymap) {
        return 0;
    }
    xkb_mod_mask_t mask = 0;
    auto add = [&](const char *name) {
        const xkb_mod_index_t idx = xkb_keymap_mod_get_index(keymap, name);
        if (idx != XKB_MOD_INVALID) {
            mask |= (1u << idx);
        }
    };
    for (const QString &m : mods) {
        if (m == QLatin1String("ctrl")) {
            add(XKB_MOD_NAME_CTRL);
        } else if (m == QLatin1String("shift")) {
            add(XKB_MOD_NAME_SHIFT);
        } else if (m == QLatin1String("alt")) {
            add(XKB_MOD_NAME_ALT);
        } else if (m == QLatin1String("meta")) {
            add(XKB_MOD_NAME_LOGO);
        }
    }
    return mask;
}

// ------------------------------------------------------------------------------------ Agent

Agent::Agent(Server *server, WindowModel *windows, LayerScopes *scopes, HelperClient *helper, QObject *parent)
    : QObject(parent)
    , m_server(server)
    , m_windows(windows)
    , m_scopes(scopes)
    , m_helper(helper)
{
    m_watch = std::make_unique<OwnerWatch>(this);
    m_keyboard = std::make_unique<AgentKeyboard>(this, server, windows, helper);

    m_idleTimer.setSingleShot(true);
    m_idleTimer.setInterval(kSessionIdleMs);
    connect(&m_idleTimer, &QTimer::timeout, this, [this]() {
        endSession(QStringLiteral("timeout"));
    });
    m_hoverTimer.setSingleShot(true);
    connect(&m_hoverTimer, &QTimer::timeout, this, [this]() {
        if (m_hoverFinish) {
            auto f = std::move(m_hoverFinish);
            f();
        }
    });
    m_dragTimer.setSingleShot(true);
    m_loopTimer.setTimerType(Qt::PreciseTimer);
    connect(&m_loopTimer, &QTimer::timeout, this, [this]() {
        const double ms = debug.loopClock.nsecsElapsed() / 1e6;
        debug.loopClock.restart();
        debug.loopWorstMs = std::max(debug.loopWorstMs, ms - 2.0);
        debug.loopTicks++;
    });

    connect(server, &Server::connectionClosed, this, [this](Connection *c) {
        if (sessionActive() && c == m_sessionConn) {
            endSession(QStringLiteral("disconnected"));
        }
    });
    connect(waylandServer(), &WaylandServer::lockStateChanged, this, [this]() {
        if (waylandServer()->isScreenLocked()) {
            finishHold(true, QStringLiteral("the screen was locked"));
            endSession(QStringLiteral("locked"));
        }
    });
    // Escape/owner checks need nothing else; the frame trace below exists only in development mode
    if (server->devMode()) {
        connect(Cursors::self()->mouse(), &Cursor::posChanged, this, [this]() {
            if (inAgentCall()) {
                debug.cursorMovesDuringAgent++;
            }
        });
        auto hookOutputs = [this]() {
            for (LogicalOutput *o : workspace()->outputs()) {
                RenderLoop *loop = o->backendOutput() ? o->backendOutput()->renderLoop() : nullptr;
                if (!loop || loop->property("kristallHooked").toBool()) {
                    continue;
                }
                loop->setProperty("kristallHooked", true);
                connect(loop, &RenderLoop::framePresented, this, [this, name = o->name()](RenderLoop *, std::chrono::nanoseconds ts, PresentationMode) {
                    if (!debug.tracing) {
                        return;
                    }
                    const QPointF cursor = Cursors::self()->mouse()->pos();
                    QPointF item;
                    if (kwinApp()->scene() && kwinApp()->scene()->cursorItem()) {
                        item = kwinApp()->scene()->cursorItem()->position();
                    }
                    const bool agent = inAgentCall();
                    if (agent) {
                        debug.framesDuringAgent++;
                    }
                    if (debug.frames.size() < 20000) {
                        debug.frames.append(QJsonObject{{QStringLiteral("output"), name},
                                                        {QStringLiteral("t"), double(ts.count()) / 1e6},
                                                        {QStringLiteral("cursorX"), cursor.x()},
                                                        {QStringLiteral("cursorY"), cursor.y()},
                                                        {QStringLiteral("itemX"), item.x()},
                                                        {QStringLiteral("itemY"), item.y()},
                                                        {QStringLiteral("agent"), agent}});
                    }
                });
            }
        };
        connect(workspace(), &Workspace::outputsChanged, this, hookOutputs);
        hookOutputs();
    }
    m_server->setSnapshotProvider(QStringLiteral("agent"), [this]() {
        return QList<QJsonObject>{makeEvent(QStringLiteral("agent.state"), QJsonObject{{QStringLiteral("active"), sessionActive()}, {QStringLiteral("label"), m_label}})};
    });
    registerMethods();
}

Agent::~Agent()
{
    finishHold(true, QStringLiteral("bridge unloading"));
    m_watch.reset();
}

// ------------------------------------------------------------------------------------ session

void Agent::beginSession(Params &p, const ReplyPtr &reply)
{
    const auto label = p.string(QStringLiteral("label"), false, 200);
    if (!label) {
        return;
    }
    if (sessionActive()) {
        reply->fail(Err::Busy, QStringLiteral("another agent session is active"));
        return;
    }
    m_token = randomToken(16);
    m_label = *label;
    // Clients only create wl_pointer/wl_keyboard objects while the seat advertises them, which
    // KWin does only when such a device exists. The agent must work on a touch-only or
    // keyboard-less machine too, so the bridge advertises both for the session.
    SeatInterface *seat = waylandServer()->seat();
    if (!seat->hasPointer()) {
        seat->setHasPointer(true);
        m_forcedPointer = true;
    }
    if (!seat->hasKeyboard()) {
        seat->setHasKeyboard(true);
        m_forcedKeyboard = true;
    }
    m_sessionConn = reply->connection();
    m_idleTimer.start();
    reply->ok(QJsonObject{{QStringLiteral("session"), m_token}});
    m_server->broadcast(QStringLiteral("agent"), QStringLiteral("agent.state"), QJsonObject{{QStringLiteral("active"), true}, {QStringLiteral("label"), m_label}});
}

void Agent::endSession(const QString &label)
{
    if (!sessionActive()) {
        return;
    }
    finishHold(true, QStringLiteral("the agent session ended"));
    m_keyboard->abortAll(label);
    m_token.clear();
    m_label.clear();
    m_sessionConn.clear();
    SeatInterface *seat = waylandServer()->seat();
    if (std::exchange(m_forcedPointer, false) && !input()->hasPointer()) {
        seat->setHasPointer(false);
    }
    // a keyboard capability without a keyboard is harmless (and KWin re-evaluates it whenever
    // devices change), so it is left advertised
    m_forcedKeyboard = false;
    m_idleTimer.stop();
    m_server->broadcast(QStringLiteral("agent"), QStringLiteral("agent.state"), QJsonObject{{QStringLiteral("active"), false}, {QStringLiteral("label"), label}});
}

bool Agent::checkSession(Params &p, const ReplyPtr &reply)
{
    const auto token = p.string(QStringLiteral("session"), true, 128);
    if (!token) {
        return false;
    }
    if (!sessionActive() || *token != m_token) {
        reply->fail(Err::Denied, QStringLiteral("no active agent session with this token"));
        return false;
    }
    touchSession();
    return true;
}

void Agent::touchSession()
{
    if (sessionActive()) {
        m_idleTimer.start();
    }
}

void Agent::ownerEscape()
{
    if (sessionActive()) {
        endSession(QStringLiteral("cancelled"));
    }
}

void Agent::ownerKey(quint32 scanCode)
{
    m_keyboard->ownerKey(scanCode);
}

void Agent::ownerPointerActivity()
{
    if (m_hold) {
        finishHold(true, QStringLiteral("the owner used the pointer"));
    }
    if (m_hoverTimer.isActive()) {
        m_hoverTimer.stop();
        if (m_hoverFinish) {
            auto f = std::move(m_hoverFinish);
            f();
        }
    }
}

// ------------------------------------------------------------------------------------ owner priority

bool Agent::ownerPointerBusy() const
{
    if (input()->pointer()->areButtonsPressed()) {
        return true;
    }
    if (workspace()->moveResizeWindow()) {
        return true;
    }
    SeatInterface *seat = waylandServer()->seat();
    if ((seat->isDragPointer() || seat->isTouchSequence()) && !m_hold) {
        return true;
    }
    return false;
}

bool Agent::ownerKeyboardBusy() const
{
    // a key the owner is holding (other than lock keys) would combine with ours
    return !input()->keyboard()->pressedKeys().isEmpty();
}

void Agent::whenOwnerIdle(bool keyboard, const ReplyPtr &reply, std::function<void()> proceed)
{
    auto busy = [this, keyboard]() {
        return keyboard ? ownerKeyboardBusy() : ownerPointerBusy();
    };
    if (!busy()) {
        proceed();
        return;
    }
    // event driven: re-check when the owner releases a button/key or a move/resize ends
    struct Waiter : QObject
    {
        QTimer timeout;
        bool done = false;
    };
    auto *w = new Waiter;
    w->setParent(this);
    auto check = [this, w, busy, reply, proceed]() {
        if (w->done) {
            return;
        }
        if (!reply->alive()) {
            w->done = true;
            w->deleteLater();
            return;
        }
        if (busy()) {
            return;
        }
        w->done = true;
        w->deleteLater();
        // defer: the owner's event is still being processed by KWin
        QTimer::singleShot(0, this, proceed);
    };
    connect(input(), &InputRedirection::pointerButtonStateChanged, w, check);
    connect(input(), &InputRedirection::keyStateChanged, w, check);
    connect(workspace(), &Workspace::windowActivated, w, check);
    connect(waylandServer()->seat(), &SeatInterface::dragEnded, w, check);
    if (Window *mr = workspace()->moveResizeWindow()) {
        connect(mr, &Window::interactiveMoveResizeFinished, w, [check]() {
            QTimer::singleShot(0, check);
        });
    }
    w->timeout.setSingleShot(true);
    connect(&w->timeout, &QTimer::timeout, w, [w, reply, keyboard]() {
        if (w->done) {
            return;
        }
        w->done = true;
        w->deleteLater();
        reply->fail(Err::Busy, keyboard ? QStringLiteral("the owner is holding a key") : QStringLiteral("the owner is using the pointer"));
    });
    w->timeout.start(kOwnerWaitMs);
}

// ------------------------------------------------------------------------------------ targeting

PointTarget Agent::resolve(const QPointF &pos) const
{
    PointTarget t;
    const bool locked = waylandServer()->isScreenLocked();
    const QList<Window *> &stacking = workspace()->stackingOrder();
    for (auto it = stacking.crbegin(); it != stacking.crend(); ++it) {
        Window *w = *it;
        if (w->isDeleted() || !w->isOnCurrentActivity() || !w->isOnCurrentDesktop() || w->isMinimized() || w->isHidden()
            || w->isHiddenByShowDesktop() || !w->readyForPainting()) {
            continue;
        }
        if (locked && !w->isLockScreen()) {
            continue;
        }
        // the assistant never clicks its own overlay (its cursor, glow, panel): look through it
        if (m_scopes->isAssistantOverlay(w) || m_scopes->isBridgeInternal(w)) {
            continue;
        }
        if (!w->hitTest(pos)) {
            continue;
        }
        t.window = w;
        if (w->isInternal()) {
            t.internal = true;
        } else if (w->isDecorated() && w->decoration() && !w->clientGeometry().contains(pos)) {
            t.decoration = true;
        } else {
            t.surface = w->surface();
        }
        return t;
    }
    return t;
}

QJsonObject Agent::targetJson(const PointTarget &t) const
{
    Window *w = t.window.data();
    QJsonObject target;
    if (w && m_windows->tracked(w)) {
        target.insert(QStringLiteral("windowId"), WindowModel::idOf(w));
        const QJsonObject s = m_windows->serialize(w);
        target.insert(QStringLiteral("appId"), s.value(QStringLiteral("appId")));
        if (s.contains(QStringLiteral("namespace"))) {
            target.insert(QStringLiteral("namespace"), s.value(QStringLiteral("namespace")));
        }
    } else {
        target.insert(QStringLiteral("windowId"), QJsonValue());
        target.insert(QStringLiteral("appId"), w ? w->resourceClass() : QString());
    }
    if (t.decoration) {
        target.insert(QStringLiteral("decoration"), true);
    }
    return QJsonObject{{QStringLiteral("target"), target}};
}

void Agent::broadcastPointer(const QJsonObject &data)
{
    m_server->broadcast(QStringLiteral("agent"), QStringLiteral("agent.pointer"), data);
}

std::chrono::microseconds Agent::nextTimestamp()
{
    // monotonic and strictly increasing, close to "now" (clients use these for double-click timing)
    // Wayland event times are milliseconds; toolkits (Qt) only recognise multi-clicks when the
    // times strictly increase, so successive agent events are at least 1 ms apart
    auto now = std::chrono::duration_cast<std::chrono::milliseconds>(monotonicNow());
    const auto last = std::chrono::duration_cast<std::chrono::milliseconds>(m_lastTimestamp);
    if (now <= last) {
        now = last + 1ms;
    }
    m_lastTimestamp = now;
    return now;
}

// ------------------------------------------------------------------------------------ seat primitives

void Agent::enterTarget(const PointTarget &t, const QPointF &pos)
{
    SeatInterface *seat = waylandServer()->seat();
    qCDebug(KRISTALL_BRIDGE) << "enterTarget" << t.window << t.surface << pos << "seat focus" << seat->focusedPointerSurface();
    seat->setTimestamp(nextTimestamp());
    if (seat->focusedPointerSurface() == t.surface && t.surface) {
        seat->setFocusedPointerSurfaceTransformation(t.window->inputTransformation());
        seat->notifyPointerMotion(pos);
    } else {
        seat->notifyPointerEnter(t.surface, pos, t.window->inputTransformation());
    }
}

// Hands the seat's pointer focus back to whatever is under the owner's pointer, exactly as KWin's
// pointer redirection set it up, at the owner's position. Clients see this in the same batch.
void Agent::restoreOwnerFocus()
{
    SeatInterface *seat = waylandServer()->seat();
    PointerInputRedirection *ptr = input()->pointer();
    const QPointF ownerPos = ptr->pos();
    qCDebug(KRISTALL_BRIDGE) << "restoreOwnerFocus" << ptr->focus() << ownerPos << "seat focus" << seat->focusedPointerSurface();
    seat->setTimestamp(nextTimestamp());
    Window *f = ptr->focus();
    if (f && f->surface() && !seat->isDragPointer()) {
        if (seat->focusedPointerSurface() == f->surface()) {
            seat->setFocusedPointerSurfaceTransformation(f->inputTransformation());
            seat->notifyPointerMotion(ownerPos);
        } else {
            seat->notifyPointerEnter(f->surface(), ownerPos, f->inputTransformation());
        }
    } else if (seat->focusedPointerSurface()) {
        seat->notifyPointerLeave();
    }
    seat->notifyPointerFrame();
}

void Agent::sendButton(quint32 button, bool pressed)
{
    SeatInterface *seat = waylandServer()->seat();
    qCDebug(KRISTALL_BRIDGE) << "button" << button << pressed << "to" << seat->focusedPointerSurface();
    seat->setTimestamp(nextTimestamp());
    seat->notifyPointerButton(button, pressed ? PointerButtonState::Pressed : PointerButtonState::Released);
    seat->notifyPointerFrame();
}

// Clears the seat's record of an agent-held button without delivering a release to anyone.
void Agent::releaseButtonSilently(quint32 button)
{
    SeatInterface *seat = waylandServer()->seat();
    if (!seat->isPointerButtonPressed(button)) {
        return;
    }
    if (seat->focusedPointerSurface()) {
        seat->notifyPointerLeave();
    }
    seat->notifyPointerButton(button, PointerButtonState::Released);
    restoreOwnerFocus();
}

void Agent::sendModifiers(const PointTarget &t, const QStringList &mods)
{
    if (mods.isEmpty() || !t.surface) {
        return;
    }
    Xkb *xkb = input()->keyboard()->xkb();
    if (!xkb->state()) {
        return;
    }
    const xkb_mod_mask_t locked = xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_LOCKED);
    waylandServer()->seat()->keyboard()->sendModifiers(modifierMask(mods), 0, locked, xkb->currentLayout(), t.surface->client());
}

void Agent::restoreModifiers(const PointTarget &t)
{
    if (!t.surface) {
        return;
    }
    Xkb *xkb = input()->keyboard()->xkb();
    if (!xkb->state()) {
        return;
    }
    waylandServer()->seat()->keyboard()->sendModifiers(xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_DEPRESSED),
                                                       xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_LATCHED),
                                                       xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_LOCKED),
                                                       xkb->currentLayout(), t.surface->client());
}

void Agent::decorationEvent(const PointTarget &t, int type, const QPointF &global, Qt::MouseButton button, Qt::MouseButtons buttons)
{
    Window *w = t.window.data();
    if (!w || !w->decoration()) {
        return;
    }
    const QPointF local = global - w->pos();
    if (type == QEvent::HoverMove) {
        QHoverEvent e(QEvent::HoverMove, local, global, local);
        QCoreApplication::sendEvent(w->decoration(), &e);
    } else {
        QMouseEvent e(QEvent::Type(type), local, global, button, buttons, Qt::NoModifier);
        e.setTimestamp(quint64(std::chrono::duration_cast<std::chrono::milliseconds>(nextTimestamp()).count()));
        e.setAccepted(false);
        QCoreApplication::sendEvent(w->decoration(), &e);
        w->setProperty("kristallDecoAccepted", e.isAccepted());
    }
}

// The decoration's hover state goes back to what the owner's pointer implies.
void Agent::decorationRestore(const PointTarget &t)
{
    Window *w = t.window.data();
    if (!w || !w->decoration()) {
        return;
    }
    PointerInputRedirection *ptr = input()->pointer();
    if (ptr->decoration() && ptr->decoration() == w->decoratedWindow()) {
        const QPointF local = ptr->pos() - w->pos();
        QHoverEvent e(QEvent::HoverMove, local, ptr->pos(), local);
        QCoreApplication::sendEvent(w->decoration(), &e);
    } else {
        QHoverEvent e(QEvent::HoverLeave, QPointF(-1, -1), QPointF(-1, -1), QPointF());
        QCoreApplication::sendEvent(w->decoration(), &e);
    }
}

// KWin semantics: a press outside the open grabbing popup(s) closes them and is swallowed.
bool Agent::dismissPopupsFor(const PointTarget &t)
{
    QList<Window *> popups;
    for (Window *w : workspace()->windows()) {
        if (!w->isDeleted() && w->hasPopupGrab()) {
            popups << w;
        }
    }
    if (popups.isEmpty()) {
        return false;
    }
    Window *last = popups.constLast();
    Window *hit = t.window.data();
    const bool outside = !hit || !Window::belongToSameApplication(hit, last) || t.decoration;
    if (!outside) {
        return false;
    }
    for (auto it = popups.crbegin(); it != popups.crend(); ++it) {
        (*it)->popupDone();
    }
    return true;
}

// Click-to-focus as KWin applies it to a real press: an inactive window is activated and raised
// (default "Activate, raise and pass click"). Returns true if the command consumed the click.
bool Agent::activateOnPress(const PointTarget &t, Qt::MouseButton button, const QPointF &pos)
{
    Window *w = t.window.data();
    if (!w || !w->isClient() || w->isDeleted()) {
        return false;
    }
    if (const auto command = w->getMousePressCommand(button)) {
        return w->performMousePressCommand(*command, pos);
    }
    return false;
}

// ------------------------------------------------------------------------------------ actions

void Agent::clickAt(const PointTarget &t, const QPointF &pos, quint32 button, Qt::MouseButton qtButton, int count, const QStringList &mods, QJsonObject &extra)
{
    if (dismissPopupsFor(t)) {
        extra.insert(QStringLiteral("dismissedPopups"), true);
        return;
    }
    if (t.decoration) {
        Window *w = t.window.data();
        decorationEvent(t, QEvent::HoverMove, pos, Qt::NoButton, Qt::NoButton);
        for (int i = 0; i < count && t.window; ++i) {
            decorationEvent(t, QEvent::MouseButtonPress, pos, qtButton, qtButton);
            const bool accepted = t.window && t.window->property("kristallDecoAccepted").toBool();
            if (!accepted && t.window) {
                // title bar: the window-manager commands a real click would trigger
                if (i == 1 && qtButton == Qt::LeftButton) {
                    workspace()->performWindowOperation(w, options->operationTitlebarDblClick());
                } else if (i == 0) {
                    const bool active = w->isActive();
                    Options::MouseCommand cmd = active ? options->commandActiveTitlebar1() : options->commandInactiveTitlebar1();
                    if (qtButton == Qt::MiddleButton) {
                        cmd = active ? options->commandActiveTitlebar2() : options->commandInactiveTitlebar2();
                    } else if (qtButton == Qt::RightButton) {
                        cmd = active ? options->commandActiveTitlebar3() : options->commandInactiveTitlebar3();
                    }
                    if (cmd == Options::MouseOperationsMenu) {
                        extra.insert(QStringLiteral("note"), QStringLiteral("window operations menu is not operable by the agent"));
                    } else {
                        w->performMousePressCommand(cmd, pos);
                    }
                }
            }
            if (t.window) {
                decorationEvent(t, QEvent::MouseButtonRelease, pos, qtButton, Qt::NoButton);
            }
        }
        if (t.window) {
            decorationRestore(t);
        }
        return;
    }
    if (activateOnPress(t, qtButton, pos)) {
        qCDebug(KRISTALL_BRIDGE) << "click consumed by window command";
        return; // the window-manager command consumed the click
    }
    if (!t.surface || !t.window) {
        qCDebug(KRISTALL_BRIDGE) << "click target vanished during activation";
        return;
    }
    enterTarget(t, pos);
    sendModifiers(t, mods);
    waylandServer()->seat()->notifyPointerFrame();
    for (int i = 0; i < count && t.surface; ++i) {
        sendButton(button, true);
        sendButton(button, false);
    }
    restoreModifiers(t);
    restoreOwnerFocus();
    releaseCommand(t, qtButton, pos);
}

// KWin's default click-to-focus raises an inactive window on release ("Activate, raise on
// release and pass click"), so a drag that starts in a background window does not raise it.
void Agent::releaseCommand(const PointTarget &t, Qt::MouseButton button, const QPointF &pos)
{
    Window *w = t.window.data();
    if (!w || !w->isClient() || w->isDeleted()) {
        return;
    }
    if (const auto command = w->getMouseReleaseCommand(button)) {
        w->performMouseReleaseCommand(*command, pos);
    }
}

void Agent::scrollAt(const PointTarget &t, const QPointF &pos, double dx, double dy, const QStringList &mods)
{
    if (t.decoration || !t.surface || !t.window) {
        return;
    }
    SeatInterface *seat = waylandServer()->seat();
    enterTarget(t, pos);
    sendModifiers(t, mods);
    seat->notifyPointerFrame();
    // one notch = 15 (KWin's wheel unit) and 120 in high-resolution units
    auto axis = [&](Qt::Orientation o, double notches) {
        if (notches == 0) {
            return;
        }
        seat->setTimestamp(nextTimestamp());
        seat->notifyPointerAxis(o, notches * 15.0, qint32(std::lround(notches * 120.0)), PointerAxisSource::Wheel);
    };
    axis(Qt::Vertical, dy);
    axis(Qt::Horizontal, dx);
    seat->notifyPointerFrame();
    restoreModifiers(t);
    restoreOwnerFocus();
}

bool Agent::startHold(const PointTarget &t, const QPointF &pos, quint32 button, Qt::MouseButton qtButton, const QStringList &mods, QString *error)
{
    if (dismissPopupsFor(t)) {
        *error = QStringLiteral("a press outside an open menu closed the menu");
        return false;
    }
    Window *w = t.window.data();
    if (!w) {
        *error = QStringLiteral("nothing at this point");
        return false;
    }
    Hold h;
    h.target = t;
    h.button = button;
    h.qtButton = qtButton;
    h.pos = pos;
    h.pressPos = pos;
    h.startGeometry = w->frameGeometry();
    if (t.decoration) {
        decorationEvent(t, QEvent::HoverMove, pos, Qt::NoButton, Qt::NoButton);
        decorationEvent(t, QEvent::MouseButtonPress, pos, qtButton, qtButton);
        if (!w->property("kristallDecoAccepted").toBool()) {
            // title bar (or border): the agent moves the window itself; the real pointer is not involved
            const bool active = w->isActive();
            const Options::MouseCommand cmd = active ? options->commandActiveTitlebar1() : options->commandInactiveTitlebar1();
            if (qtButton == Qt::LeftButton && cmd != Options::MouseOperationsMenu) {
                w->performMousePressCommand(cmd, pos);
            }
            h.manualMove = qtButton == Qt::LeftButton && w->isMovable();
        }
        m_hold = h;
        return true;
    }
    if (!t.surface) {
        *error = QStringLiteral("this surface cannot receive agent input");
        return false;
    }
    if (activateOnPress(t, qtButton, pos)) {
        *error = QStringLiteral("the press was consumed by a window-manager action");
        return false;
    }
    enterTarget(t, pos);
    sendModifiers(t, mods);
    waylandServer()->seat()->notifyPointerFrame();
    sendButton(button, true);
    h.pressSerial = waylandServer()->seat()->pointerButtonSerial(button);
    m_hold = h;
    // A client may answer the press by asking for an interactive move/resize (client-side
    // decorations) or a drag-and-drop. KWin would bind those to the owner's pointer; the agent
    // takes them over instead.
    m_holdConnections << connect(w, &Window::interactiveMoveResizeStarted, this, [this, w]() {
        QMetaObject::invokeMethod(this, [this, w = QPointer<Window>(w)]() {
            if (w) {
                onInteractiveMoveResizeStarted(w);
            }
        }, Qt::QueuedConnection);
    });
    m_holdConnections << connect(waylandServer()->seat(), &SeatInterface::dragStarted, this, [this]() {
        if (m_hold && waylandServer()->seat()->dragSerial() == m_hold->pressSerial) {
            m_hold->dnd = true;
        }
    });
    // keep the target focused for the rest of the gesture; the owner's surface gets it back at release
    return true;
}

void Agent::onInteractiveMoveResizeStarted(Window *w)
{
    if (!m_hold || m_hold->target.window != w || !(w->isInteractiveMove() || w->isInteractiveResize())) {
        return;
    }
    const bool resize = w->isInteractiveResize();
    m_hold->resizeGravity = int(Gravity::Kind(w->interactiveMoveResizeGravity()));
    w->cancelInteractiveMoveResize();
    m_hold->startGeometry = w->frameGeometry();
    m_hold->pressPos = m_hold->pos;
    m_hold->manualMove = !resize;
    m_hold->manualResize = resize;
    // KWin cleared the seat's pointer focus when the move started; the client already saw a leave
}

void Agent::holdMotion(const QPointF &pos)
{
    if (!m_hold) {
        return;
    }
    Hold &h = *m_hold;
    h.pos = pos;
    Window *w = h.target.window.data();
    if (!w) {
        return;
    }
    SeatInterface *seat = waylandServer()->seat();
    if (h.manualMove || h.manualResize) {
        const QPointF d = pos - h.pressPos;
        if (h.manualMove) {
            if (w->maximizeMode() != MaximizeRestore && d.manhattanLength() > 4) {
                w->maximize(MaximizeRestore);
                h.startGeometry = QRectF(h.pressPos.x() - w->width() / 2, h.startGeometry.y(), w->width(), w->height());
            }
            w->move(h.startGeometry.topLeft() + d);
        } else {
            QRectF g = h.startGeometry;
            const Gravity::Kind gravity = Gravity::Kind(h.resizeGravity);
            if (gravity == Gravity::Left || gravity == Gravity::TopLeft || gravity == Gravity::BottomLeft) {
                g.setLeft(std::min(g.left() + d.x(), g.right() - 1));
            }
            if (gravity == Gravity::Right || gravity == Gravity::TopRight || gravity == Gravity::BottomRight) {
                g.setRight(std::max(g.right() + d.x(), g.left() + 1));
            }
            if (gravity == Gravity::Top || gravity == Gravity::TopLeft || gravity == Gravity::TopRight) {
                g.setTop(std::min(g.top() + d.y(), g.bottom() - 1));
            }
            if (gravity == Gravity::Bottom || gravity == Gravity::BottomLeft || gravity == Gravity::BottomRight) {
                g.setBottom(std::max(g.bottom() + d.y(), g.top() + 1));
            }
            w->moveResize(g);
        }
        return;
    }
    if (h.target.decoration) {
        decorationEvent(h.target, QEvent::MouseMove, pos, Qt::NoButton, h.qtButton);
        return;
    }
    if (h.dnd && seat->isDragPointer()) {
        const PointTarget over = resolve(pos);
        seat->setTimestamp(nextTimestamp());
        if (over.window && over.surface) {
            seat->setDragTarget(seat->dropHandlerForSurface(over.surface), over.surface, pos, over.window->inputTransformation());
        } else {
            seat->setDragTarget(nullptr, nullptr, pos, QMatrix4x4());
        }
        seat->notifyDragMotion(pos);
        return;
    }
    if (seat->focusedPointerSurface() != h.target.surface) {
        return; // the target lost focus (destroyed or a grab elsewhere)
    }
    // implicit grab: motion goes to the pressed surface even outside it
    seat->setTimestamp(nextTimestamp());
    seat->notifyPointerMotion(pos);
    seat->notifyPointerFrame();
}

void Agent::finishHold(bool interrupted, const QString &why)
{
    if (!m_hold) {
        return;
    }
    Hold h = *m_hold;
    m_hold.reset();
    m_dragTimer.stop();
    for (const auto &c : std::as_const(m_holdConnections)) {
        disconnect(c);
    }
    m_holdConnections.clear();
    SeatInterface *seat = waylandServer()->seat();
    Window *w = h.target.window.data();
    if (h.target.decoration) {
        if (w) {
            decorationEvent(h.target, QEvent::MouseButtonRelease, h.pos, h.qtButton, Qt::NoButton);
            decorationRestore(h.target);
        }
    } else if (h.dnd && seat->isDragPointer()) {
        if (interrupted) {
            seat->cancelDrag();
            releaseButtonSilently(h.button);
        } else {
            seat->setTimestamp(nextTimestamp());
            seat->notifyPointerButton(h.button, PointerButtonState::Released); // drops on the current target
            seat->notifyPointerFrame();
            restoreOwnerFocus();
        }
    } else if (h.target.surface && seat->focusedPointerSurface() == h.target.surface) {
        // complete the gesture where the agent is (also when interrupted: a release is the only
        // way to end a client's implicit grab cleanly)
        seat->setTimestamp(nextTimestamp());
        seat->notifyPointerMotion(h.pos);
        sendButton(h.button, false);
        restoreModifiers(h.target);
        restoreOwnerFocus();
        if (!h.manualMove && !h.manualResize) {
            releaseCommand(h.target, h.qtButton, h.pos);
        }
    } else {
        releaseButtonSilently(h.button);
        restoreModifiers(h.target);
    }
    if (h.pendingReply) {
        if (interrupted) {
            h.pendingReply->fail(Err::Busy, why.isEmpty() ? QStringLiteral("interrupted") : why);
        } else {
            h.pendingReply->ok(targetJson(h.target));
        }
    }
}

// ------------------------------------------------------------------------------------ methods

void Agent::registerMethods()
{
    m_server->registerMethod(QStringLiteral("agent.begin"), MethodSpec{true, QStringLiteral("agentInput"), [this](Params &p, const ReplyPtr &r) {
                                                                beginSession(p, r);
                                                            }});
    m_server->registerMethod(QStringLiteral("agent.end"), MethodSpec{true, QStringLiteral("agentInput"), [this](Params &p, const ReplyPtr &r) {
                                                              if (!checkSession(p, r)) {
                                                                  return;
                                                              }
                                                              endSession(QStringLiteral("ended"));
                                                              r->ok();
                                                          }});
    m_server->registerMethod(QStringLiteral("agent.pointer"), MethodSpec{true, QStringLiteral("agentInput"), [this](Params &p, const ReplyPtr &r) {
                                                                  pointer(p, r);
                                                              }});
    m_server->registerMethod(QStringLiteral("agent.drag"), MethodSpec{true, QStringLiteral("agentInput"), [this](Params &p, const ReplyPtr &r) {
                                                               drag(p, r);
                                                           }});
    m_keyboard->registerMethods();

    if (m_server->devMode()) {
        m_server->registerMethod(QStringLiteral("debug.trace"), MethodSpec{false, QString(), [this](Params &p, const ReplyPtr &r) {
                                                                    const auto enable = p.boolean(QStringLiteral("enable"), false, true);
                                                                    if (!enable) {
                                                                        return;
                                                                    }
                                                                    QJsonArray frames;
                                                                    for (const QJsonObject &f : std::as_const(debug.frames)) {
                                                                        frames.append(f);
                                                                    }
                                                                    QJsonObject out{
                                                                        {QStringLiteral("cursorMovesDuringAgent"), double(debug.cursorMovesDuringAgent)},
                                                                        {QStringLiteral("agentCalls"), double(debug.agentCalls)},
                                                                        {QStringLiteral("framesDuringAgent"), double(debug.framesDuringAgent)},
                                                                        {QStringLiteral("frames"), frames},
                                                                        {QStringLiteral("serverRequests"), double(m_server->stats.requests)},
                                                                        {QStringLiteral("serverInvalid"), double(m_server->stats.invalid)},
                                                                        {QStringLiteral("serverDenied"), double(m_server->stats.denied)},
                                                                        {QStringLiteral("serverDropped"), double(m_server->stats.dropped)},
                                                                    };
                                                                    out.insert(QStringLiteral("loopWorstLatenessMs"), debug.loopWorstMs);
                                                                    out.insert(QStringLiteral("loopTicks"), double(debug.loopTicks));
                                                                    debug.frames.clear();
                                                                    debug.tracing = *enable;
                                                                    // event-loop lateness probe: a 2 ms timer measuring how late it fires
                                                                    debug.loopWorstMs = 0;
                                                                    debug.loopTicks = 0;
                                                                    if (*enable) {
                                                                        debug.loopClock.start();
                                                                        m_loopTimer.start(2);
                                                                    } else {
                                                                        m_loopTimer.stop();
                                                                    }
                                                                    r->ok(out);
                                                                }});
    }
}

void Agent::pointer(Params &p, const ReplyPtr &reply)
{
    if (!checkSession(p, reply)) {
        return;
    }
    const auto type = p.string(QStringLiteral("type"), true, 16);
    const auto buttonName = p.string(QStringLiteral("button"), false, 16, QStringLiteral("left"));
    const auto count = p.integer(QStringLiteral("count"), false, 1, 3, 1);
    const auto dx = p.number(QStringLiteral("dx"), false, -100, 100, 0);
    const auto dy = p.number(QStringLiteral("dy"), false, -100, 100, 0);
    const auto mods = p.stringList(QStringLiteral("modifiers"), false, 4, 8);
    const auto windowId = p.string(QStringLiteral("windowId"), false, 64);
    const auto hoverMs = p.integer(QStringLiteral("hoverMs"), false, 0, 5000, 0);
    if (!type || !buttonName || !count || !dx || !dy || !mods || !windowId || !hoverMs) {
        return;
    }
    static const QSet<QString> types = {QStringLiteral("move"), QStringLiteral("click"), QStringLiteral("down"), QStringLiteral("up"), QStringLiteral("scroll")};
    if (!types.contains(*type)) {
        reply->fail(Err::Invalid, QStringLiteral("'type' must be move, click, down, up or scroll"));
        return;
    }
    quint32 button = 0;
    Qt::MouseButton qtButton = Qt::NoButton;
    if (!parseButton(*buttonName, &button, &qtButton)) {
        reply->fail(Err::Invalid, QStringLiteral("'button' must be left, right, middle, back or forward"));
        return;
    }
    if (!validModifiers(*mods)) {
        reply->fail(Err::Invalid, QStringLiteral("'modifiers' may contain ctrl, shift, alt, meta"));
        return;
    }
    const bool needsPos = *type != QLatin1String("up");
    const auto x = p.number(QStringLiteral("x"), needsPos, -kCoordLimit, kCoordLimit, m_hold ? m_hold->pos.x() : 0);
    const auto y = p.number(QStringLiteral("y"), needsPos, -kCoordLimit, kCoordLimit, m_hold ? m_hold->pos.y() : 0);
    if (!x || !y) {
        return;
    }
    const QPointF pos(*x, *y);
    const QString t = *type;
    const QString wid = *windowId;
    const QStringList modifiers = *mods;
    const int clicks = *count;
    const double sdx = *dx, sdy = *dy;
    const int hover = *hoverMs;

    // a gesture the agent holds continues regardless of the owner's state
    if (m_hold && (t == QLatin1String("move") || t == QLatin1String("up"))) {
        if (m_hold->pendingReply) {
            reply->fail(Err::Busy, QStringLiteral("a drag is in progress"));
            return;
        }
        if (t == QLatin1String("up") && m_hold->button != button) {
            reply->fail(Err::Invalid, QStringLiteral("a different button is held"));
            return;
        }
        broadcastPointer(QJsonObject{{QStringLiteral("x"), pos.x()}, {QStringLiteral("y"), pos.y()}, {QStringLiteral("type"), t}, {QStringLiteral("button"), *buttonName}});
        debug.agentCalls++;
        m_inCall++;
        const QJsonObject target = targetJson(m_hold->target);
        holdMotion(pos);
        if (t == QLatin1String("up")) {
            finishHold(false);
        }
        m_inCall--;
        reply->ok(target);
        return;
    }
    if (t == QLatin1String("up")) {
        reply->fail(Err::Invalid, QStringLiteral("no button is held"));
        return;
    }
    if (m_hold) {
        reply->fail(Err::Busy, QStringLiteral("a button is held; send 'up' first"));
        return;
    }
    if (m_hoverTimer.isActive()) {
        reply->fail(Err::Busy, QStringLiteral("a hover is in progress"));
        return;
    }

    whenOwnerIdle(false, reply, [this, reply, t, pos, wid, button, qtButton, clicks, sdx, sdy, modifiers, hover, buttonName = *buttonName]() {
        if (!reply->alive() || !sessionActive()) {
            reply->fail(Err::Denied, QStringLiteral("the agent session ended"));
            return;
        }
        if (waylandServer()->isScreenLocked()) {
            reply->fail(Err::Denied, QStringLiteral("the screen is locked"));
            return;
        }
        if (effects && effects->isMouseInterception()) {
            reply->fail(Err::Busy, QStringLiteral("a full-screen effect (e.g. the overview) has the pointer"));
            return;
        }
        PointTarget target = resolve(pos);
        if (!wid.isEmpty()) {
            Window *want = m_windows->find(wid);
            if (!want) {
                reply->fail(Err::NotFound, QStringLiteral("no window with id '%1'").arg(wid));
                return;
            }
            auto belongs = [want](Window *hit) {
                return hit && (hit == want || hit->transientFor() == want || (hit->isPopupWindow() && Window::belongToSameApplication(hit, want)));
            };
            if (!belongs(target.window.data())) {
                // the window is covered at this point: raise it, as a click on it would
                workspace()->activateWindow(want, true);
                workspace()->raiseWindow(want);
                target = resolve(pos);
                if (!belongs(target.window.data())) {
                    reply->fail(Err::NotFound, QStringLiteral("the point is not inside window '%1'").arg(wid));
                    return;
                }
            }
        }
        if (target.internal) {
            reply->fail(Err::Unsupported, QStringLiteral("compositor-internal windows cannot receive agent input"));
            return;
        }
        broadcastPointer(QJsonObject{{QStringLiteral("x"), pos.x()}, {QStringLiteral("y"), pos.y()}, {QStringLiteral("type"), t}, {QStringLiteral("button"), buttonName}});
        debug.agentCalls++;
        m_inCall++;
        QJsonObject result = targetJson(target);
        QJsonObject extra;
        if (t == QLatin1String("click")) {
            clickAt(target, pos, button, qtButton, clicks, modifiers, extra);
        } else if (t == QLatin1String("scroll")) {
            scrollAt(target, pos, sdx, sdy, modifiers);
        } else if (t == QLatin1String("down")) {
            QString error;
            if (!startHold(target, pos, button, qtButton, modifiers, &error)) {
                m_inCall--;
                reply->fail(Err::Busy, error);
                return;
            }
        } else if (t == QLatin1String("move")) {
            if (target.surface) {
                enterTarget(target, pos);
                waylandServer()->seat()->notifyPointerFrame();
            } else if (target.decoration) {
                decorationEvent(target, QEvent::HoverMove, pos, Qt::NoButton, Qt::NoButton);
            }
            if (hover > 0) {
                // keep hovering (tooltips, hover menus) until hoverMs or owner pointer activity
                m_inCall--;
                m_hoverFinish = [this, reply, result, target]() {
                    if (target.decoration) {
                        decorationRestore(target);
                    } else {
                        restoreOwnerFocus();
                    }
                    reply->ok(result);
                };
                m_hoverTimer.start(hover);
                return;
            }
            if (target.decoration) {
                decorationRestore(target);
            } else {
                restoreOwnerFocus();
            }
        }
        m_inCall--;
        for (auto it = extra.constBegin(); it != extra.constEnd(); ++it) {
            result.insert(it.key(), it.value());
        }
        reply->ok(result);
    });
}

void Agent::drag(Params &p, const ReplyPtr &reply)
{
    if (!checkSession(p, reply)) {
        return;
    }
    const auto from = p.object(QStringLiteral("from"), true);
    const auto to = p.object(QStringLiteral("to"), true);
    const auto buttonName = p.string(QStringLiteral("button"), false, 16, QStringLiteral("left"));
    const auto duration = p.integer(QStringLiteral("durationMs"), false, 0, 10000, 300);
    const auto mods = p.stringList(QStringLiteral("modifiers"), false, 4, 8);
    if (!from || !to || !buttonName || !duration || !mods) {
        return;
    }
    Params pf(*from), pt(*to);
    const auto fx = pf.number(QStringLiteral("x"), true, -kCoordLimit, kCoordLimit);
    const auto fy = pf.number(QStringLiteral("y"), true, -kCoordLimit, kCoordLimit);
    const auto tx = pt.number(QStringLiteral("x"), true, -kCoordLimit, kCoordLimit);
    const auto ty = pt.number(QStringLiteral("y"), true, -kCoordLimit, kCoordLimit);
    if (!fx || !fy || !tx || !ty) {
        reply->fail(Err::Invalid, QStringLiteral("'from' and 'to' need numeric x and y"));
        return;
    }
    quint32 button = 0;
    Qt::MouseButton qtButton = Qt::NoButton;
    if (!parseButton(*buttonName, &button, &qtButton)) {
        reply->fail(Err::Invalid, QStringLiteral("'button' must be left, right, middle, back or forward"));
        return;
    }
    if (!validModifiers(*mods)) {
        reply->fail(Err::Invalid, QStringLiteral("'modifiers' may contain ctrl, shift, alt, meta"));
        return;
    }
    if (m_hold) {
        reply->fail(Err::Busy, QStringLiteral("a button is already held"));
        return;
    }
    const QPointF a(*fx, *fy), b(*tx, *ty);
    const int durationMs = *duration;
    const QStringList modifiers = *mods;
    whenOwnerIdle(false, reply, [this, reply, a, b, durationMs, button, qtButton, modifiers, buttonName = *buttonName]() {
        if (!reply->alive() || !sessionActive()) {
            reply->fail(Err::Denied, QStringLiteral("the agent session ended"));
            return;
        }
        if (waylandServer()->isScreenLocked()) {
            reply->fail(Err::Denied, QStringLiteral("the screen is locked"));
            return;
        }
        if (effects && effects->isMouseInterception()) {
            reply->fail(Err::Busy, QStringLiteral("a full-screen effect (e.g. the overview) has the pointer"));
            return;
        }
        if (m_hold) {
            reply->fail(Err::Busy, QStringLiteral("a button is already held"));
            return;
        }
        const PointTarget target = resolve(a);
        if (target.internal) {
            reply->fail(Err::Unsupported, QStringLiteral("compositor-internal windows cannot receive agent input"));
            return;
        }
        broadcastPointer(QJsonObject{{QStringLiteral("x"), a.x()}, {QStringLiteral("y"), a.y()}, {QStringLiteral("type"), QStringLiteral("down")}, {QStringLiteral("button"), buttonName}});
        debug.agentCalls++;
        QString error;
        if (!startHold(target, a, button, qtButton, modifiers, &error)) {
            reply->fail(Err::Busy, error);
            return;
        }
        m_hold->pendingReply = reply;
        // interpolate at the frame rate of a typical panel; the last step lands exactly on `to`
        const int steps = std::max(1, durationMs / 16);
        auto step = std::make_shared<int>(0);
        auto tick = std::make_shared<std::function<void()>>();
        *tick = [this, step, steps, a, b, durationMs, tick, buttonName]() {
            if (!m_hold || !m_hold->pendingReply) {
                return;
            }
            ++*step;
            const double f = double(*step) / steps;
            const QPointF pos = a + (b - a) * f;
            m_inCall++;
            holdMotion(pos);
            m_inCall--;
            if (*step >= steps) {
                broadcastPointer(QJsonObject{{QStringLiteral("x"), b.x()}, {QStringLiteral("y"), b.y()}, {QStringLiteral("type"), QStringLiteral("up")}, {QStringLiteral("button"), buttonName}});
                finishHold(false);
                return;
            }
            m_dragTimer.start(std::max(1, durationMs / steps));
        };
        disconnect(&m_dragTimer, &QTimer::timeout, this, nullptr);
        connect(&m_dragTimer, &QTimer::timeout, this, [tick]() {
            (*tick)();
        });
        if (durationMs == 0) {
            (*tick)();
        } else {
            m_dragTimer.start(std::max(1, durationMs / steps));
        }
    });
}

} // namespace Kristall
