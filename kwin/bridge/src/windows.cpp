/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "windows.h"
#include "helperclient.h"
#include "server.h"

#include "core/output.h"
#include "cursor.h"
#include "effect/effect.h"
#include "effect/effecthandler.h"
#include "virtualdesktops.h"
#include "wayland/clientconnection.h"
#include "wayland/layershell_v1.h"
#include "wayland/pointerconstraints_v1.h"
#include "wayland/surface.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"

#include <QAction>
#include <QIcon>
#include <QJsonArray>

#include <cmath>

using namespace KWin;

namespace Kristall
{

// ------------------------------------------------------------------------------------ LayerScopes

LayerScopes::LayerScopes(QObject *parent)
    : QObject(parent)
{
    const auto shells = waylandServer()->findChildren<LayerShellV1Interface *>();
    for (LayerShellV1Interface *shell : shells) {
        connect(shell, &LayerShellV1Interface::surfaceCreated, this, [this](LayerSurfaceV1Interface *layer) {
            SurfaceInterface *surface = layer->surface();
            m_scopes.insert(surface, layer->scope());
            connect(surface, &QObject::destroyed, this, [this, surface]() {
                m_scopes.remove(surface);
            });
        });
    }
    if (shells.isEmpty()) {
        logOnce(QStringLiteral("nolayershell"), QStringLiteral("no layer-shell global found; shell surfaces cannot be told apart"));
    }
}

QString LayerScopes::scopeOf(const Window *window) const
{
    if (!window || !window->surface()) {
        return QString();
    }
    const auto it = m_scopes.constFind(window->surface());
    return it == m_scopes.constEnd() ? QString() : it.value();
}

bool LayerScopes::isAssistantOverlay(const Window *window) const
{
    return scopeOf(window).startsWith(QLatin1String("kristall-assistant"));
}

bool LayerScopes::isBridgeInternal(const Window *window) const
{
    return scopeOf(window).startsWith(QLatin1String("kristall-bridge-"));
}

bool LayerScopes::isShell(const Window *window) const
{
    return scopeOf(window).startsWith(QLatin1String("kristall-"));
}

// ------------------------------------------------------------------------------------ helpers

static double round2(double v)
{
    return std::round(v * 100.0) / 100.0;
}

static QString typeOf(const Window *w, bool layer)
{
    if (layer) {
        return QStringLiteral("layer");
    }
    if (w->isPopupWindow() || w->isUnmanaged()) {
        if (w->isTooltip()) {
            return QStringLiteral("tooltip");
        }
        return QStringLiteral("popup");
    }
    if (w->isDesktop()) {
        return QStringLiteral("desktop");
    }
    if (w->isDock()) {
        return QStringLiteral("dock");
    }
    if (w->isDialog()) {
        return QStringLiteral("dialog");
    }
    if (w->isUtility() || w->isToolbar()) {
        return QStringLiteral("utility");
    }
    if (w->isMenu() || w->isDropdownMenu() || w->isPopupMenu() || w->isComboBox()) {
        return QStringLiteral("menu");
    }
    if (w->isTooltip()) {
        return QStringLiteral("tooltip");
    }
    if (w->isNotification() || w->isCriticalNotification()) {
        return QStringLiteral("notification");
    }
    if (w->isOnScreenDisplay()) {
        return QStringLiteral("osd");
    }
    if (w->isSplash()) {
        return QStringLiteral("splash");
    }
    if (w->isNormalWindow()) {
        return QStringLiteral("normal");
    }
    return QStringLiteral("other");
}

static bool isXwayland(const Window *w)
{
    const SurfaceInterface *s = w->surface();
    return s && waylandServer()->xWaylandConnection() && s->client() == waylandServer()->xWaylandConnection();
}

// ------------------------------------------------------------------------------------ WindowModel

WindowModel::WindowModel(Server *server, LayerScopes *scopes, QObject *parent)
    : QObject(parent)
    , m_server(server)
    , m_scopes(scopes)
{
    m_flushTimer.setSingleShot(true);
    connect(&m_flushTimer, &QTimer::timeout, this, &WindowModel::flush);

    Workspace *ws = workspace();
    connect(ws, &Workspace::windowAdded, this, [this](Window *w) {
        track(w, true);
    });
    connect(ws, &Workspace::windowRemoved, this, &WindowModel::untrack);
    connect(ws, &Workspace::windowActivated, this, [this](Window *w) {
        // KWin may activate a new window before announcing it: announce it first
        if (w && !tracked(w) && shouldTrack(w)) {
            track(w, true);
        }
        if (!m_server->hasSubscribers(QStringLiteral("active"))) {
            return;
        }
        m_server->broadcast(QStringLiteral("active"), QStringLiteral("active.changed"),
                            QJsonObject{{QStringLiteral("id"), (w && tracked(w)) ? QJsonValue(idOf(w)) : QJsonValue()}});
    });
    connect(ws, &Workspace::stackingOrderChanged, this, [this]() {
        m_stackingDirty = true;
        scheduleFlush();
    });
    auto outputsChanged = [this]() {
        for (const auto &c : std::as_const(m_outputConnections)) {
            disconnect(c);
        }
        m_outputConnections.clear();
        for (LogicalOutput *o : workspace()->outputs()) {
            m_outputConnections << connect(o, &LogicalOutput::changed, this, [this]() {
                m_outputsDirty = true;
                scheduleFlush();
            });
        }
        m_outputsDirty = true;
        scheduleFlush();
    };
    connect(ws, &Workspace::outputsChanged, this, outputsChanged);
    connect(ws, &Workspace::outputOrderChanged, this, outputsChanged);
    outputsChanged();
    m_outputsDirty = false;
    // workArea: KWin recomputes the client areas in Workspace::rearrange() (struts and layer-shell
    // exclusive zones changed, outputs changed) and has no signal for the result; aboutToRearrange
    // is emitted right before, and the flush runs in a later event-loop turn, after the
    // recomputation. outputs.changed is only sent when the data actually differs.
    auto workAreaMaybeChanged = [this]() {
        m_outputsDirty = true;
        scheduleFlush();
    };
    connect(ws, &Workspace::aboutToRearrange, this, workAreaMaybeChanged);
    connect(VirtualDesktopManager::self(), &VirtualDesktopManager::currentChanged, this, workAreaMaybeChanged);

    auto desktopsChanged = [this]() {
        m_desktopsDirty = true;
        scheduleFlush();
    };
    VirtualDesktopManager *vds = VirtualDesktopManager::self();
    connect(vds, &VirtualDesktopManager::currentChanged, this, desktopsChanged);
    connect(vds, &VirtualDesktopManager::countChanged, this, desktopsChanged);
    connect(vds, &VirtualDesktopManager::desktopAdded, this, [this, desktopsChanged](VirtualDesktop *d) {
        connect(d, &VirtualDesktop::nameChanged, this, desktopsChanged);
        desktopsChanged();
    });
    connect(vds, &VirtualDesktopManager::desktopRemoved, this, desktopsChanged);
    for (VirtualDesktop *d : vds->desktops()) {
        connect(d, &VirtualDesktop::nameChanged, this, desktopsChanged);
    }

    for (Window *w : ws->windows()) {
        track(w, false);
    }

    m_server->setSnapshotProvider(QStringLiteral("windows"), [this]() {
        // deliver pending deltas to existing subscribers first, then make the snapshot the new
        // baseline (deltas are computed against what clients were last told)
        flush();
        const QJsonArray arr = windowsArray();
        for (const QJsonValue &v : arr) {
            if (Window *w = find(v.toObject().value(QStringLiteral("id")).toString())) {
                m_lastSent[w] = v.toObject();
            }
        }
        return QList<QJsonObject>{makeEvent(QStringLiteral("windows.snapshot"), QJsonObject{{QStringLiteral("windows"), arr}})};
    });
    m_server->setSnapshotProvider(QStringLiteral("active"), [this]() {
        Window *a = workspace()->activeWindow();
        return QList<QJsonObject>{makeEvent(QStringLiteral("active.changed"),
                                            QJsonObject{{QStringLiteral("id"), (a && tracked(a)) ? QJsonValue(idOf(a)) : QJsonValue()}})};
    });
    m_server->setSnapshotProvider(QStringLiteral("stacking"), [this]() {
        return QList<QJsonObject>{makeEvent(QStringLiteral("stacking.changed"), QJsonObject{{QStringLiteral("order"), stackingArray()}})};
    });
    m_server->setSnapshotProvider(QStringLiteral("outputs"), [this]() {
        const QJsonObject now = outputsData();
        if (!m_outputsDirty) {
            m_lastOutputs = now; // otherwise the pending flush compares and tells everyone
        }
        return QList<QJsonObject>{makeEvent(QStringLiteral("outputs.changed"), now)};
    });
    m_server->setSnapshotProvider(QStringLiteral("desktops"), [this]() {
        return QList<QJsonObject>{makeEvent(QStringLiteral("desktops.changed"), desktopsData())};
    });
    registerMethods();
}

WindowModel::~WindowModel() = default;

QString WindowModel::idOf(const Window *window)
{
    return window->internalId().toString(QUuid::WithoutBraces);
}

Window *WindowModel::find(const QString &id) const
{
    const auto it = m_byId.constFind(id);
    if (it == m_byId.constEnd() || !it.value() || it.value()->isDeleted()) {
        return nullptr;
    }
    return it.value().data();
}

bool WindowModel::tracked(const Window *window) const
{
    return m_lastSent.contains(const_cast<Window *>(window));
}

bool WindowModel::shouldTrack(Window *w) const
{
    if (!w || w->isDeleted() || w->isInternal() || w->isLockScreen() || w->isInputMethod() || w->isOutline() || w->isDNDIcon()) {
        return false;
    }
    if (m_scopes->isBridgeInternal(w)) {
        return false;
    }
    return true;
}

void WindowModel::track(Window *w, bool announce)
{
    if (!shouldTrack(w) || m_lastSent.contains(w)) {
        return;
    }
    const QString id = idOf(w);
    m_byId.insert(id, w);
    QList<QMetaObject::Connection> cons;
    auto dirty = [this, w]() {
        markDirty(w);
    };
    cons << connect(w, &Window::captionChanged, this, dirty);
    cons << connect(w, &Window::frameGeometryChanged, this, dirty);
    cons << connect(w, &Window::outputChanged, this, dirty);
    cons << connect(w, &Window::desktopsChanged, this, dirty);
    cons << connect(w, &Window::activeChanged, this, dirty);
    cons << connect(w, &Window::minimizedChanged, this, dirty);
    cons << connect(w, &Window::maximizedChanged, this, dirty);
    cons << connect(w, &Window::fullScreenChanged, this, dirty);
    cons << connect(w, &Window::keepAboveChanged, this, dirty);
    cons << connect(w, &Window::demandsAttentionChanged, this, dirty);
    cons << connect(w, &Window::skipTaskbarChanged, this, dirty);
    cons << connect(w, &Window::skipSwitcherChanged, this, dirty);
    cons << connect(w, &Window::closeableChanged, this, dirty);
    cons << connect(w, &Window::minimizeableChanged, this, dirty);
    cons << connect(w, &Window::maximizeableChanged, this, dirty);
    cons << connect(w, &Window::iconChanged, this, dirty);
    cons << connect(w, &Window::applicationMenuChanged, this, dirty);
    cons << connect(w, &Window::desktopFileNameChanged, this, dirty);
    cons << connect(w, &Window::windowClassChanged, this, dirty);
    cons << connect(w, &Window::transientChanged, this, dirty);
    cons << connect(w, &Window::hiddenChanged, this, dirty);
    cons << connect(w, &Window::closed, this, [this, w]() {
        untrack(w);
    });
    // pointer lock/confinement of the window's surface (games): watched on the current surface
    cons << connect(w, &Window::surfaceChanged, this, [this, w]() {
        watchConstraints(w);
        markDirty(w);
    });
    m_connections.insert(w, cons);
    watchConstraints(w);
    const QJsonObject obj = serialize(w);
    m_lastSent.insert(w, obj);
    if (announce) {
        m_server->broadcast(QStringLiteral("windows"), QStringLiteral("window.added"), QJsonObject{{QStringLiteral("window"), obj}});
        m_stackingDirty = true;
        scheduleFlush();
    }
}

void WindowModel::untrack(Window *w)
{
    if (!m_lastSent.contains(w)) {
        return;
    }
    const QString id = m_lastSent.value(w).value(QStringLiteral("id")).toString();
    for (const auto &c : m_constraintConnections.take(w)) {
        disconnect(c);
    }
    for (const auto &c : m_connections.take(w)) {
        disconnect(c);
    }
    m_lastSent.remove(w);
    m_dirty.remove(w);
    m_byId.remove(id);
    if (m_helper) {
        m_helper->forgetIconGeometry(id);
    }
    m_server->broadcast(QStringLiteral("windows"), QStringLiteral("window.removed"), QJsonObject{{QStringLiteral("id"), id}});
    m_stackingDirty = true;
    scheduleFlush();
}

void WindowModel::markDirty(Window *w)
{
    if (!m_lastSent.contains(w)) {
        return;
    }
    m_dirty.insert(w);
    scheduleFlush();
}

int WindowModel::frameIntervalMs() const
{
    uint32_t maxRefresh = 0; // mHz
    for (LogicalOutput *o : workspace()->outputs()) {
        maxRefresh = std::max(maxRefresh, o->refreshRate());
    }
    if (maxRefresh < 1000) {
        return 16;
    }
    return std::clamp(int(std::floor(1000000.0 / maxRefresh)), 4, 50);
}

void WindowModel::scheduleFlush()
{
    // Idle means idle: with nobody listening there is nothing to compute or send. Deltas are
    // coalesced to at most one batch per frame of the fastest output.
    if (m_server->connections().isEmpty()) {
        m_dirty.clear();
        m_stackingDirty = m_outputsDirty = m_desktopsDirty = false;
        return;
    }
    if (!m_flushTimer.isActive()) {
        m_flushTimer.start(frameIntervalMs());
    }
}

void WindowModel::flush()
{
    const bool winSubs = m_server->hasSubscribers(QStringLiteral("windows"));
    const auto dirty = std::exchange(m_dirty, {});
    for (Window *w : dirty) {
        if (!m_lastSent.contains(w)) {
            continue;
        }
        const QJsonObject now = serialize(w);
        QJsonObject &last = m_lastSent[w];
        QJsonObject changes;
        for (auto it = now.constBegin(); it != now.constEnd(); ++it) {
            if (last.value(it.key()) != it.value()) {
                changes.insert(it.key(), it.value());
            }
        }
        last = now;
        if (!changes.isEmpty() && winSubs) {
            m_server->broadcast(QStringLiteral("windows"), QStringLiteral("window.changed"),
                                QJsonObject{{QStringLiteral("id"), now.value(QStringLiteral("id"))}, {QStringLiteral("changes"), changes}});
        }
    }
    if (std::exchange(m_stackingDirty, false) && m_server->hasSubscribers(QStringLiteral("stacking"))) {
        m_server->broadcast(QStringLiteral("stacking"), QStringLiteral("stacking.changed"), QJsonObject{{QStringLiteral("order"), stackingArray()}});
    }
    if (std::exchange(m_outputsDirty, false) && m_server->hasSubscribers(QStringLiteral("outputs"))) {
        const QJsonObject now = outputsData();
        if (now != m_lastOutputs) {
            m_lastOutputs = now;
            m_server->broadcast(QStringLiteral("outputs"), QStringLiteral("outputs.changed"), now);
        }
    }
    if (std::exchange(m_desktopsDirty, false) && m_server->hasSubscribers(QStringLiteral("desktops"))) {
        m_server->broadcast(QStringLiteral("desktops"), QStringLiteral("desktops.changed"), desktopsData());
    }
}

void WindowModel::watchConstraints(Window *w)
{
    for (const auto &c : m_constraintConnections.take(w)) {
        disconnect(c);
    }
    SurfaceInterface *surface = w->surface();
    if (!surface) {
        return;
    }
    auto dirty = [this, w]() {
        markDirty(w);
    };
    QList<QMetaObject::Connection> cons;
    cons << connect(surface, &SurfaceInterface::lockedPointerRegionChanged, this, dirty);
    cons << connect(surface, &SurfaceInterface::confinedPointerRegionChanged, this, dirty);
    cons << connect(surface, &SurfaceInterface::pointerConfinementChangedWithoutCommit, this, dirty);
    m_constraintConnections.insert(w, cons);
}

// A pointer lock / confinement the window's client holds (zwp_pointer_constraints_v1), whether
// KWin has activated it at this moment or not: games keep it while they run.
static bool hasPointerLock(const Window *w)
{
    const SurfaceInterface *s = w->surface();
    return s && (s->lockedPointer() || s->lockedPointerRegion().has_value());
}

static bool hasPointerConfinement(const Window *w)
{
    const SurfaceInterface *s = w->surface();
    return s && (s->confinedPointer() || s->confinedPointerRegion().has_value());
}

QJsonObject WindowModel::serialize(Window *w) const
{
    const QString scope = m_scopes->scopeOf(w);
    const bool layer = !scope.isNull();
    const RectF g = w->frameGeometry();
    QJsonArray desktops;
    for (VirtualDesktop *d : w->desktops()) {
        desktops.append(int(d->x11DesktopNumber()));
    }
    QString appId = w->desktopFileName();
    if (appId.endsWith(QLatin1String(".desktop"))) {
        appId.chop(8);
    }
    if (appId.isEmpty()) {
        appId = w->resourceClass();
    }
    QJsonValue menu;
    if (!w->applicationMenuServiceName().isEmpty() && !w->applicationMenuObjectPath().isEmpty()) {
        menu = QJsonObject{{QStringLiteral("service"), w->applicationMenuServiceName()}, {QStringLiteral("path"), w->applicationMenuObjectPath()}};
    }
    const QString type = typeOf(w, layer);
    Window *parent = w->transientFor();
    QJsonObject o{
        {QStringLiteral("id"), idOf(w)},
        {QStringLiteral("appId"), appId},
        {QStringLiteral("title"), w->caption()},
        {QStringLiteral("pid"), int(w->pid())},
        {QStringLiteral("x"), round2(g.x())},
        {QStringLiteral("y"), round2(g.y())},
        {QStringLiteral("w"), round2(g.width())},
        {QStringLiteral("h"), round2(g.height())},
        {QStringLiteral("output"), w->output() ? w->output()->name() : QString()},
        {QStringLiteral("desktops"), desktops},
        {QStringLiteral("allDesktops"), w->isOnAllDesktops()},
        {QStringLiteral("active"), w->isActive()},
        {QStringLiteral("minimized"), w->isMinimized()},
        {QStringLiteral("maximized"), w->maximizeMode() == MaximizeFull},
        {QStringLiteral("fullscreen"), w->isFullScreen()},
        {QStringLiteral("keepAbove"), w->keepAbove()},
        {QStringLiteral("demandsAttention"), w->isDemandingAttention()},
        {QStringLiteral("normal"), !layer && type == QLatin1String("normal") && !m_scopes->isShell(w)},
        {QStringLiteral("skipTaskbar"), w->skipTaskbar()},
        {QStringLiteral("skipSwitcher"), w->skipSwitcher()},
        {QStringLiteral("closeable"), w->isCloseable()},
        {QStringLiteral("minimizable"), w->isMinimizable()},
        {QStringLiteral("maximizable"), w->isMaximizable()},
        {QStringLiteral("icon"), w->icon().name()},
        {QStringLiteral("menu"), menu},
        // additions (see contract notes)
        {QStringLiteral("type"), type},
        {QStringLiteral("parentId"), (parent && tracked(parent)) ? QJsonValue(idOf(parent)) : QJsonValue()},
        {QStringLiteral("xwayland"), isXwayland(w)},
        {QStringLiteral("pointerLocked"), hasPointerLock(w)},
        {QStringLiteral("pointerConstrained"), hasPointerConfinement(w)},
        {QStringLiteral("content"), QJsonObject{{QStringLiteral("x"), round2(w->clientGeometry().x())}, {QStringLiteral("y"), round2(w->clientGeometry().y())},
                                                {QStringLiteral("w"), round2(w->clientGeometry().width())}, {QStringLiteral("h"), round2(w->clientGeometry().height())}}},
    };
    if (layer) {
        o.insert(QStringLiteral("namespace"), scope);
    }
    return o;
}

QJsonArray WindowModel::windowsArray() const
{
    QJsonArray arr;
    for (Window *w : workspace()->stackingOrder()) {
        if (m_lastSent.contains(w)) {
            arr.append(serialize(w));
        }
    }
    // tracked windows that are not in the stacking order (rare: being set up)
    for (auto it = m_lastSent.constBegin(); it != m_lastSent.constEnd(); ++it) {
        if (!workspace()->stackingOrder().contains(it.key())) {
            arr.append(serialize(it.key()));
        }
    }
    return arr;
}

QJsonArray WindowModel::stackingArray() const
{
    QJsonArray arr;
    for (Window *w : workspace()->stackingOrder()) {
        if (m_lastSent.contains(w)) {
            arr.append(idOf(w));
        }
    }
    return arr;
}

QJsonObject WindowModel::outputsData() const
{
    QJsonArray arr;
    const QList<LogicalOutput *> order = workspace()->outputOrder();
    for (LogicalOutput *o : workspace()->outputs()) {
        const RectF g = o->geometryF();
        // what is left of the output after layer-shell exclusive zones (menu bar, Dock) and other
        // struts: where a maximised window goes
        const RectF wa = workspace()->clientArea(MaximizeArea, o);
        arr.append(QJsonObject{
            {QStringLiteral("name"), o->name()},
            {QStringLiteral("x"), round2(g.x())},
            {QStringLiteral("y"), round2(g.y())},
            {QStringLiteral("w"), round2(g.width())},
            {QStringLiteral("h"), round2(g.height())},
            {QStringLiteral("scale"), o->scale()},
            {QStringLiteral("refresh"), round2(o->refreshRate() / 1000.0)},
            {QStringLiteral("internal"), o->isInternal()},
            {QStringLiteral("primary"), !order.isEmpty() && order.first() == o},
            {QStringLiteral("workArea"), QJsonObject{{QStringLiteral("x"), round2(wa.x())}, {QStringLiteral("y"), round2(wa.y())},
                                                     {QStringLiteral("w"), round2(wa.width())}, {QStringLiteral("h"), round2(wa.height())}}},
        });
    }
    return QJsonObject{{QStringLiteral("outputs"), arr}};
}

QJsonObject WindowModel::desktopsData() const
{
    VirtualDesktopManager *vds = VirtualDesktopManager::self();
    QJsonArray names;
    for (VirtualDesktop *d : vds->desktops()) {
        names.append(d->name());
    }
    return QJsonObject{{QStringLiteral("current"), int(vds->current())}, {QStringLiteral("count"), int(vds->count())}, {QStringLiteral("names"), names}};
}

// ------------------------------------------------------------------------------------ methods

void WindowModel::registerMethods()
{
    auto withWindow = [this](Params &p, const ReplyPtr &reply) -> Window * {
        const auto id = p.string(QStringLiteral("id"), true, 64);
        if (!id) {
            return nullptr;
        }
        Window *w = find(*id);
        if (!w) {
            reply->fail(Err::NotFound, QStringLiteral("no window with id '%1'").arg(id->left(64)));
        }
        return w;
    };
    auto method = [this](const QString &name, Handler h, const QString &cap = QStringLiteral("windows")) {
        m_server->registerMethod(name, MethodSpec{false, cap, std::move(h)});
    };

    method(QStringLiteral("window.list"), [this](Params &, const ReplyPtr &r) {
        r->ok(QJsonObject{{QStringLiteral("windows"), windowsArray()}});
    });
    method(QStringLiteral("window.activate"), [withWindow](Params &p, const ReplyPtr &r) {
        if (Window *w = withWindow(p, r)) {
            if (w->isMinimized()) {
                w->setMinimized(false);
            }
            if (!w->isOnCurrentDesktop() && !w->desktops().isEmpty()) {
                VirtualDesktopManager::self()->setCurrent(w->desktops().constFirst());
            }
            workspace()->activateWindow(w, true);
            r->ok();
        }
    });
    method(QStringLiteral("window.close"), [withWindow](Params &p, const ReplyPtr &r) {
        if (Window *w = withWindow(p, r)) {
            if (!w->isCloseable()) {
                r->fail(Err::Invalid, QStringLiteral("window cannot be closed"));
                return;
            }
            w->closeWindow();
            r->ok();
        }
    });
    method(QStringLiteral("window.setMinimized"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto v = p.boolean(QStringLiteral("value"), true);
        Window *w = v ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        if (*v && !w->isMinimizable()) {
            r->fail(Err::Invalid, QStringLiteral("window cannot be minimised"));
            return;
        }
        w->setMinimized(*v);
        r->ok();
    });
    method(QStringLiteral("window.setMaximized"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto v = p.boolean(QStringLiteral("value"), true);
        Window *w = v ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        if (!w->isMaximizable()) {
            r->fail(Err::Invalid, QStringLiteral("window cannot be maximised"));
            return;
        }
        w->maximize(*v ? MaximizeFull : MaximizeRestore);
        r->ok();
    });
    method(QStringLiteral("window.setFullscreen"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto v = p.boolean(QStringLiteral("value"), true);
        Window *w = v ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        w->setFullScreen(*v);
        r->ok();
    });
    method(QStringLiteral("window.setGeometry"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto x = p.number(QStringLiteral("x"), true, -kCoordLimit, kCoordLimit);
        const auto y = p.number(QStringLiteral("y"), true, -kCoordLimit, kCoordLimit);
        const auto wd = p.number(QStringLiteral("w"), true, 1, kCoordLimit);
        const auto ht = p.number(QStringLiteral("h"), true, 1, kCoordLimit);
        Window *w = (x && y && wd && ht) ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        if (w->isFullScreen() || !w->isMovable()) {
            r->fail(Err::Invalid, QStringLiteral("window cannot be moved"));
            return;
        }
        if (w->maximizeMode() != MaximizeRestore) {
            w->maximize(MaximizeRestore);
        }
        if (w->isResizable()) {
            w->moveResize(RectF(*x, *y, *wd, *ht));
        } else {
            w->move(QPointF(*x, *y));
        }
        r->ok();
    });
    method(QStringLiteral("window.toDesktop"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto d = p.integer(QStringLiteral("desktop"), true, 1, 64);
        Window *w = d ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        VirtualDesktop *vd = VirtualDesktopManager::self()->desktopForX11Id(uint(*d));
        if (!vd) {
            r->fail(Err::NotFound, QStringLiteral("no desktop %1").arg(*d));
            return;
        }
        workspace()->sendWindowToDesktops(w, {vd}, false);
        r->ok();
    });
    method(QStringLiteral("window.toOutput"), [withWindow](Params &p, const ReplyPtr &r) {
        const auto name = p.string(QStringLiteral("output"), true, 128);
        Window *w = name ? withWindow(p, r) : nullptr;
        if (!w) {
            return;
        }
        LogicalOutput *o = workspace()->findOutput(*name);
        if (!o) {
            r->fail(Err::NotFound, QStringLiteral("no output '%1'").arg(*name));
            return;
        }
        w->sendToOutput(o);
        r->ok();
    });
    method(
        QStringLiteral("window.setIconGeometry"), [this, withWindow](Params &p, const ReplyPtr &r) {
            const auto x = p.number(QStringLiteral("x"), true, -kCoordLimit, kCoordLimit);
            const auto y = p.number(QStringLiteral("y"), true, -kCoordLimit, kCoordLimit);
            const auto wd = p.number(QStringLiteral("w"), true, 0, kCoordLimit);
            const auto ht = p.number(QStringLiteral("h"), true, 0, kCoordLimit);
            Window *w = (x && y && wd && ht) ? withWindow(p, r) : nullptr;
            if (!w) {
                return;
            }
            if (!m_helper || !m_helper->iconGeometryReady()) {
                r->fail(Err::Unsupported, QStringLiteral("icon geometry is not available right now"));
                return;
            }
            m_helper->setIconGeometry(w, idOf(w), QRectF(*x, *y, *wd, *ht));
            r->ok();
        },
        QStringLiteral("iconGeometry"));

    method(
        QStringLiteral("desktop.set"), [](Params &p, const ReplyPtr &r) {
            const auto idx = p.integer(QStringLiteral("index"), true, 1, 64);
            if (!idx) {
                return;
            }
            if (uint(*idx) > VirtualDesktopManager::self()->count()) {
                r->fail(Err::NotFound, QStringLiteral("no desktop %1").arg(*idx));
                return;
            }
            VirtualDesktopManager::self()->setCurrent(uint(*idx));
            r->ok();
        },
        QString());
    method(
        QStringLiteral("workspace.showDesktop"), [](Params &p, const ReplyPtr &r) {
            const auto v = p.boolean(QStringLiteral("value"), true);
            if (!v) {
                return;
            }
            workspace()->setShowingDesktop(*v);
            r->ok();
        },
        QString());
    method(
        QStringLiteral("effect.toggle"), [](Params &p, const ReplyPtr &r) {
            const auto name = p.string(QStringLiteral("name"), true, 32);
            if (!name) {
                return;
            }
            QString effectName;
            QString action;
            if (*name == QLatin1String("overview")) {
                effectName = QStringLiteral("overview");
                action = QStringLiteral("Overview");
            } else if (*name == QLatin1String("desktopgrid")) {
                effectName = QStringLiteral("overview");
                action = QStringLiteral("Grid View");
            } else if (*name == QLatin1String("windowview")) {
                effectName = QStringLiteral("windowview");
                action = QStringLiteral("ExposeAll");
            } else {
                r->fail(Err::Invalid, QStringLiteral("unknown effect '%1'").arg(name->left(32)));
                return;
            }
            Effect *effect = effects ? effects->findEffect(effectName) : nullptr;
            QAction *a = nullptr;
            if (effect) {
                const auto actions = effect->findChildren<QAction *>();
                for (QAction *candidate : actions) {
                    if (candidate->objectName() == action) {
                        a = candidate;
                        break;
                    }
                }
            }
            if (!a) {
                r->fail(Err::Unsupported, QStringLiteral("effect '%1' is not loaded").arg(*name));
                return;
            }
            a->trigger();
            r->ok();
        },
        QString());
    method(
        QStringLiteral("cursor.get"), [](Params &, const ReplyPtr &r) {
            const QPointF pos = Cursors::self()->mouse()->pos();
            r->ok(QJsonObject{{QStringLiteral("x"), round2(pos.x())}, {QStringLiteral("y"), round2(pos.y())}});
        },
        QString());
}

} // namespace Kristall
