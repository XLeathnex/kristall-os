/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-FileCopyrightText: 2010 Fredrik Höglund <fredrik@kde.org> (blur-request handling, see below)
    SPDX-FileCopyrightText: 2018 Alex Nemeth <alex.nemeth329@gmail.com>
    SPDX-License-Identifier: GPL-2.0-or-later

    The collection of blur requests (surface blur region from ext-background-effect-v1, the
    "kwin_blur" property of internal windows, decoration blur regions) and the skip rules in
    shouldRender() follow KWin's blur effect (src/plugins/blur/blur.cpp, KWin 6.8,
    GPL-2.0-or-later). Everything else in this file is original Kristall code.
*/
#include "glasseffect.h"
#include "crashguard.h"
#include "glasslog.h"
#include "glassserver.h"
#include "glasssettings.h"
#include "surfacetracker.h"

#include "core/output.h"
#include "core/outputlayer.h"
#include "core/rendertarget.h"
#include "core/renderviewport.h"
#include "effect/effecthandler.h"
#include "effect/effectwindow.h"
#include "scene/backgroundeffectitem.h"
#include "scene/item.h"
#include "scene/scene.h"
#include "scene/windowitem.h"
#include "wayland/backgroundeffect_v1.h"
#include "wayland/surface.h"
#include "wayland_server.h"
#include "window.h"

#include <KDecoration3/Decoration>

#include <QJsonArray>
#include <QWindow>

#include <algorithm>
#include <cmath>
#include <numbers>

Q_LOGGING_CATEGORY(KRISTALL_GLASS, "kristall.glass", QtInfoMsg)

namespace Kristall
{

using namespace KWin;

namespace
{
constexpr float kChroma = 0.07f; ///< relative dispersion of R/B at the rim (restrained)
constexpr int kLumaIntervalMs = 100; ///< legibility sampling at most 10 Hz per window and output
constexpr int kSchemeDwellMs = 600; ///< minimum time between two scheme flips of a shape
constexpr float kSchemeAnimSeconds = 0.30f;
constexpr float kPressAnimSeconds = 0.12f;
constexpr qreal kGridLogical = 32.0; ///< capture rects snap to this grid so animating shapes reuse the cached blur

float luminance(const QColor &c)
{
    return 0.2126f * float(c.redF()) + 0.7152f * float(c.greenF()) + 0.0722f * float(c.blueF());
}

QRectF snapOut(const QRectF &r, qreal grid)
{
    const qreal x0 = std::floor(r.left() / grid) * grid;
    const qreal y0 = std::floor(r.top() / grid) * grid;
    const qreal x1 = std::ceil(r.right() / grid) * grid;
    const qreal y1 = std::ceil(r.bottom() / grid) * grid;
    return QRectF(x0, y0, x1 - x0, y1 - y0);
}

/// corner extent and exponent of a continuous-curvature corner (see docs/contracts/glass.md)
void cornerShape(double radius, double smoothing, double maxExtent, float &extent, float &exponent)
{
    if (radius <= 0.01) {
        extent = 0;
        exponent = 2;
        return;
    }
    // The smoothed corner starts (1 + smoothing) * radius before the corner (like the common
    // "corner smoothing" control); its 45° point sits where a circular corner of `radius` would.
    const double R = std::min(radius * (1.0 + smoothing), maxExtent);
    const double k = std::max(1.0, R / radius);
    const double v = 1.0 - (std::numbers::sqrt2 - 1.0) / (std::numbers::sqrt2 * k);
    extent = float(R);
    exponent = float(std::clamp(-std::numbers::ln2 / std::log(v), 2.0, 8.0));
}

bool itemTreeHasRepaints(Item *item, RenderView *view)
{
    if (item->hasRepaints(view)) {
        return true;
    }
    const auto children = item->childItems();
    for (Item *child : children) {
        if (itemTreeHasRepaints(child, view)) {
            return true;
        }
    }
    return false;
}
} // namespace

bool GlassEffect::supported()
{
    return effects->isOpenGLCompositing();
}

GlassEffect::GlassEffect()
{
#ifdef KRISTALL_GLASS_TEST_BROKEN
    // test build: an unresolved *data* symbol (functions would be bound lazily and crash
    // instead) makes dlopen fail, like a plugin built against a different KWin
    extern int kristall_glass_symbol_that_does_not_exist;
    m_frames = quint64(kristall_glass_symbol_that_does_not_exist);
#endif
    m_clock.start();
    m_guard = std::make_unique<CrashGuard>();
    m_settings = std::make_unique<GlassSettings>();
    m_server = std::make_unique<GlassServer>();
    m_server->statusProvider = [this]() {
        return status();
    };
    m_server->listen();

    if (m_guard->tripped()) {
        m_server->setState(QStringLiteral("disabled"), QStringLiteral("crash-guard"));
        publishConfig();
        return;
    }
    if (qEnvironmentVariableIntValue("KRISTALL_GLASS_TEST_CRASH") != 0) {
        qCCritical(KRISTALL_GLASS) << "KRISTALL_GLASS_TEST_CRASH set: aborting on purpose";
        std::abort();
    }

    effects->makeOpenGLContextCurrent();
    m_renderer = std::make_unique<GlassRenderer>();
    if (!m_renderer->init()) {
        qCCritical(KRISTALL_GLASS) << "glass disabled:" << m_renderer->error();
        m_server->setState(QStringLiteral("failed"), m_renderer->error());
        publishConfig();
        return;
    }
    m_tracker = std::make_unique<SurfaceTracker>();

    connect(m_settings.get(), &GlassSettings::changed, this, [this]() {
        markAllDirty();
        publishConfig();
    });
    connect(m_server.get(), &GlassServer::bindingChanged, this, &GlassEffect::slotBindingChanged);
    connect(m_server.get(), &GlassServer::bindingRemoved, this, &GlassEffect::slotBindingRemoved);
    connect(m_server.get(), &GlassServer::qualityHintChanged, this, [this]() {
        markAllDirty();
        publishConfig();
    });
    connect(m_server.get(), &GlassServer::debugChanged, this, [this]() {
        m_timingWindow.invalidate();
        markAllDirty();
    });

    m_lumaPoll.setSingleShot(true);
    m_lumaPoll.setInterval(16);
    connect(&m_lumaPoll, &QTimer::timeout, this, &GlassEffect::pollLegibility);

    // We provide the material for blur requests; advertise the capability KWin's blur would.
    waylandServer()->backgroundEffectManager()->addBlurCapability();

    connect(effects, &EffectsHandler::windowAdded, this, &GlassEffect::slotWindowAdded);
    connect(effects, &EffectsHandler::windowClosed, this, &GlassEffect::slotWindowClosed);
    connect(effects, &EffectsHandler::windowDeleted, this, &GlassEffect::slotWindowDeleted);
    connect(effects, &EffectsHandler::viewRemoved, this, &GlassEffect::slotViewRemoved);
    connect(effects, &EffectsHandler::stackingOrderChanged, this, [this]() {
        for (auto &[w, gw] : m_windows) {
            for (auto &[view, vs] : gw->views) {
                vs.forceDirty = true;
            }
        }
    });
    if (m_tracker) {
        // a namespace can only be known after the layer surface exists; windows appear later
        connect(m_tracker.get(), &SurfaceTracker::layerSurfaceCreated, this, [](SurfaceInterface *) { });
    }

    const auto stacking = effects->stackingOrder();
    for (EffectWindow *w : stacking) {
        slotWindowAdded(w);
    }
    m_valid = true;
    m_server->setState(QStringLiteral("active"), QString());
    publishConfig();
    qCInfo(KRISTALL_GLASS) << "Liquid Glass active; socket" << m_server->socketPath();
}

GlassEffect::~GlassEffect()
{
    if (m_valid) {
        waylandServer()->backgroundEffectManager()->removeBlurCapability();
    }
    effects->makeOpenGLContextCurrent();
    m_windows.clear();
    m_renderer.reset();
    m_server.reset(); // closes the socket: clients fall back immediately
}

void GlassEffect::reconfigure(ReconfigureFlags)
{
    markAllDirty();
}

bool GlassEffect::provides(Feature feature)
{
    return feature == Blur || Effect::provides(feature);
}

bool GlassEffect::isActive() const
{
    return m_valid && !m_windows.empty() && !effects->isScreenLocked();
}

QualityTier GlassEffect::effectiveQuality() const
{
    const QString setting = m_settings->qualitySetting();
    if (setting == QLatin1String("high")) {
        return QualityTier::High;
    }
    if (setting == QLatin1String("efficient")) {
        return QualityTier::Efficient;
    }
    if (const auto hint = m_server->qualityHint()) {
        return *hint == QLatin1String("efficient") ? QualityTier::Efficient : QualityTier::High;
    }
    return m_settings->onBattery().value_or(false) ? QualityTier::Efficient : QualityTier::High;
}

void GlassEffect::publishConfig()
{
    m_server->setEffectiveConfig({
        {QStringLiteral("quality"), effectiveQuality() == QualityTier::High ? QStringLiteral("high") : QStringLiteral("efficient")},
        {QStringLiteral("qualitySetting"), m_settings->qualitySetting()},
        {QStringLiteral("theme"), m_settings->darkTheme() ? QStringLiteral("dark") : QStringLiteral("light")},
        {QStringLiteral("glass"), m_settings->glass()},
        {QStringLiteral("reduceTransparency"), m_settings->reduceTransparency()},
        {QStringLiteral("legibility"), m_renderer && m_renderer->supportsLegibility()},
    });
}

// ---------------------------------------------------------------------------------------------
// windows, blur requests, bindings
// ---------------------------------------------------------------------------------------------

GlassEffect::GlassWindow *GlassEffect::glassWindow(EffectWindow *w)
{
    auto it = m_windows.find(w);
    return it == m_windows.end() ? nullptr : it->second.get();
}

GlassEffect::GlassWindow *GlassEffect::ensureGlassWindow(EffectWindow *w)
{
    if (auto gw = glassWindow(w)) {
        return gw;
    }
    auto gw = std::make_unique<GlassWindow>();
    gw->window = w;
    gw->item = std::make_unique<BackgroundEffectItem>(w->windowItem());
    BackgroundEffectItem *item = gw->item.get();
    GlassWindow *raw = gw.get();
    // BackgroundEffectItem clips its geometry to the window, but refraction and blur read
    // beyond the window's edge (e.g. below a menu bar). Re-apply the full reach rect after
    // KWin's own clip, which runs first because it connected first.
    gw->containerConnection = connect(w->windowItem()->windowContainer(), &Item::boundingRectChanged, this, [item, raw]() {
        item->setGeometry(raw->itemRect);
    });
    if (SurfaceInterface *surface = w->surface()) {
        gw->commitConnection = connect(surface, &SurfaceInterface::committed, this, [this, raw]() {
            for (quint64 id : raw->bindings) {
                m_server->surfaceCommitted(id);
            }
        });
    }
    auto [it, inserted] = m_windows.emplace(w, std::move(gw));
    return it->second.get();
}

void GlassEffect::maybeDropGlassWindow(EffectWindow *w)
{
    auto it = m_windows.find(w);
    if (it == m_windows.end()) {
        return;
    }
    GlassWindow &gw = *it->second;
    if (!gw.bindings.empty() || gw.blurContent.has_value() || gw.blurFrame.has_value()) {
        return;
    }
    scheduleGlassRepaint(gw);
    disconnect(gw.containerConnection);
    disconnect(gw.commitConnection);
    effects->makeOpenGLContextCurrent();
    m_windows.erase(it);
}

void GlassEffect::slotWindowAdded(EffectWindow *w)
{
    if (SurfaceInterface *surface = w->surface()) {
        m_blurConnections[w] = connect(surface, &SurfaceInterface::blurChanged, this, [this, w]() {
            updateBlurRequest(w);
        });
    }
    if (QWindow *internal = w->internalWindow()) {
        internal->installEventFilter(this);
    }
    const auto connectDecoration = [this, w]() {
        if (w->decoration()) {
            connect(w->decoration(), &KDecoration3::Decoration::blurRegionChanged, this, [this, w]() {
                updateBlurRequest(w);
            });
        }
    };
    connectDecoration();
    connect(w, &EffectWindow::windowDecorationChanged, this, [this, w, connectDecoration]() {
        connectDecoration();
        updateBlurRequest(w);
    });
    connect(w, &EffectWindow::windowFrameGeometryChanged, this, [this](EffectWindow *window, const RectF &old) {
        // the vacated area changes the background of glass that refracts it
        markBackgroundDirty(QRectF(old).adjusted(-64, -64, 64, 64));
        markBackgroundDirty(QRectF(window->expandedGeometry()));
        if (GlassWindow *gw = glassWindow(window)) {
            for (auto &[view, vs] : gw->views) {
                vs.forceDirty = true;
            }
        }
    });
    connect(w, &EffectWindow::windowHiddenChanged, this, [this](EffectWindow *window) {
        markBackgroundDirty(QRectF(window->expandedGeometry()));
    });
    connect(w, &EffectWindow::minimizedChanged, this, [this](EffectWindow *window) {
        markBackgroundDirty(QRectF(window->expandedGeometry()));
    });
    connect(w, &EffectWindow::windowOpacityChanged, this, [this](EffectWindow *window, qreal, qreal) {
        markBackgroundDirty(QRectF(window->expandedGeometry()));
    });

    markBackgroundDirty(QRectF(w->expandedGeometry()));
    updateBlurRequest(w);

    bool changed = false;
    for (quint64 id : m_server->bindingIds()) {
        if (matches(id, w)) {
            GlassWindow *gw = ensureGlassWindow(w);
            if (std::find(gw->bindings.begin(), gw->bindings.end(), id) == gw->bindings.end()) {
                gw->bindings.push_back(id);
                gw->dirty = true;
                changed = true;
            }
        }
    }
    if (changed) {
        scheduleGlassRepaint(*glassWindow(w));
        reportBindingCounts();
    }
}

void GlassEffect::slotWindowClosed(EffectWindow *w)
{
    markBackgroundDirty(QRectF(w->expandedGeometry()));
    if (GlassWindow *gw = glassWindow(w); gw && !gw->bindings.empty()) {
        // keep drawing during the close animation, but the client's surface is gone
        reportBindingCounts();
    }
}

void GlassEffect::slotWindowDeleted(EffectWindow *w)
{
    markBackgroundDirty(QRectF(w->expandedGeometry()));
    if (auto it = m_windows.find(w); it != m_windows.end()) {
        disconnect(it->second->containerConnection);
        disconnect(it->second->commitConnection);
        effects->makeOpenGLContextCurrent();
        const bool hadBindings = !it->second->bindings.empty();
        m_windows.erase(it);
        if (hadBindings) {
            reportBindingCounts();
        }
    }
    if (auto it = m_blurConnections.find(w); it != m_blurConnections.end()) {
        disconnect(*it);
        m_blurConnections.erase(it);
    }
}

void GlassEffect::slotViewRemoved(RenderView *view)
{
    effects->makeOpenGLContextCurrent();
    for (auto &[w, gw] : m_windows) {
        gw->views.erase(view);
    }
}

bool GlassEffect::eventFilter(QObject *watched, QEvent *event)
{
    auto internal = qobject_cast<QWindow *>(watched);
    if (internal && event->type() == QEvent::DynamicPropertyChange) {
        auto *pe = static_cast<QDynamicPropertyChangeEvent *>(event);
        if (pe->propertyName() == "kwin_blur") {
            if (EffectWindow *w = effects->findWindow(internal)) {
                updateBlurRequest(w);
            }
        }
    }
    return false;
}

void GlassEffect::updateBlurRequest(EffectWindow *w)
{
    // Derived from BlurEffect::updateBlurRegion (KWin 6.8): the same three request sources.
    std::optional<RegionF> content;
    std::optional<RegionF> frame;
    if (SurfaceInterface *surface = w->surface()) {
        if (!surface->blurRegion().isEmpty()) {
            content = surface->blurRegion();
        }
    }
    if (QWindow *internal = w->internalWindow()) {
        const QVariant property = internal->property("kwin_blur");
        if (property.isValid()) {
            content = property.value<RegionF>();
        }
    }
    if (w->decorationHasAlpha() && w->decoration() && !w->decoration()->blurRegion().isNull()) {
        const RegionF decorationRegion = RegionF(RectF(w->decoration()->rect())) - RegionF(w->contentsRect());
        frame = decorationRegion.intersected(RegionF(RectF(w->decoration()->blurRegion().boundingRect())));
    }

    GlassWindow *gw = glassWindow(w);
    if (!content && !frame && !gw) {
        return;
    }
    if (!gw) {
        gw = ensureGlassWindow(w);
    }
    if (gw->blurContent != content || gw->blurFrame != frame) {
        gw->blurContent = content;
        gw->blurFrame = frame;
        gw->dirty = true;
        scheduleGlassRepaint(*gw);
    }
    maybeDropGlassWindow(w);
}

bool GlassEffect::matches(quint64 bindingId, EffectWindow *w)
{
    const SurfaceBinding *b = m_server->binding(bindingId);
    if (!b || w->isDeleted() || !w->surface()) {
        return false;
    }
    const SurfaceMatch &m = b->match;
    const qint64 wantPid = m.pid < 0 ? b->peerPid : m.pid;
    if (wantPid > 0 && w->pid() != wantPid) {
        return false;
    }
    if (!m.layerNamespace.isEmpty() && (!m_tracker || m_tracker->layerNamespace(w) != m.layerNamespace)) {
        return false;
    }
    if (!m.appId.isEmpty() && w->windowClass().section(QLatin1Char(' '), 1).compare(m.appId, Qt::CaseInsensitive) != 0) {
        return false;
    }
    if (!m.title.isEmpty() && w->caption() != m.title) {
        return false;
    }
    if (!m.output.isEmpty() && (!w->screen() || w->screen()->name() != m.output)) {
        return false;
    }
    return true;
}

void GlassEffect::rematchBinding(quint64 id)
{
    const auto stacking = effects->stackingOrder();
    for (EffectWindow *w : stacking) {
        const bool match = matches(id, w);
        GlassWindow *gw = glassWindow(w);
        const bool has = gw && std::find(gw->bindings.begin(), gw->bindings.end(), id) != gw->bindings.end();
        if (match && !has) {
            gw = ensureGlassWindow(w);
            gw->bindings.push_back(id);
            gw->dirty = true;
            scheduleGlassRepaint(*gw);
        } else if (!match && has) {
            std::erase(gw->bindings, id);
            gw->dirty = true;
            scheduleGlassRepaint(*gw);
            maybeDropGlassWindow(w);
        }
    }
}

void GlassEffect::reportBindingCounts()
{
    for (quint64 id : m_server->bindingIds()) {
        int count = 0;
        for (const auto &[w, gw] : m_windows) {
            if (!w->isDeleted() && std::find(gw->bindings.begin(), gw->bindings.end(), id) != gw->bindings.end()) {
                ++count;
            }
        }
        m_server->setBoundWindows(id, count);
    }
}

void GlassEffect::slotBindingChanged(quint64 id, bool matchChanged)
{
    if (matchChanged) {
        rematchBinding(id);
        reportBindingCounts();
    }
    for (auto &[w, gw] : m_windows) {
        if (std::find(gw->bindings.begin(), gw->bindings.end(), id) != gw->bindings.end()) {
            gw->dirty = true;
            scheduleGlassRepaint(*gw);
        }
    }
}

void GlassEffect::slotBindingRemoved(quint64 id)
{
    std::vector<EffectWindow *> affected;
    for (auto &[w, gw] : m_windows) {
        if (std::erase(gw->bindings, id) > 0) {
            gw->dirty = true;
            scheduleGlassRepaint(*gw);
            affected.push_back(w);
        }
    }
    for (EffectWindow *w : affected) {
        maybeDropGlassWindow(w);
    }
}

// ---------------------------------------------------------------------------------------------
// shapes and materials
// ---------------------------------------------------------------------------------------------

void GlassEffect::resolveMaterial(LocalShape &shape, bool automatic) const
{
    const double s = m_settings->glass();
    const bool dark = m_settings->darkTheme();
    const bool clear = shape.spec.variant == Variant::Clear;

    // theme tint; strength follows the owner's slider (0 ultra-clear .. 1 fully tinted)
    QColor tintColor = dark ? QColor::fromRgbF(0.11, 0.11, 0.13) : QColor::fromRgbF(0.98, 0.98, 0.99);
    double amount = dark ? 0.16 + 0.68 * s : 0.10 + 0.72 * s;
    double blur = 2.0 + 8.0 * s;
    double blurMix = 1.0;
    double saturation = 1.30;
    double legibility = 1.0;
    if (clear) {
        amount *= 0.40;
        blur = 1.0 + 2.0 * s;
        blurMix = 0.40;
        saturation = 1.12;
        legibility = 0.5;
    }
    if (shape.spec.tintAmount) {
        amount = *shape.spec.tintAmount;
    }
    if (shape.spec.tint) {
        tintColor = *shape.spec.tint;
        amount = shape.spec.tintAmount.value_or(std::max(0.35, amount)) * shape.spec.tint->alphaF();
        tintColor.setAlphaF(1.0);
    }
    if (automatic) {
        // app-requested blur: the app draws its own (often translucent) background on top
        amount *= 0.6;
    }
    shape.tint = QVector4D(tintColor.redF(), tintColor.greenF(), tintColor.blueF(), float(std::clamp(amount, 0.0, 1.0)));
    shape.tintLuminance = luminance(tintColor);
    const double specular = dark ? 0.62 : 0.80;
    const double innerShadow = dark ? 0.20 : 0.10;
    shape.material = QVector4D(blurMix, saturation, specular, innerShadow);
    shape.legibility = legibility;
    shape.chroma = kChroma;
    shape.blurRadius = blur;
}

void GlassEffect::rebuildShapes(GlassWindow &gw)
{
    gw.dirty = false;
    gw.shapes.clear();
    gw.hasAutoClip = false;
    EffectWindow *w = gw.window;
    // surface-local -> window-local (frame relative): differs for server-side decorations and
    // client-side shadows
    const QPointF surfaceOffset = w->bufferGeometry().topLeft() - w->frameGeometry().topLeft();

    std::unordered_map<QString, ShapeState> states;
    int slot = 0;
    if (gw.isExplicit()) {
        for (quint64 id : gw.bindings) {
            const SurfaceBinding *b = m_server->binding(id);
            if (!b) {
                continue;
            }
            for (const ShapeSpec &spec : b->shapes) {
                if (spec.rect.isEmpty() || spec.opacity <= 0.0) {
                    continue;
                }
                LocalShape ls;
                ls.spec = spec;
                ls.spec.rect.translate(surfaceOffset);
                if (ls.spec.pointer) {
                    *ls.spec.pointer += surfaceOffset;
                }
                ls.binding = id;
                resolveMaterial(ls, false);
                if (slot < GlassRenderer::kLumaSlots) {
                    ls.lumaSlot = slot++;
                }
                const QString key = QString::number(id) + QLatin1Char('/') + spec.id;
                auto old = gw.states.find(key);
                ShapeState st = old != gw.states.end() ? old->second : ShapeState{};
                st.pressedTarget = spec.pressed ? 1.0f : 0.0f;
                states.emplace(key, st);
                ls.stateKey = key;
                gw.shapes.push_back(std::move(ls));
            }
        }
    } else {
        // automatic shape for a blur request: one rounded rect over the requested area
        RegionF region;
        if (gw.blurContent) {
            if (gw.blurContent->isEmpty()) {
                region = RegionF(w->contentsRect());
            } else if (w->decoration()) {
                region = gw.blurContent->translated(w->contentsRect().topLeft()) & RegionF(w->contentsRect());
            } else {
                region = *gw.blurContent & RegionF(w->contentsRect());
            }
        }
        if (gw.blurFrame) {
            region += *gw.blurFrame;
        }
        if (!region.isEmpty()) {
            const RectF bounds = region.boundingRect();
            double radius = 0;
            const BorderRadius br = w->window()->borderRadius();
            if (!br.isNull()) {
                radius = std::max({br.topLeft(), br.topRight(), br.bottomLeft(), br.bottomRight()});
            } else {
                // infer rounded corners from a stair-stepped region (e.g. Breeze menus)
                for (const RectF &r : region.rects()) {
                    if (r.left() > bounds.left() + 0.01 && r.top() < bounds.top() + bounds.height() / 2) {
                        radius = std::max(radius, r.bottom() - bounds.top());
                    }
                }
            }
            double area = 0;
            for (const RectF &r : region.rects()) {
                area += r.width() * r.height();
            }
            const double boundsArea = bounds.width() * bounds.height();
            if (area < boundsArea * 0.9 - 4.0 * radius * radius) {
                // not a rounded rect: draw the material clipped to the region, lens on the bounds
                gw.hasAutoClip = true;
                gw.autoClip = region;
            }
            LocalShape ls;
            ls.spec.id = QStringLiteral("auto");
            ls.spec.rect = QRectF(bounds);
            ls.spec.radius = std::min(radius, std::min(bounds.width(), bounds.height()) / 2);
            ls.spec.smoothing = 0.0;
            const double minSide = std::min(bounds.width(), bounds.height());
            ls.spec.bezel = std::clamp(0.12 * minSide, 3.0, 14.0);
            ls.spec.depth = *ls.spec.bezel * 0.4;
            resolveMaterial(ls, true);
            const QString key = QStringLiteral("auto");
            auto old = gw.states.find(key);
            states.emplace(key, old != gw.states.end() ? old->second : ShapeState{});
            ls.stateKey = key;
            gw.shapes.push_back(std::move(ls));
        }
    }
    gw.states = std::move(states);
    // resolve state pointers (node-based map: addresses stay valid until the next rebuild)
    for (LocalShape &ls : gw.shapes) {
        ls.state = &gw.states[ls.stateKey];
    }
    const bool darkTheme = m_settings->darkTheme();
    for (LocalShape &ls : gw.shapes) {
        if (ls.state->scheme < 0) {
            ls.state->scheme = ls.state->schemeTarget = darkTheme ? 0.0f : 1.0f;
        }
        if (ls.binding == 0) {
            // apps choose their own text colour: follow the theme, never adapt
            ls.state->schemeTarget = darkTheme ? 0.0f : 1.0f;
        }
    }
    updateItemGeometry(gw);
    gw.animating = true; // let advanceAnimations() settle any new targets
}

void GlassEffect::updateItemGeometry(GlassWindow &gw)
{
    QRectF rect;
    for (const LocalShape &ls : gw.shapes) {
        // lens depth + chroma, blur reach (generously: three blur radii) and the snapping grid
        const double reach = ls.spec.effectiveDepth() * (1.0 + kChroma) + 3.0 * ls.blurRadius + 4.0;
        rect |= ls.spec.rect.adjusted(-reach, -reach, reach, reach);
    }
    if (!rect.isEmpty()) {
        const QPointF origin = gw.window->pos();
        rect = snapOut(rect.translated(origin), kGridLogical).adjusted(-kGridLogical, -kGridLogical, kGridLogical, kGridLogical).translated(-origin);
    }
    gw.itemRect = rect;
    gw.item->setEffectBoundingRect(RectF(rect));
    gw.item->setGeometry(RectF(rect)); // undo the clip to the window rect, see ensureGlassWindow
    float maxBlur = 0;
    for (const LocalShape &ls : gw.shapes) {
        maxBlur = std::max(maxBlur, ls.blurRadius);
    }
    gw.item->setPixelsToExpandRepaintsBelowOpaqueRegions(uint32_t(std::ceil(blurParamsFor(maxBlur * 2.0f).reach)));
}

QRectF GlassEffect::reachGlobal(const GlassWindow &gw) const
{
    return gw.itemRect.translated(gw.window->pos());
}

void GlassEffect::scheduleGlassRepaint(GlassWindow &gw)
{
    // Repaint through the window's own item, not the layer: our own requests must not look
    // like a background change (see prePaintWindow), otherwise the cached blur would be lost
    // on every shape update.
    const QRectF old = gw.itemRect;
    if (gw.dirty) {
        rebuildShapes(gw);
    }
    const QRectF now = gw.itemRect;
    const QRectF both = old.isEmpty() ? now : (now.isEmpty() ? old : old.united(now));
    if (!both.isEmpty()) {
        gw.window->addRepaint(RectF(both));
    }
}

void GlassEffect::markAllDirty()
{
    for (auto &[w, gw] : m_windows) {
        gw->dirty = true;
        for (auto &[view, vs] : gw->views) {
            vs.forceDirty = true;
        }
        scheduleGlassRepaint(*gw);
    }
}

void GlassEffect::markBackgroundDirty(const QRectF &globalRect)
{
    for (auto &[w, gw] : m_windows) {
        if (reachGlobal(*gw).intersects(globalRect)) {
            for (auto &[view, vs] : gw->views) {
                vs.forceDirty = true;
            }
        }
    }
}

// ---------------------------------------------------------------------------------------------
// painting
// ---------------------------------------------------------------------------------------------

void GlassEffect::prePaintScreen(ScreenPrePaintData &data)
{
    m_currentView = data.view;
    m_frames++;
    advanceAnimations();
    effects->prePaintScreen(data);
    m_genericPaint = data.mask & (PAINT_SCREEN_TRANSFORMED | PAINT_SCREEN_WITH_TRANSFORMED_WINDOWS);

    // Repaints other effects requested on the output layer count as background changes.
    m_frameDirty.clear();
    if (data.view && data.view->layer()) {
        const Region layerDamage = data.view->layer()->deviceRepaints();
        if (!layerDamage.isEmpty()) {
            const QRectF b = QRectF(QRect(layerDamage.boundingRect()));
            const qreal scale = data.view->scale();
            const QPointF origin = data.view->viewport().topLeft();
            m_frameDirty.push_back(QRectF(b.topLeft() / scale + origin, b.size() / scale));
        }
    }
}

void GlassEffect::prePaintWindow(RenderView *view, EffectWindow *w, WindowPrePaintData &data)
{
    effects->prePaintWindow(view, w, data);

    // Windows are visited bottom to top. Everything below a glass window that has pending
    // repaints in this frame is a background change for it; nothing else is.
    if (GlassWindow *gw = glassWindow(w)) {
        ViewState &vs = gw->views[view];
        bool dirty = m_genericPaint || vs.forceDirty || (data.mask & PAINT_WINDOW_TRANSFORMED);
        if (!dirty) {
            const QRectF reach = reachGlobal(*gw);
            for (const QRectF &r : m_frameDirty) {
                if (r.intersects(reach)) {
                    dirty = true;
                    break;
                }
            }
        }
        vs.backgroundDirty = dirty;
        vs.forceDirty = false;
    }
    if (itemTreeHasRepaints(w->windowItem(), view)) {
        m_frameDirty.push_back(QRectF(w->expandedGeometry()));
    }
}

bool GlassEffect::shouldRender(EffectWindow *w, int mask, const WindowPaintData &data) const
{
    if (effects->activeFullScreenEffect() && !w->data(WindowForceBlurRole).toBool()) {
        return false;
    }
    if (w->isDesktop()) {
        return false;
    }
    // Scale, translation and opacity are applied to the shapes; rotations and 3D transforms
    // (e.g. the cube) are not supported and simply show the window without glass.
    if (!qFuzzyIsNull(data.rotationAngle()) || !qFuzzyIsNull(data.zTranslation())) {
        return false;
    }
    Q_UNUSED(mask);
    return true;
}

void GlassEffect::buildDeviceGeometry(GlassWindow &gw, const RenderViewport &viewport, const WindowPaintData &data)
{
    m_deviceShapes.clear();
    m_deviceBodies.clear();
    m_deviceClusters.clear();

    const qreal scale = viewport.scale();
    const qreal xs = data.xScale();
    const qreal ys = data.yScale();
    const QPointF origin = gw.window->pos() + QPointF(data.xTranslation(), data.yTranslation());
    const qreal unit = std::min(xs, ys) * scale; // device px per window-local logical px
    const QPointF offsetPx = origin * scale;
    const auto toDevice = [&](const QPointF &p) {
        return QPointF(offsetPx.x() + p.x() * xs * scale, offsetPx.y() + p.y() * ys * scale);
    };

    // 1. shapes
    for (const LocalShape &ls : gw.shapes) {
        const ShapeSpec &spec = ls.spec;
        const QRectF dev(toDevice(spec.rect.topLeft()), toDevice(spec.rect.bottomRight()));
        DeviceShape ds;
        const QPointF c = dev.center();
        const float hx = float(dev.width() / 2), hy = float(dev.height() / 2);
        ds.geom = QVector4D(float(c.x()), float(c.y()), hx, hy);
        float extent, exponent;
        cornerShape(spec.effectiveRadius() * unit, spec.effectiveSmoothing(), std::min(hx, hy), extent, exponent);
        ds.corner = QVector4D(extent, exponent, 1.0f / exponent, 0.0f);
        const float bezel = float(std::min<double>(spec.effectiveBezel() * unit, std::min(hx, hy)));
        ds.lens = QVector4D(bezel, float(spec.effectiveDepth() * unit), ls.state->pressed, float(spec.opacity));
        ds.tint = ls.tint;
        ds.material = ls.material;
        float sigma = 0;
        QPointF pointer;
        if (spec.pointer) {
            pointer = toDevice(*spec.pointer);
            sigma = 0.55f * std::max(8.0f, std::min(hx, hy));
        }
        ds.extra = QVector4D(float(pointer.x()), float(pointer.y()), sigma, ls.state->scheme);
        ds.extra2 = QVector4D(ls.legibility, ls.chroma, 0, 0);
        ds.bounds = dev;
        ds.lumaSlot = ls.binding != 0 ? ls.lumaSlot : -1;
        m_deviceShapes.push_back(ds);
    }

    // 2. bodies: shapes of one group that come within `merge` of each other merge smoothly
    const int n = int(m_deviceShapes.size());
    m_scratchIndex.assign(n, -1); // body index per shape
    m_orderedShapes.clear(); // shapes reordered so that every body is contiguous
    m_bodyBlur.clear();
    for (int i = 0; i < n; ++i) {
        if (m_scratchIndex[i] >= 0) {
            continue;
        }
        const int bodyIndex = int(m_deviceBodies.size());
        const QString &group = gw.shapes[i].spec.group;
        m_members.clear();
        m_members.push_back(i);
        m_scratchIndex[i] = bodyIndex;
        if (!group.isEmpty()) {
            // flood fill: shapes of the same group within `merge` of any member join the body
            for (size_t m = 0; m < m_members.size() && m_members.size() < size_t(GlassRenderer::kMaxShapesPerBody); ++m) {
                const int a = m_members[m];
                for (int j = 0; j < n && m_members.size() < size_t(GlassRenderer::kMaxShapesPerBody); ++j) {
                    if (m_scratchIndex[j] >= 0 || gw.shapes[j].spec.group != group) {
                        continue;
                    }
                    const float k = float(std::max(gw.shapes[a].spec.merge, gw.shapes[j].spec.merge) * unit);
                    if (m_deviceShapes[a].bounds.adjusted(-k, -k, k, k).intersects(m_deviceShapes[j].bounds)) {
                        m_scratchIndex[j] = bodyIndex;
                        m_members.push_back(j);
                    }
                }
            }
        }
        DeviceBody body;
        body.first = int(m_orderedShapes.size());
        body.count = int(m_members.size());
        QRectF bounds;
        float k = 0;
        float blur = 0;
        for (int idx : m_members) {
            m_orderedShapes.push_back(m_deviceShapes[idx]);
            bounds |= m_deviceShapes[idx].bounds;
            blur = std::max(blur, float(gw.shapes[idx].blurRadius * unit));
            if (m_members.size() > 1) {
                k = std::max(k, float(gw.shapes[idx].spec.merge * unit));
            }
        }
        body.mergeK = k;
        body.bounds = bounds.adjusted(-2, -2, 2, 2);
        m_deviceBodies.push_back(body);
        m_bodyBlur.push_back(blur);
    }
    m_deviceShapes.swap(m_orderedShapes);

    // 3. capture clusters: bodies whose reach overlaps share one capture and one blur chain
    const QRectF viewRect = QRectF(QRect(viewport.scaledRenderRect()));
    m_clusterRects.clear();
    m_clusterBlur.clear();
    for (size_t b = 0; b < m_deviceBodies.size(); ++b) {
        DeviceBody &body = m_deviceBodies[b];
        float depth = 0;
        for (int k = 0; k < body.count; ++k) {
            // pressed shapes refract up to 35% deeper
            depth = std::max(depth, m_deviceShapes[body.first + k].lens.y() * 1.35f * (1.0f + kChroma));
        }
        const float r = depth + 2.0f + blurParamsFor(m_bodyBlur[b]).reach;
        const QRectF reach = body.bounds.adjusted(-r, -r, r, r);
        int target = -1;
        for (size_t c = 0; c < m_clusterRects.size(); ++c) {
            if (m_clusterRects[c].intersects(reach)) {
                target = int(c);
                break;
            }
        }
        if (target < 0) {
            target = int(m_clusterRects.size());
            m_clusterRects.push_back(reach);
            m_clusterBlur.push_back(m_bodyBlur[b]);
        } else {
            m_clusterRects[target] |= reach;
            m_clusterBlur[target] = std::max(m_clusterBlur[target], m_bodyBlur[b]);
        }
        body.cluster = target;
    }
    // growing a cluster can make it overlap an earlier one; fold until stable (few clusters)
    for (bool merged = true; merged;) {
        merged = false;
        for (size_t a = 0; a < m_clusterRects.size() && !merged; ++a) {
            for (size_t c = a + 1; c < m_clusterRects.size() && !merged; ++c) {
                if (!m_clusterRects[a].intersects(m_clusterRects[c])) {
                    continue;
                }
                m_clusterRects[a] |= m_clusterRects[c];
                m_clusterBlur[a] = std::max(m_clusterBlur[a], m_clusterBlur[c]);
                for (DeviceBody &body : m_deviceBodies) {
                    if (body.cluster == int(c)) {
                        body.cluster = int(a);
                    } else if (body.cluster > int(c)) {
                        --body.cluster;
                    }
                }
                m_clusterRects.erase(m_clusterRects.begin() + c);
                m_clusterBlur.erase(m_clusterBlur.begin() + c);
                merged = true;
            }
        }
    }
    // Snap capture rects to a coarse grid: a Dock that magnifies or a capsule that morphs keeps
    // the same capture rect, so its cached blur stays valid while only the shape changes.
    const qreal grid = kGridLogical * scale;
    for (size_t c = 0; c < m_clusterRects.size(); ++c) {
        DeviceCluster cl;
        const QRectF snapped = snapOut(m_clusterRects[c], grid).intersected(viewRect);
        cl.captureRect = snapped.isEmpty() ? Rect() : Rect(snapped.toAlignedRect());
        cl.blurRadius = m_clusterBlur[c];
        m_deviceClusters.push_back(cl);
    }
    for (DeviceBody &body : m_deviceBodies) {
        if (m_deviceClusters[body.cluster].captureRect.isEmpty()) {
            body.count = 0; // entirely off this output
        }
    }
}

bool GlassEffect::drawWindow(const RenderTarget &renderTarget, const RenderViewport &viewport, EffectWindow *w, int mask,
                             const Region &deviceRegion, WindowPaintData &data)
{
    GlassWindow *gw = m_valid ? glassWindow(w) : nullptr;
    if (gw && shouldRender(w, mask, data)) {
        if (gw->dirty) {
            rebuildShapes(*gw);
        }
        if (!gw->shapes.empty()) {
            ViewState &vs = gw->views[m_currentView];
            if (!vs.cache) {
                vs.cache = std::make_unique<GlassRenderer::WindowCache>();
            }
            buildDeviceGeometry(*gw, viewport, data);
            // remove empty bodies (off-view)
            std::erase_if(m_deviceBodies, [](const DeviceBody &b) {
                return b.count == 0;
            });

            FrameParams params;
            const QualityTier tier = effectiveQuality();
            params.mode = tier == QualityTier::Efficient ? FrameParams::Efficient : FrameParams::High;
            if (m_settings->reduceTransparency()) {
                params.mode = FrameParams::ReduceTransparency;
                params.opaqueColor = m_settings->darkTheme() ? QVector3D(0.16f, 0.16f, 0.18f) : QVector3D(0.94f, 0.94f, 0.95f);
            }
            if (m_server->isolate() == QLatin1String("refraction")) {
                params.mode = FrameParams::IsolateRefraction;
            }
            params.devScale = float(viewport.scale() * std::min(data.xScale(), data.yScale()));
            params.windowOpacity = float(w->opacity() * data.opacity());
            params.backgroundDirty = vs.backgroundDirty;
            params.timing = m_server->timingEnabled();
            const bool tracked = gw->isExplicit();
            const int lumaInterval = tier == QualityTier::Efficient ? 3 * kLumaIntervalMs : kLumaIntervalMs;
            params.wantLuma = tracked && (!vs.lastLuma.isValid() || vs.lastLuma.elapsed() >= lumaInterval);

            Region region = deviceRegion;
            if (gw->hasAutoClip) {
                Region clip;
                for (const RectF &r : gw->autoClip.rects()) {
                    const RectF global = RectF(QRectF(r).translated(w->pos() + QPointF(data.xTranslation(), data.yTranslation())));
                    clip |= viewport.mapToDeviceCoordinatesAligned(global);
                }
                region = deviceRegion == Region::infinite() ? clip : (deviceRegion & clip);
            }
            const bool covered = m_renderer->paint(renderTarget, viewport, region, *vs.cache, m_deviceShapes, m_deviceBodies,
                                                   m_deviceClusters, params);
            m_glassDraws++;
            if (params.wantLuma && m_renderer->lumaPending(*vs.cache)) {
                vs.lastLuma.start();
                if (!m_lumaPoll.isActive()) {
                    m_lumaPollAttempts = 0;
                    m_lumaPoll.start();
                }
            }
            if (!covered) {
                // a new capture was only partly repainted: complete it next frame
                w->addRepaint(RectF(gw->itemRect));
                vs.forceDirty = true;
            }
            if (params.timing) {
                const PassTimes &t = m_renderer->lastTimes();
                m_timingSum.captureMs += t.captureMs;
                m_timingSum.blurMs += t.blurMs;
                m_timingSum.compositeMs += t.compositeMs;
                m_timingSum.lumaMs += t.lumaMs;
                m_lastTiming = t;
            }
        }
    }
    return effects->drawWindow(renderTarget, viewport, w, mask, deviceRegion, data);
}

void GlassEffect::postPaintScreen()
{
    effects->postPaintScreen();
    // Event-driven animation: only while a pressed or legibility transition is running.
    for (auto &[w, gw] : m_windows) {
        if (gw->animating) {
            w->addRepaint(RectF(gw->itemRect));
        }
    }
    if (m_server->timingEnabled()) {
        m_timingFrames++;
        reportTiming();
    }
}

void GlassEffect::advanceAnimations()
{
    const qint64 now = m_clock.elapsed();
    const float dt = m_lastAnimationMs < 0 ? 0.0f : std::clamp(float(now - m_lastAnimationMs) / 1000.0f, 0.0f, 0.1f);
    m_lastAnimationMs = now;
    const auto approach = [dt](float &value, float target, float seconds) {
        if (value == target) {
            return false;
        }
        const float step = dt / seconds;
        value = value < target ? std::min(target, value + step) : std::max(target, value - step);
        return value != target;
    };
    for (auto &[w, gw] : m_windows) {
        if (!gw->animating) {
            continue;
        }
        bool running = false;
        for (auto &[key, st] : gw->states) {
            running |= approach(st.pressed, st.pressedTarget, kPressAnimSeconds);
            if (st.scheme >= 0) {
                running |= approach(st.scheme, st.schemeTarget, kSchemeAnimSeconds);
            }
        }
        // one more frame after the values settle, so the final state is painted
        gw->animating = running;
        if (!running) {
            w->addRepaint(RectF(gw->itemRect));
        }
    }
}

void GlassEffect::pollLegibility()
{
    effects->makeOpenGLContextCurrent();
    bool pending = false;
    for (auto &[w, gw] : m_windows) {
        for (auto &[view, vs] : gw->views) {
            if (!vs.cache || !m_renderer->lumaPending(*vs.cache)) {
                continue;
            }
            if (m_renderer->pollLuma(*vs.cache, m_lumaResults)) {
                applyLuma(*gw, m_lumaResults);
            } else {
                pending = true;
            }
        }
    }
    if (pending && ++m_lumaPollAttempts < 30) {
        m_lumaPoll.start();
    } else if (pending) {
        qCWarning(KRISTALL_GLASS) << "legibility readback did not complete";
    }
}

void GlassEffect::applyLuma(GlassWindow &gw, const std::vector<GlassRenderer::LumaResult> &results)
{
    const bool darkTheme = m_settings->darkTheme();
    const qint64 now = m_clock.elapsed();
    bool changed = false;
    for (LocalShape &ls : gw.shapes) {
        if (ls.binding == 0 || ls.lumaSlot < 0 || ls.lumaSlot >= int(results.size())) {
            continue;
        }
        ShapeState &st = *ls.state;
        const float background = results[ls.lumaSlot].mean;
        // estimated luminance of the glass before the legibility band is applied
        const float glass = background * (1.0f - ls.tint.w()) + ls.tintLuminance * ls.tint.w();
        st.glassLuminance = glass;
        // Theme-biased hysteresis: light theme prefers light glass with dark text and flips only
        // over clearly dark content, the dark theme vice versa.
        const bool light = st.schemeTarget > 0.5f;
        bool wantLight = light;
        if (darkTheme) {
            wantLight = light ? glass > 0.52f : glass > 0.62f;
        } else {
            wantLight = light ? glass > 0.40f : glass > 0.50f;
        }
        if (wantLight != light && now - st.lastFlipMs >= kSchemeDwellMs) {
            st.schemeTarget = wantLight ? 1.0f : 0.0f;
            st.lastFlipMs = now;
            gw.animating = true;
            changed = true;
            st.reported = false;
        }
        if (!st.reported) {
            m_server->sendLegibility(ls.binding, ls.spec.id, st.schemeTarget > 0.5f ? QStringLiteral("light") : QStringLiteral("dark"), glass);
            st.reported = true;
        }
    }
    if (changed) {
        gw.window->addRepaint(RectF(gw.itemRect));
    }
}

QJsonObject GlassEffect::status() const
{
    QJsonObject o;
    if (m_guard) {
        o[QStringLiteral("guard")] = m_guard->status();
    }
    o[QStringLiteral("frames")] = qint64(m_frames);
    o[QStringLiteral("glassDraws")] = qint64(m_glassDraws);
    if (m_renderer) {
        const Counters &c = m_renderer->counters();
        o[QStringLiteral("captures")] = qint64(c.captures);
        o[QStringLiteral("blurs")] = qint64(c.blurs);
        o[QStringLiteral("cacheHits")] = qint64(c.cacheHits);
        o[QStringLiteral("composites")] = qint64(c.composites);
        o[QStringLiteral("lumaReads")] = qint64(c.lumaReads);
        o[QStringLiteral("allocations")] = qint64(c.allocations);
    }
    o[QStringLiteral("quality")] = effectiveQuality() == QualityTier::High ? QStringLiteral("high") : QStringLiteral("efficient");
    o[QStringLiteral("theme")] = m_settings->darkTheme() ? QStringLiteral("dark") : QStringLiteral("light");
    o[QStringLiteral("glass")] = m_settings->glass();
    o[QStringLiteral("reduceTransparency")] = m_settings->reduceTransparency();
    QJsonArray windows;
    for (const auto &[w, gw] : m_windows) {
        QJsonObject wo;
        wo[QStringLiteral("explicit")] = gw->isExplicit();
        wo[QStringLiteral("shapes")] = int(gw->shapes.size());
        wo[QStringLiteral("pid")] = qint64(w->pid());
        if (m_tracker) {
            const QString ns = const_cast<SurfaceTracker *>(m_tracker.get())->layerNamespace(w);
            if (!ns.isEmpty()) {
                wo[QStringLiteral("namespace")] = ns;
            }
        }
        const QRectF g = QRectF(w->frameGeometry());
        wo[QStringLiteral("geometry")] = QJsonArray{g.x(), g.y(), g.width(), g.height()};
        QJsonArray schemes;
        for (const LocalShape &ls : gw->shapes) {
            schemes.append(QJsonObject{{QStringLiteral("id"), ls.spec.id},
                                       {QStringLiteral("scheme"), ls.state && ls.state->schemeTarget > 0.5f ? QStringLiteral("light") : QStringLiteral("dark")},
                                       {QStringLiteral("glassLuminance"), ls.state ? ls.state->glassLuminance : -1.0f}});
        }
        wo[QStringLiteral("shapeStates")] = schemes;
        windows.append(wo);
    }
    o[QStringLiteral("windows")] = windows;
    o[QStringLiteral("lastTiming")] = QJsonObject{
        {QStringLiteral("captureMs"), m_lastTiming.captureMs},
        {QStringLiteral("blurMs"), m_lastTiming.blurMs},
        {QStringLiteral("compositeMs"), m_lastTiming.compositeMs},
        {QStringLiteral("lumaMs"), m_lastTiming.lumaMs},
    };
    return o;
}

void GlassEffect::reportTiming()
{
    if (!m_timingWindow.isValid()) {
        m_timingWindow.start();
        m_timingSum = PassTimes{};
        m_timingFrames = 0;
        return;
    }
    if (m_timingWindow.elapsed() < 1000 || m_timingFrames == 0) {
        return;
    }
    const double f = double(m_timingFrames);
    const QJsonObject t{
        {QStringLiteral("frames"), qint64(m_timingFrames)},
        {QStringLiteral("captureMs"), m_timingSum.captureMs / f},
        {QStringLiteral("blurMs"), m_timingSum.blurMs / f},
        {QStringLiteral("compositeMs"), m_timingSum.compositeMs / f},
        {QStringLiteral("lumaMs"), m_timingSum.lumaMs / f},
        {QStringLiteral("totalMs"), (m_timingSum.captureMs + m_timingSum.blurMs + m_timingSum.compositeMs + m_timingSum.lumaMs) / f},
    };
    qCInfo(KRISTALL_GLASS).noquote() << "timing per frame (ms, glFinish-bracketed): capture" << t[QStringLiteral("captureMs")].toDouble()
                                     << "blur" << t[QStringLiteral("blurMs")].toDouble() << "composite" << t[QStringLiteral("compositeMs")].toDouble()
                                     << "luma" << t[QStringLiteral("lumaMs")].toDouble() << "over" << m_timingFrames << "frames";
    m_server->sendTiming(t);
    m_timingWindow.restart();
    m_timingSum = PassTimes{};
    m_timingFrames = 0;
}

} // namespace Kristall

#include "moc_glasseffect.cpp"
