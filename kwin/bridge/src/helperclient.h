/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QByteArray>
#include <QHash>
#include <QList>
#include <QMap>
#include <QObject>
#include <QPointer>
#include <QRectF>
#include <QSocketNotifier>

#include <functional>
#include <memory>

struct wl_display;
struct wl_registry;
struct wl_compositor;
struct wl_shm;
struct wl_seat;
struct wl_output;
struct wl_surface;
struct wl_buffer;
struct zwlr_layer_shell_v1;
struct zwlr_layer_surface_v1;
struct org_kde_plasma_window_management;
struct org_kde_plasma_window;
struct ext_data_control_manager_v1;
struct ext_data_control_device_v1;
struct ext_data_control_source_v1;
struct ext_data_control_offer_v1;

namespace KWin
{
class Window;
class ClientConnection;
}

namespace Kristall
{

class LayerScopes;

// Clipboard contents by MIME type (kept only in memory, never logged).
using ClipboardData = QList<std::pair<QString, QByteArray>>;

// An in-process Wayland client of the compositor, connected through a socketpair. It gives the
// bridge access to two things KWin exposes only to Wayland clients:
//  * per-window minimise targets (org_kde_plasma_window.set_minimized_geometry), which is what
//    Window::iconGeometry() and therefore KWin's minimise animations read; the "panel" the
//    geometry is relative to is a 1x1 transparent, input-less layer surface per output;
//  * the clipboard (ext-data-control-v1), for the paste fallback of agent.text.
// It never blocks: there are no roundtrips, the socket is non-blocking and driven by notifiers.
class HelperClient : public QObject
{
    Q_OBJECT
public:
    HelperClient(LayerScopes *scopes, QObject *parent);
    ~HelperClient() override;

    bool start();
    bool alive() const
    {
        return m_display != nullptr && !m_dead;
    }

    // icon geometry
    bool iconGeometryReady() const;
    void setIconGeometry(KWin::Window *window, const QString &id, const QRectF &global);
    void forgetIconGeometry(const QString &id);

    // clipboard
    bool clipboardReady() const;
    bool hasSelection() const;
    // Reads every offered MIME type of the current clipboard (bounded in size and time).
    void snapshotClipboard(std::function<void(ClipboardData)> done);
    // Owns the clipboard with the given data. `served` runs after the first transfer completed.
    void setClipboard(const ClipboardData &data, std::function<void()> served = {});
    void clearClipboard();

    // handlers called from the C callbacks
    void onGlobal(wl_registry *registry, uint32_t name, const char *interface, uint32_t version);
    void onGlobalRemove(uint32_t name);
    void onOutputName(wl_output *output, const char *name);
    void onLayerConfigure(zwlr_layer_surface_v1 *surface, uint32_t serial, uint32_t w, uint32_t h);
    void onLayerClosed(zwlr_layer_surface_v1 *surface);
    void onDataOffer(ext_data_control_offer_v1 *offer);
    void onOfferMime(ext_data_control_offer_v1 *offer, const char *mime);
    void onSelection(ext_data_control_offer_v1 *offer);
    void onSourceSend(ext_data_control_source_v1 *source, const char *mime, int fd);
    void onSourceCancelled(ext_data_control_source_v1 *source);
    void onDeviceFinished();

private:
    struct Anchor
    {
        QString outputName;
        wl_output *output = nullptr;
        wl_surface *surface = nullptr;
        zwlr_layer_surface_v1 *layer = nullptr;
        wl_buffer *buffer = nullptr;
        bool configured = false;
    };
    struct IconTarget
    {
        QPointer<KWin::Window> window;
        QRectF global;
        org_kde_plasma_window *plasmaWindow = nullptr;
        wl_surface *sentPanel = nullptr;
    };
    struct Source
    {
        ext_data_control_source_v1 *source = nullptr;
        ClipboardData data;
        std::function<void()> served;
        bool servedOnce = false;
    };

    void dispatch();
    void flush();
    void fail(const QString &why);
    void syncAnchors();
    void createAnchor(wl_output *output, const QString &name);
    void destroyAnchor(Anchor &a);
    KWin::Window *anchorWindow(const Anchor &a) const;
    void applyIcon(const QString &id, IconTarget &t);
    void reapplyIcons();
    void writeToFd(int fd, const QByteArray &bytes, std::function<void()> done);

    LayerScopes *m_scopes;
    QPointer<KWin::ClientConnection> m_connection;
    wl_display *m_display = nullptr;
    wl_registry *m_registry = nullptr;
    wl_compositor *m_compositor = nullptr;
    wl_shm *m_shm = nullptr;
    wl_seat *m_seat = nullptr;
    zwlr_layer_shell_v1 *m_layerShell = nullptr;
    org_kde_plasma_window_management *m_pwm = nullptr;
    ext_data_control_manager_v1 *m_dataControl = nullptr;
    ext_data_control_device_v1 *m_dataDevice = nullptr;
    QHash<uint32_t, wl_output *> m_outputs; // registry name -> output
    QHash<wl_output *, QString> m_outputNames;
    QList<Anchor> m_anchors;
    QHash<QString, IconTarget> m_icons;
    QSocketNotifier *m_readNotifier = nullptr;
    QSocketNotifier *m_writeNotifier = nullptr;
    bool m_dead = false;

    // clipboard state
    QHash<ext_data_control_offer_v1 *, QStringList> m_offers;
    ext_data_control_offer_v1 *m_selection = nullptr;
    std::unique_ptr<Source> m_source;
    QList<ext_data_control_source_v1 *> m_retiredSources;
};

} // namespace Kristall
