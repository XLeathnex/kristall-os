/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    GPU side of the effect: background capture, light Dual-Kawase blur, the glass composite and
    the asynchronous luminance readback used for automatic legibility.

    Passes per capture cluster (a group of nearby shapes sharing one background capture):
      capture  glBlitFramebuffer of the damaged part of the cluster rect      (skipped if cached)
      blur     n downsample + (n-1) upsample passes, n = 0..4, ≥ 1/2 res      (skipped if cached)
      luma     one 16-tap texel per shape, then glReadPixels into a PBO        (only after a re-blur,
                                                                                at most 10 Hz)
    Per body (merged shapes) and frame:
      composite  one draw over the body's damaged bounding rects               (always when painted)
*/
#pragma once

#include "core/rect.h"
#include "core/region.h"
#include "opengl/glframebuffer.h"
#include "opengl/gltexture.h"

#include <QElapsedTimer>
#include <QRectF>
#include <QVector4D>

#include <epoxy/gl.h>

#include <array>
#include <memory>
#include <vector>

namespace KWin
{
class GLFramebuffer;
class GLShader;
class GLTexture;
class RenderTarget;
class RenderViewport;
}

namespace Kristall
{

/// One shape ready for the GPU, in global device pixels.
struct DeviceShape
{
    QVector4D geom; ///< centre xy, half size zw
    QVector4D corner; ///< R, p, 1/p, 0
    QVector4D lens; ///< bezel, depth, pressed, opacity
    QVector4D tint; ///< rgb, amount
    QVector4D material; ///< blurMix, saturation, specular, innerShadow
    QVector4D extra; ///< pointer xy, pointer sigma, scheme
    QVector4D extra2; ///< legibility strength, chroma, 0, 0
    QRectF bounds; ///< bounding rect of the outline
    int lumaSlot = -1; ///< index of the luminance texel, -1 = no legibility tracking
};

struct DeviceBody
{
    int first = 0; ///< index into the shape array
    int count = 0; ///< up to kMaxShapesPerBody
    float mergeK = 0; ///< device px
    QRectF bounds; ///< device px, includes the anti-aliasing margin
    int cluster = 0;
};

struct DeviceCluster
{
    KWin::Rect captureRect; ///< global device px, integer, clipped to the view
    float blurRadius = 0; ///< device px
};

struct FrameParams
{
    enum Mode {
        High = 0,
        Efficient = 1,
        ReduceTransparency = 2,
        IsolateRefraction = 3,
    };
    Mode mode = High;
    QVector2D lightDir{-0.45f, -0.89f};
    float devScale = 1;
    float windowOpacity = 1;
    QVector3D opaqueColor{0.94f, 0.94f, 0.95f};
    bool backgroundDirty = true;
    bool wantLuma = false;
    bool timing = false;
};

struct BlurParams
{
    int iterations = 0;
    float offset = 0;
    float reach = 0; ///< device px the blur reads beyond a pixel
};
BlurParams blurParamsFor(float radiusDevice);

struct PassTimes
{
    double captureMs = 0;
    double blurMs = 0;
    double compositeMs = 0;
    double lumaMs = 0;
};

struct Counters
{
    quint64 paints = 0; ///< glass windows drawn
    quint64 captures = 0; ///< background captures (blits)
    quint64 blurs = 0; ///< blur chains run
    quint64 cacheHits = 0; ///< clusters drawn from the cached blur
    quint64 composites = 0; ///< composite draws (bodies)
    quint64 lumaReads = 0; ///< luminance readbacks issued
    quint64 allocations = 0; ///< texture (re)allocations
};

class GlassRenderer
{
public:
    static constexpr int kMaxShapesPerBody = 8;
    static constexpr int kMaxLevels = 5;
    static constexpr int kLumaSlots = 64;

    struct Level
    {
        std::unique_ptr<KWin::GLTexture> texture;
        std::unique_ptr<KWin::GLFramebuffer> framebuffer;
        QSize capacity;
        QSize used;
    };

    struct TargetSet
    {
        std::array<Level, kMaxLevels> levels;
        GLenum format = 0;
        KWin::Rect captureRect;
        BlurParams blur;
        int resultLevel = 0;
        bool contentValid = false;
    };

    struct LumaReadback
    {
        std::unique_ptr<KWin::GLTexture> texture;
        std::unique_ptr<KWin::GLFramebuffer> framebuffer;
        GLuint pbo = 0;
        GLsync fence = nullptr;
        int slotCount = 0;
        QElapsedTimer sinceIssue;
        bool everIssued = false;
    };

    /// GPU state for one window on one output
    struct WindowCache
    {
        std::vector<TargetSet> sets;
        LumaReadback luma;
        ~WindowCache();
    };

    struct LumaResult
    {
        int slot;
        float mean;
        float min;
        float max;
    };

    GlassRenderer();
    ~GlassRenderer();

    bool init();
    bool isValid() const { return m_valid; }
    QString error() const { return m_error; }
    bool supportsLegibility() const { return m_asyncReadback; }

    /// Draws the glass of one window. Must be called from Effect::drawWindow before the window
    /// itself is drawn. Returns false if part of a capture was not covered by @p deviceRegion
    /// and the caller should schedule a repaint of the clusters.
    bool paint(const KWin::RenderTarget &renderTarget, const KWin::RenderViewport &viewport,
               const KWin::Region &deviceRegion, WindowCache &cache,
               const std::vector<DeviceShape> &shapes, const std::vector<DeviceBody> &bodies,
               const std::vector<DeviceCluster> &clusters, const FrameParams &params);

    /// Non-blocking: returns true and fills @p out if a readback of @p cache completed.
    bool pollLuma(WindowCache &cache, std::vector<LumaResult> &out);
    bool lumaPending(const WindowCache &cache) const { return cache.luma.fence != nullptr; }

    const Counters &counters() const { return m_counters; }
    const PassTimes &lastTimes() const { return m_times; }

private:
    bool ensureLevel(Level &level, GLenum format, const QSize &size);
    void capture(const KWin::RenderTarget &renderTarget, const KWin::RenderViewport &viewport,
                 const KWin::Region &deviceRegion, TargetSet &set, bool full);
    void runBlur(TargetSet &set, bool efficient, int vboFirst);
    void issueLuma(WindowCache &cache, const std::vector<DeviceShape> &shapes, const std::vector<DeviceBody> &bodies,
                   int vboFirst);

    struct Pass
    {
        std::unique_ptr<KWin::GLShader> shader;
        int mvp = -1;
        int cap = -1;
        int used = -1;
        int offset = -1;
        int area = -1;
    };
    Pass m_down;
    Pass m_up;
    Pass m_luma;

    struct
    {
        std::unique_ptr<KWin::GLShader> shader;
        int mvp, sharpTex, blurTex, captureOrigin, sharpInfo, blurInfo, texScale;
        int shapeCount, mergeK, geom, corner, lens, tint, material, extra, extra2;
        int lightDir, devScale, windowOpacity, mode, opaqueColor;
    } m_comp;

    bool m_valid = false;
    bool m_asyncReadback = false;
    QString m_error;
    Counters m_counters;
    PassTimes m_times;

    // scratch storage reused every frame (no per-frame heap allocations once warmed up)
    std::vector<KWin::Rect> m_scratchRects;
    std::vector<float> m_uniformScratch;
};

} // namespace Kristall
