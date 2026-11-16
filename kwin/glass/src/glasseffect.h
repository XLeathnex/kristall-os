/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    KWin::Effect for "real Liquid Glass": shapes declared over glass.sock by the shell, and
    default shapes for every surface that asks for background blur (ext-background-effect-v1,
    internal windows, decorations). Replaces KWin's stock blur effect.
*/
#pragma once

#include "glassrenderer.h"
#include "glasssettings.h"
#include "glassshape.h"

#include "core/region.h"
#include "effect/effect.h"

#include <QElapsedTimer>
#include <QHash>
#include <QJsonObject>
#include <QPointer>
#include <QTimer>

#include <memory>
#include <optional>
#include <unordered_map>
#include <vector>

namespace KWin
{
class BackgroundEffectItem;
class EffectWindow;
class RenderView;
}

namespace Kristall
{

class CrashGuard;
class GlassServer;
class GlassSettings;
class SurfaceTracker;

struct ShapeState
{
    float pressed = 0;
    float pressedTarget = 0;
    float scheme = -1; ///< animated 0 (dark glass, light text) .. 1 (light glass, dark text); -1 = unset
    float schemeTarget = 1;
    float glassLuminance = -1;
    qint64 lastFlipMs = 0;
    bool reported = false;
};

/// A shape in window-local logical coordinates with its material resolved.
struct LocalShape
{
    ShapeSpec spec;
    quint64 binding = 0; ///< 0 = automatic shape from a blur request
    QString stateKey;
    ShapeState *state = nullptr;
    QVector4D tint;
    QVector4D material;
    float legibility = 1;
    float chroma = 0.06f;
    float blurRadius = 6; ///< logical px
    float tintLuminance = 1;
    int lumaSlot = -1;
};

class GlassEffect : public KWin::Effect
{
    Q_OBJECT

public:
    GlassEffect();
    ~GlassEffect() override;

    static bool supported();

    void reconfigure(ReconfigureFlags flags) override;
    void prePaintScreen(KWin::ScreenPrePaintData &data) override;
    void prePaintWindow(KWin::RenderView *view, KWin::EffectWindow *w, KWin::WindowPrePaintData &data) override;
    bool drawWindow(const KWin::RenderTarget &renderTarget, const KWin::RenderViewport &viewport, KWin::EffectWindow *w, int mask,
                    const KWin::Region &deviceRegion, KWin::WindowPaintData &data) override;
    void postPaintScreen() override;

    bool provides(Feature feature) override;
    bool isActive() const override;
    int requestedEffectChainPosition() const override { return 20; }
    bool blocksDirectScanout() const override { return false; }
    bool eventFilter(QObject *watched, QEvent *event) override;

private:
    struct ViewState
    {
        std::unique_ptr<GlassRenderer::WindowCache> cache;
        bool backgroundDirty = true;
        bool forceDirty = true;
        QElapsedTimer lastLuma;
    };

    struct GlassWindow
    {
        KWin::EffectWindow *window = nullptr;
        std::vector<quint64> bindings;
        std::optional<KWin::RegionF> blurContent;
        std::optional<KWin::RegionF> blurFrame;
        std::unique_ptr<KWin::BackgroundEffectItem> item;
        QMetaObject::Connection containerConnection;
        QMetaObject::Connection commitConnection;
        QRectF itemRect; ///< window-local logical rect the scene repaints when the background changes
        std::vector<LocalShape> shapes;
        std::unordered_map<QString, ShapeState> states;
        std::unordered_map<KWin::RenderView *, ViewState> views;
        bool dirty = true;
        bool animating = false;
        bool hasAutoClip = false;
        KWin::RegionF autoClip; ///< window-local; app blur regions that are not a single rounded rect

        bool isExplicit() const { return !bindings.empty(); }
    };

    // windows and bindings
    void slotWindowAdded(KWin::EffectWindow *w);
    void slotWindowClosed(KWin::EffectWindow *w);
    void slotWindowDeleted(KWin::EffectWindow *w);
    void slotViewRemoved(KWin::RenderView *view);
    void slotBindingChanged(quint64 id, bool matchChanged);
    void slotBindingRemoved(quint64 id);
    void updateBlurRequest(KWin::EffectWindow *w);
    bool matches(quint64 bindingId, KWin::EffectWindow *w);
    void rematchBinding(quint64 id);
    void reportBindingCounts();
    GlassWindow *ensureGlassWindow(KWin::EffectWindow *w);
    void maybeDropGlassWindow(KWin::EffectWindow *w);
    GlassWindow *glassWindow(KWin::EffectWindow *w);

    // shapes
    void rebuildShapes(GlassWindow &gw);
    void resolveMaterial(LocalShape &shape, bool automatic) const;
    void updateItemGeometry(GlassWindow &gw);
    void scheduleGlassRepaint(GlassWindow &gw);
    void markAllDirty();
    void markBackgroundDirty(const QRectF &globalRect);
    QRectF reachGlobal(const GlassWindow &gw) const;

    // per frame
    bool shouldRender(KWin::EffectWindow *w, int mask, const KWin::WindowPaintData &data) const;
    void buildDeviceGeometry(GlassWindow &gw, const KWin::RenderViewport &viewport, const KWin::WindowPaintData &data);
    void advanceAnimations();
    void pollLegibility();
    void applyLuma(GlassWindow &gw, const std::vector<GlassRenderer::LumaResult> &results);
    QualityTier effectiveQuality() const;
    void publishConfig();
    QJsonObject status() const;
    void reportTiming();

    std::unique_ptr<CrashGuard> m_guard;
    std::unique_ptr<GlassSettings> m_settings;
    std::unique_ptr<GlassServer> m_server;
    std::unique_ptr<SurfaceTracker> m_tracker;
    std::unique_ptr<GlassRenderer> m_renderer;
    std::unordered_map<KWin::EffectWindow *, std::unique_ptr<GlassWindow>> m_windows;
    QHash<KWin::EffectWindow *, QMetaObject::Connection> m_blurConnections;
    bool m_valid = false;

    KWin::RenderView *m_currentView = nullptr;
    std::vector<QRectF> m_frameDirty; ///< global logical rects that changed below the window being painted
    bool m_genericPaint = false;

    QElapsedTimer m_clock;
    qint64 m_lastAnimationMs = -1;
    QTimer m_lumaPoll;
    int m_lumaPollAttempts = 0;

    // scratch, reused every frame
    std::vector<DeviceShape> m_deviceShapes;
    std::vector<DeviceBody> m_deviceBodies;
    std::vector<DeviceCluster> m_deviceClusters;
    std::vector<int> m_scratchIndex;
    std::vector<int> m_members;
    std::vector<DeviceShape> m_orderedShapes;
    std::vector<float> m_bodyBlur;
    std::vector<QRectF> m_clusterRects;
    std::vector<float> m_clusterBlur;
    std::vector<GlassRenderer::LumaResult> m_lumaResults;

    // statistics / debug
    quint64 m_frames = 0;
    quint64 m_glassDraws = 0;
    QElapsedTimer m_timingWindow;
    PassTimes m_timingSum;
    quint64 m_timingFrames = 0;
    PassTimes m_lastTiming;
};

} // namespace Kristall
