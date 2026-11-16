/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    Maps wl_surfaces to their wlr-layer-shell namespace ("scope"). KWin's EffectWindow does not
    expose the namespace and LayerShellV1Window is not an exported class, so we observe
    LayerShellV1Interface::surfaceCreated (exported) and remember each LayerSurfaceV1Interface.
    Surfaces that already existed when the effect was loaded are found by walking the Qt signal
    connections of their window (Qt private API, see the .cpp).
*/
#pragma once

#include <QHash>
#include <QObject>
#include <QPointer>

namespace KWin
{
class EffectWindow;
class LayerSurfaceV1Interface;
class SurfaceInterface;
}

namespace Kristall
{

class SurfaceTracker : public QObject
{
    Q_OBJECT

public:
    explicit SurfaceTracker(QObject *parent = nullptr);

    bool isAvailable() const { return m_available; }
    /// layer-shell namespace of the window's surface, or an empty string
    QString layerNamespace(KWin::EffectWindow *window);

Q_SIGNALS:
    void layerSurfaceCreated(KWin::SurfaceInterface *surface);

private:
    void remember(KWin::LayerSurfaceV1Interface *layerSurface);

    QHash<KWin::SurfaceInterface *, QPointer<KWin::LayerSurfaceV1Interface>> m_layerSurfaces;
    bool m_available = false;
};

} // namespace Kristall
