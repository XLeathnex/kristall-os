/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "helperclient.h"
#include "util.h"
#include "windows.h"

#include "core/output.h"
#include "wayland/clientconnection.h"
#include "wayland/display.h"
#include "wayland/surface.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"

#include <wayland-client.h>

#include "ext-data-control-v1-client-protocol.h"
#include "plasma-window-management-client-protocol.h"
// the generated C header names a parameter "namespace"
#define namespace namespace_
#include "wlr-layer-shell-unstable-v1-client-protocol.h"
#undef namespace

#include <QTimer>

#include <cerrno>
#include <cstring>
#include <fcntl.h>
#include <sys/mman.h>
#include <sys/socket.h>
#include <unistd.h>

using namespace KWin;

namespace Kristall
{

static const char kAnchorNamespace[] = "kristall-bridge-anchor";
constexpr qsizetype kMaxClipboardType = 16 << 20;
constexpr qsizetype kMaxClipboardTotal = 32 << 20;
constexpr int kMaxClipboardTypes = 24;

// ------------------------------------------------------------------------------------ listeners

static void registryGlobal(void *data, wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
    static_cast<HelperClient *>(data)->onGlobal(registry, name, interface, version);
}
static void registryGlobalRemove(void *data, wl_registry *, uint32_t name)
{
    static_cast<HelperClient *>(data)->onGlobalRemove(name);
}
static const wl_registry_listener s_registryListener = {registryGlobal, registryGlobalRemove};

static void outputGeometry(void *, wl_output *, int32_t, int32_t, int32_t, int32_t, int32_t, const char *, const char *, int32_t)
{
}
static void outputMode(void *, wl_output *, uint32_t, int32_t, int32_t, int32_t)
{
}
static void outputDone(void *, wl_output *)
{
}
static void outputScale(void *, wl_output *, int32_t)
{
}
static void outputName(void *data, wl_output *output, const char *name)
{
    static_cast<HelperClient *>(data)->onOutputName(output, name);
}
static void outputDescription(void *, wl_output *, const char *)
{
}
static const wl_output_listener s_outputListener = {outputGeometry, outputMode, outputDone, outputScale, outputName, outputDescription};

static void layerConfigure(void *data, zwlr_layer_surface_v1 *surface, uint32_t serial, uint32_t w, uint32_t h)
{
    static_cast<HelperClient *>(data)->onLayerConfigure(surface, serial, w, h);
}
static void layerClosed(void *data, zwlr_layer_surface_v1 *surface)
{
    static_cast<HelperClient *>(data)->onLayerClosed(surface);
}
static const zwlr_layer_surface_v1_listener s_layerListener = {layerConfigure, layerClosed};

static void offerMime(void *data, ext_data_control_offer_v1 *offer, const char *mime)
{
    static_cast<HelperClient *>(data)->onOfferMime(offer, mime);
}
static const ext_data_control_offer_v1_listener s_offerListener = {offerMime};

static void deviceDataOffer(void *data, ext_data_control_device_v1 *, ext_data_control_offer_v1 *offer)
{
    static_cast<HelperClient *>(data)->onDataOffer(offer);
}
static void deviceSelection(void *data, ext_data_control_device_v1 *, ext_data_control_offer_v1 *offer)
{
    static_cast<HelperClient *>(data)->onSelection(offer);
}
static void deviceFinished(void *data, ext_data_control_device_v1 *)
{
    static_cast<HelperClient *>(data)->onDeviceFinished();
}
static void devicePrimarySelection(void *, ext_data_control_device_v1 *, ext_data_control_offer_v1 *offer)
{
    if (offer) {
        ext_data_control_offer_v1_destroy(offer);
    }
}
static const ext_data_control_device_v1_listener s_deviceListener = {deviceDataOffer, deviceSelection, deviceFinished, devicePrimarySelection};

static void sourceSend(void *data, ext_data_control_source_v1 *source, const char *mime, int32_t fd)
{
    static_cast<HelperClient *>(data)->onSourceSend(source, mime, fd);
}
static void sourceCancelled(void *data, ext_data_control_source_v1 *source)
{
    static_cast<HelperClient *>(data)->onSourceCancelled(source);
}
static const ext_data_control_source_v1_listener s_sourceListener = {sourceSend, sourceCancelled};

// ------------------------------------------------------------------------------------ lifecycle

HelperClient::HelperClient(LayerScopes *scopes, QObject *parent)
    : QObject(parent)
    , m_scopes(scopes)
{
}

HelperClient::~HelperClient()
{
    if (!m_display) {
        return;
    }
    for (auto it = m_icons.begin(); it != m_icons.end(); ++it) {
        if (it->plasmaWindow) {
            org_kde_plasma_window_destroy(it->plasmaWindow);
        }
    }
    for (Anchor &a : m_anchors) {
        destroyAnchor(a);
    }
    if (m_source && m_source->source) {
        ext_data_control_source_v1_destroy(m_source->source);
    }
    for (auto *s : std::as_const(m_retiredSources)) {
        ext_data_control_source_v1_destroy(s);
    }
    for (auto it = m_offers.begin(); it != m_offers.end(); ++it) {
        ext_data_control_offer_v1_destroy(it.key());
    }
    if (m_dataDevice) {
        ext_data_control_device_v1_destroy(m_dataDevice);
    }
    wl_display_flush(m_display);
    delete m_readNotifier;
    delete m_writeNotifier;
    wl_display_disconnect(m_display);
    m_display = nullptr;
    // the server side notices the closed socket and destroys the client in its own time
}

bool HelperClient::start()
{
    int fds[2];
    if (socketpair(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0, fds) != 0) {
        logWarning(QStringLiteral("helper: socketpair failed: %1").arg(QString::fromLocal8Bit(strerror(errno))));
        return false;
    }
    m_connection = waylandServer()->display()->createClient(fds[0]);
    if (!m_connection) {
        close(fds[0]);
        close(fds[1]);
        logWarning(QStringLiteral("helper: compositor refused the in-process client"));
        return false;
    }
    m_display = wl_display_connect_to_fd(fds[1]);
    if (!m_display) {
        close(fds[1]);
        logWarning(QStringLiteral("helper: cannot connect the in-process client"));
        return false;
    }
    const int fd = wl_display_get_fd(m_display);
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
    m_readNotifier = new QSocketNotifier(fd, QSocketNotifier::Read, this);
    connect(m_readNotifier, &QSocketNotifier::activated, this, &HelperClient::dispatch);
    m_writeNotifier = new QSocketNotifier(fd, QSocketNotifier::Write, this);
    m_writeNotifier->setEnabled(false);
    connect(m_writeNotifier, &QSocketNotifier::activated, this, &HelperClient::flush);

    m_registry = wl_display_get_registry(m_display);
    wl_registry_add_listener(m_registry, &s_registryListener, this);
    flush();

    connect(workspace(), &Workspace::outputsChanged, this, &HelperClient::syncAnchors);
    return true;
}

void HelperClient::fail(const QString &why)
{
    if (m_dead) {
        return;
    }
    m_dead = true;
    logWarning(QStringLiteral("helper connection lost (%1); icon geometry and clipboard paste are unavailable").arg(why));
    if (m_readNotifier) {
        m_readNotifier->setEnabled(false);
    }
    if (m_writeNotifier) {
        m_writeNotifier->setEnabled(false);
    }
}

void HelperClient::dispatch()
{
    if (m_dead) {
        return;
    }
    while (wl_display_prepare_read(m_display) != 0) {
        if (wl_display_dispatch_pending(m_display) < 0) {
            fail(QStringLiteral("dispatch failed"));
            return;
        }
    }
    if (wl_display_read_events(m_display) < 0 && errno != EAGAIN) {
        fail(QStringLiteral("read failed: %1").arg(QString::fromLocal8Bit(strerror(errno))));
        return;
    }
    if (wl_display_dispatch_pending(m_display) < 0) {
        fail(QStringLiteral("protocol error %1").arg(wl_display_get_error(m_display)));
        return;
    }
    flush();
}

void HelperClient::flush()
{
    if (m_dead || !m_display) {
        return;
    }
    const int r = wl_display_flush(m_display);
    if (r < 0 && errno == EAGAIN) {
        m_writeNotifier->setEnabled(true);
    } else if (r < 0) {
        fail(QStringLiteral("flush failed: %1").arg(QString::fromLocal8Bit(strerror(errno))));
    } else {
        m_writeNotifier->setEnabled(false);
    }
}

// ------------------------------------------------------------------------------------ registry

void HelperClient::onGlobal(wl_registry *registry, uint32_t name, const char *interface, uint32_t version)
{
    const QByteArray iface(interface);
    if (iface == wl_compositor_interface.name) {
        m_compositor = static_cast<wl_compositor *>(wl_registry_bind(registry, name, &wl_compositor_interface, std::min<uint32_t>(version, 4)));
    } else if (iface == wl_shm_interface.name) {
        m_shm = static_cast<wl_shm *>(wl_registry_bind(registry, name, &wl_shm_interface, 1));
    } else if (iface == wl_seat_interface.name && !m_seat) {
        m_seat = static_cast<wl_seat *>(wl_registry_bind(registry, name, &wl_seat_interface, 1));
        if (m_dataControl && !m_dataDevice) {
            m_dataDevice = ext_data_control_manager_v1_get_data_device(m_dataControl, m_seat);
            ext_data_control_device_v1_add_listener(m_dataDevice, &s_deviceListener, this);
        }
    } else if (iface == wl_output_interface.name && version >= 4) {
        auto *output = static_cast<wl_output *>(wl_registry_bind(registry, name, &wl_output_interface, 4));
        wl_output_add_listener(output, &s_outputListener, this);
        m_outputs.insert(name, output);
    } else if (iface == zwlr_layer_shell_v1_interface.name) {
        m_layerShell = static_cast<zwlr_layer_shell_v1 *>(wl_registry_bind(registry, name, &zwlr_layer_shell_v1_interface, std::min<uint32_t>(version, 3)));
        QTimer::singleShot(0, this, &HelperClient::syncAnchors);
    } else if (iface == org_kde_plasma_window_management_interface.name && version >= 12) {
        m_pwm = static_cast<org_kde_plasma_window_management *>(
            wl_registry_bind(registry, name, &org_kde_plasma_window_management_interface, std::min<uint32_t>(version, 16)));
    } else if (iface == ext_data_control_manager_v1_interface.name) {
        m_dataControl = static_cast<ext_data_control_manager_v1 *>(wl_registry_bind(registry, name, &ext_data_control_manager_v1_interface, 1));
        if (m_seat && !m_dataDevice) {
            m_dataDevice = ext_data_control_manager_v1_get_data_device(m_dataControl, m_seat);
            ext_data_control_device_v1_add_listener(m_dataDevice, &s_deviceListener, this);
        }
    }
}

void HelperClient::onGlobalRemove(uint32_t name)
{
    if (wl_output *output = m_outputs.take(name)) {
        for (int i = m_anchors.size() - 1; i >= 0; --i) {
            if (m_anchors[i].output == output) {
                destroyAnchor(m_anchors[i]);
                m_anchors.removeAt(i);
            }
        }
        m_outputNames.remove(output);
        wl_output_release(output);
        reapplyIcons();
        flush();
    }
}

void HelperClient::onOutputName(wl_output *output, const char *name)
{
    m_outputNames.insert(output, QString::fromUtf8(name));
    QTimer::singleShot(0, this, &HelperClient::syncAnchors);
}

// ------------------------------------------------------------------------------------ anchors

void HelperClient::syncAnchors()
{
    if (m_dead || !m_layerShell || !m_compositor || !m_shm) {
        return;
    }
    QSet<wl_output *> wanted;
    for (auto it = m_outputNames.constBegin(); it != m_outputNames.constEnd(); ++it) {
        wanted.insert(it.key());
    }
    for (int i = m_anchors.size() - 1; i >= 0; --i) {
        if (!wanted.contains(m_anchors[i].output)) {
            destroyAnchor(m_anchors[i]);
            m_anchors.removeAt(i);
        } else {
            wanted.remove(m_anchors[i].output);
        }
    }
    for (wl_output *o : std::as_const(wanted)) {
        createAnchor(o, m_outputNames.value(o));
    }
    flush();
}

void HelperClient::createAnchor(wl_output *output, const QString &name)
{
    Anchor a;
    a.output = output;
    a.outputName = name;
    a.surface = wl_compositor_create_surface(m_compositor);
    wl_region *empty = wl_compositor_create_region(m_compositor);
    wl_surface_set_input_region(a.surface, empty);
    wl_region_destroy(empty);
    a.layer = zwlr_layer_shell_v1_get_layer_surface(m_layerShell, a.surface, output, ZWLR_LAYER_SHELL_V1_LAYER_BACKGROUND, kAnchorNamespace);
    zwlr_layer_surface_v1_add_listener(a.layer, &s_layerListener, this);
    zwlr_layer_surface_v1_set_size(a.layer, 1, 1);
    zwlr_layer_surface_v1_set_anchor(a.layer, ZWLR_LAYER_SURFACE_V1_ANCHOR_TOP | ZWLR_LAYER_SURFACE_V1_ANCHOR_LEFT);
    zwlr_layer_surface_v1_set_exclusive_zone(a.layer, -1);
    wl_surface_commit(a.surface);
    m_anchors.append(a);
}

void HelperClient::destroyAnchor(Anchor &a)
{
    // KWin drops minimised geometries whose panel surface is destroyed; forget our references
    for (auto it = m_icons.begin(); it != m_icons.end(); ++it) {
        if (it->sentPanel == a.surface) {
            it->sentPanel = nullptr;
        }
    }
    if (a.layer) {
        zwlr_layer_surface_v1_destroy(a.layer);
    }
    if (a.surface) {
        wl_surface_destroy(a.surface);
    }
    if (a.buffer) {
        wl_buffer_destroy(a.buffer);
    }
    a = Anchor();
}

void HelperClient::onLayerConfigure(zwlr_layer_surface_v1 *surface, uint32_t serial, uint32_t, uint32_t)
{
    for (Anchor &a : m_anchors) {
        if (a.layer != surface) {
            continue;
        }
        zwlr_layer_surface_v1_ack_configure(surface, serial);
        if (!a.buffer) {
            // one transparent ARGB pixel
            const int fd = memfd_create("kristall-bridge-anchor", MFD_CLOEXEC | MFD_ALLOW_SEALING);
            if (fd < 0 || ftruncate(fd, 4) != 0) {
                if (fd >= 0) {
                    close(fd);
                }
                return;
            }
            wl_shm_pool *pool = wl_shm_create_pool(m_shm, fd, 4);
            a.buffer = wl_shm_pool_create_buffer(pool, 0, 1, 1, 4, WL_SHM_FORMAT_ARGB8888);
            wl_shm_pool_destroy(pool);
            close(fd);
            wl_surface_attach(a.surface, a.buffer, 0, 0);
            wl_surface_damage(a.surface, 0, 0, 1, 1);
        }
        wl_surface_commit(a.surface);
        a.configured = true;
        // the window is created when the commit is processed; re-apply after that
        QTimer::singleShot(0, this, &HelperClient::reapplyIcons);
    }
    flush();
}

void HelperClient::onLayerClosed(zwlr_layer_surface_v1 *surface)
{
    for (int i = m_anchors.size() - 1; i >= 0; --i) {
        if (m_anchors[i].layer == surface) {
            destroyAnchor(m_anchors[i]);
            m_anchors.removeAt(i);
        }
    }
    QTimer::singleShot(0, this, &HelperClient::syncAnchors);
}

Window *HelperClient::anchorWindow(const Anchor &a) const
{
    if (!a.configured || !m_connection) {
        return nullptr;
    }
    for (Window *w : workspace()->windows()) {
        if (w->surface() && w->surface()->client() == m_connection && m_scopes->isBridgeInternal(w) && w->output()
            && w->output()->name() == a.outputName) {
            return w;
        }
    }
    return nullptr;
}

// ------------------------------------------------------------------------------------ icon geometry

bool HelperClient::iconGeometryReady() const
{
    if (!alive() || !m_pwm) {
        return false;
    }
    for (const Anchor &a : m_anchors) {
        if (anchorWindow(a)) {
            return true;
        }
    }
    return false;
}

void HelperClient::setIconGeometry(Window *window, const QString &id, const QRectF &global)
{
    IconTarget &t = m_icons[id];
    t.window = window;
    t.global = global;
    applyIcon(id, t);
    flush();
}

void HelperClient::forgetIconGeometry(const QString &id)
{
    auto it = m_icons.find(id);
    if (it == m_icons.end()) {
        return;
    }
    if (it->plasmaWindow && m_display && !m_dead) {
        org_kde_plasma_window_destroy(it->plasmaWindow);
    }
    m_icons.erase(it);
    flush();
}

void HelperClient::applyIcon(const QString &id, IconTarget &t)
{
    if (!t.window || m_dead || !m_pwm) {
        return;
    }
    if (!t.plasmaWindow) {
        const QByteArray uuid = t.window->internalId().toString().toUtf8(); // with braces, as KWin stores it
        t.plasmaWindow = org_kde_plasma_window_management_get_window_by_uuid(m_pwm, uuid.constData());
    }
    if (t.global.isEmpty()) {
        if (t.sentPanel) {
            org_kde_plasma_window_unset_minimized_geometry(t.plasmaWindow, t.sentPanel);
            t.sentPanel = nullptr;
        }
        return;
    }
    // the anchor on the output that contains the rectangle's centre; geometry is panel-relative
    const QPointF c = t.global.center();
    const Anchor *best = nullptr;
    Window *bestWindow = nullptr;
    for (const Anchor &a : std::as_const(m_anchors)) {
        Window *aw = anchorWindow(a);
        if (!aw) {
            continue;
        }
        if (!best || (aw->output() && aw->output()->geometryF().contains(c))) {
            best = &a;
            bestWindow = aw;
        }
    }
    if (!best) {
        return;
    }
    if (t.sentPanel && t.sentPanel != best->surface) {
        org_kde_plasma_window_unset_minimized_geometry(t.plasmaWindow, t.sentPanel);
    }
    const QPointF origin = bestWindow->pos();
    const int x = std::max(0, int(std::lround(t.global.x() - origin.x())));
    const int y = std::max(0, int(std::lround(t.global.y() - origin.y())));
    org_kde_plasma_window_set_minimized_geometry(t.plasmaWindow, best->surface, uint32_t(x), uint32_t(y),
                                                 uint32_t(std::max(1L, std::lround(t.global.width()))),
                                                 uint32_t(std::max(1L, std::lround(t.global.height()))));
    t.sentPanel = best->surface;
    Q_UNUSED(id)
}

void HelperClient::reapplyIcons()
{
    for (auto it = m_icons.begin(); it != m_icons.end(); ++it) {
        applyIcon(it.key(), it.value());
    }
    flush();
}

// ------------------------------------------------------------------------------------ clipboard

bool HelperClient::clipboardReady() const
{
    return alive() && m_dataDevice;
}

bool HelperClient::hasSelection() const
{
    return m_selection != nullptr || m_source != nullptr;
}

void HelperClient::onDataOffer(ext_data_control_offer_v1 *offer)
{
    m_offers.insert(offer, {});
    ext_data_control_offer_v1_add_listener(offer, &s_offerListener, this);
}

void HelperClient::onOfferMime(ext_data_control_offer_v1 *offer, const char *mime)
{
    auto it = m_offers.find(offer);
    if (it != m_offers.end() && it->size() < 64) {
        it->append(QString::fromUtf8(mime));
    }
}

void HelperClient::onSelection(ext_data_control_offer_v1 *offer)
{
    if (m_selection && m_selection != offer) {
        m_offers.remove(m_selection);
        ext_data_control_offer_v1_destroy(m_selection);
    }
    m_selection = offer;
}

void HelperClient::onDeviceFinished()
{
    if (m_dataDevice) {
        ext_data_control_device_v1_destroy(m_dataDevice);
        m_dataDevice = nullptr;
    }
}

void HelperClient::snapshotClipboard(std::function<void(ClipboardData)> done)
{
    if (m_source && m_selection == nullptr) {
        done(m_source->data);
        return;
    }
    if (!clipboardReady() || !m_selection) {
        done({});
        return;
    }
    QStringList mimes = m_offers.value(m_selection);
    // our own source: no need to read it back through the compositor
    if (m_source && mimes == [this]() {
            QStringList l;
            for (const auto &p : std::as_const(m_source->data)) {
                l << p.first;
            }
            return l;
        }()) {
        done(m_source->data);
        return;
    }
    static const QSet<QString> skip = {QStringLiteral("SAVE_TARGETS"), QStringLiteral("TARGETS"), QStringLiteral("MULTIPLE"), QStringLiteral("TIMESTAMP")};
    struct State
    {
        ClipboardData data;
        int pending = 0;
        qsizetype total = 0;
        bool finished = false;
        std::function<void(ClipboardData)> done;
        QList<QSocketNotifier *> notifiers;
    };
    auto state = std::make_shared<State>();
    state->done = std::move(done);
    auto finish = [state]() {
        if (state->finished) {
            return;
        }
        state->finished = true;
        for (QSocketNotifier *n : std::as_const(state->notifiers)) {
            const int fd = int(n->socket());
            n->setEnabled(false);
            n->deleteLater();
            close(fd);
        }
        state->notifiers.clear();
        auto cb = std::move(state->done);
        cb(std::move(state->data));
    };
    int count = 0;
    for (const QString &mime : std::as_const(mimes)) {
        if (skip.contains(mime) || count >= kMaxClipboardTypes) {
            continue;
        }
        int p[2];
        if (pipe2(p, O_CLOEXEC | O_NONBLOCK) != 0) {
            continue;
        }
        ext_data_control_offer_v1_receive(m_selection, mime.toUtf8().constData(), p[1]);
        close(p[1]); // libwayland duplicated it while marshalling
        const int index = state->data.size();
        state->data.append({mime, QByteArray()});
        state->pending++;
        count++;
        auto *n = new QSocketNotifier(p[0], QSocketNotifier::Read, this);
        state->notifiers << n;
        connect(n, &QSocketNotifier::activated, this, [state, n, index, finish]() {
            if (state->finished) {
                return;
            }
            char buf[65536];
            for (;;) {
                const ssize_t r = read(int(n->socket()), buf, sizeof(buf));
                if (r > 0) {
                    auto &bytes = state->data[index].second;
                    if (bytes.size() + r > kMaxClipboardType || state->total + r > kMaxClipboardTotal) {
                        bytes.clear(); // too large to keep: this type is dropped
                        state->data[index].first.clear();
                    } else {
                        bytes.append(buf, r);
                        state->total += r;
                    }
                    continue;
                }
                if (r < 0 && errno == EAGAIN) {
                    return;
                }
                // EOF or error: this type is complete
                n->setEnabled(false);
                state->notifiers.removeOne(n);
                close(int(n->socket()));
                n->deleteLater();
                if (--state->pending == 0) {
                    finish();
                }
                return;
            }
        });
    }
    flush();
    if (state->pending == 0) {
        finish();
        return;
    }
    // an unresponsive clipboard owner must not stall the agent: take what arrived within 1 s
    QTimer::singleShot(1000, this, finish);
}

void HelperClient::setClipboard(const ClipboardData &data, std::function<void()> served)
{
    if (!clipboardReady() || !m_dataControl) {
        return;
    }
    if (m_source) {
        m_retiredSources << m_source->source; // destroyed when the compositor cancels it
    }
    m_source = std::make_unique<Source>();
    m_source->data.clear();
    for (const auto &p : data) {
        if (!p.first.isEmpty()) {
            m_source->data.append(p);
        }
    }
    m_source->served = std::move(served);
    m_source->source = ext_data_control_manager_v1_create_data_source(m_dataControl);
    ext_data_control_source_v1_add_listener(m_source->source, &s_sourceListener, this);
    for (const auto &p : std::as_const(m_source->data)) {
        ext_data_control_source_v1_offer(m_source->source, p.first.toUtf8().constData());
    }
    ext_data_control_device_v1_set_selection(m_dataDevice, m_source->source);
    flush();
}

void HelperClient::clearClipboard()
{
    if (!clipboardReady()) {
        return;
    }
    ext_data_control_device_v1_set_selection(m_dataDevice, nullptr);
    flush();
}

void HelperClient::onSourceSend(ext_data_control_source_v1 *source, const char *mime, int fd)
{
    const Source *s = (m_source && m_source->source == source) ? m_source.get() : nullptr;
    if (!s) {
        close(fd);
        return;
    }
    QByteArray bytes;
    for (const auto &p : s->data) {
        if (p.first == QLatin1String(mime)) {
            bytes = p.second;
            break;
        }
    }
    fcntl(fd, F_SETFL, fcntl(fd, F_GETFL) | O_NONBLOCK);
    writeToFd(fd, bytes, [this, source]() {
        if (m_source && m_source->source == source && !m_source->servedOnce) {
            m_source->servedOnce = true;
            if (m_source->served) {
                auto cb = std::move(m_source->served);
                cb();
            }
        }
    });
}

void HelperClient::writeToFd(int fd, const QByteArray &bytes, std::function<void()> done)
{
    auto offset = std::make_shared<qsizetype>(0);
    auto *n = new QSocketNotifier(fd, QSocketNotifier::Write, this);
    auto finish = [n, fd, done]() {
        n->setEnabled(false);
        n->deleteLater();
        close(fd);
        if (done) {
            done();
        }
    };
    auto pump = [bytes, offset, fd, finish]() {
        while (*offset < bytes.size()) {
            const ssize_t w = write(fd, bytes.constData() + *offset, size_t(bytes.size() - *offset));
            if (w > 0) {
                *offset += w;
                continue;
            }
            if (w < 0 && errno == EAGAIN) {
                return;
            }
            break; // reader went away (EPIPE; SIGPIPE is ignored in KWin)
        }
        finish();
    };
    connect(n, &QSocketNotifier::activated, this, pump);
    // a reader that never reads must not keep the fd forever
    QTimer::singleShot(5000, n, [n, finish]() {
        if (n->isEnabled()) {
            finish();
        }
    });
    pump();
}

void HelperClient::onSourceCancelled(ext_data_control_source_v1 *source)
{
    if (m_source && m_source->source == source) {
        m_source.reset();
    }
    m_retiredSources.removeOne(source);
    ext_data_control_source_v1_destroy(source);
    flush();
}

} // namespace Kristall
