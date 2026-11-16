/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "surfacetracker.h"
#include "glasslog.h"

#include "effect/effectwindow.h"
#include "wayland/layershell_v1.h"
#include "wayland/surface.h"
#include "wayland_server.h"
#include "window.h"

#include <private/qobject_p.h>
#include <private/qobject_p_p.h>

namespace Kristall
{

SurfaceTracker::SurfaceTracker(QObject *parent)
    : QObject(parent)
{
    KWin::WaylandServer *server = KWin::waylandServer();
    if (!server) {
        return;
    }
    // LayerShellV1Integration (child of WaylandServer) owns the LayerShellV1Interface
    auto *shell = server->findChild<KWin::LayerShellV1Interface *>(QString(), Qt::FindChildrenRecursively);
    if (!shell) {
        qCWarning(KRISTALL_GLASS) << "layer-shell interface not found; namespace matching unavailable";
        return;
    }
    m_available = true;
    connect(shell, &KWin::LayerShellV1Interface::surfaceCreated, this, [this](KWin::LayerSurfaceV1Interface *ls) {
        remember(ls);
        Q_EMIT layerSurfaceCreated(ls->surface());
    });
}

void SurfaceTracker::remember(KWin::LayerSurfaceV1Interface *ls)
{
    KWin::SurfaceInterface *surface = ls->surface();
    m_layerSurfaces.insert(surface, ls);
    connect(ls, &QObject::destroyed, this, [this, surface]() {
        m_layerSurfaces.remove(surface);
    });
}

QString SurfaceTracker::layerNamespace(KWin::EffectWindow *window)
{
    KWin::SurfaceInterface *surface = window->surface();
    if (!surface) {
        return {};
    }
    if (auto it = m_layerSurfaces.constFind(surface); it != m_layerSurfaces.constEnd()) {
        return it->isNull() ? QString() : (*it)->scope();
    }
    // Late load: the layer surface was created before this effect existed. LayerShellV1Window
    // connects several LayerSurfaceV1Interface signals to itself, so the layer surface is among
    // the senders of the window object. Walking that list needs Qt private API (QObjectPrivate);
    // the image always builds us against the exact Qt it ships, so the layout is checked at
    // compile time. Only reached for windows whose class is LayerShellV1Window.
    KWin::Window *w = window->window();
    if (!w || qstrcmp(w->metaObject()->className(), "KWin::LayerShellV1Window") != 0) {
        return {};
    }
    QObjectPrivate *d = QObjectPrivate::get(w);
    QObjectPrivate::ConnectionData *cd = d->connections.loadAcquire();
    if (!cd) {
        return {};
    }
    for (QObjectPrivate::Connection *c = cd->senders; c; c = c->next) {
        if (auto *ls = qobject_cast<KWin::LayerSurfaceV1Interface *>(c->sender)) {
            if (ls->surface() == surface) {
                remember(ls);
                return ls->scope();
            }
        }
    }
    return {};
}

} // namespace Kristall
