/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-FileCopyrightText: 2010 Fredrik Höglund <fredrik@kde.org> (capture/blur structure, see below)
    SPDX-FileCopyrightText: 2018 Alex Nemeth <alex.nemeth329@gmail.com>
    SPDX-License-Identifier: GPL-2.0-or-later

    The capture + Dual-Kawase blur structure (blit the damaged background into an offscreen
    texture, downsample/upsample chain) follows KWin's blur effect (src/plugins/blur/blur.cpp,
    KWin 6.8, GPL-2.0-or-later). This file is therefore distributed under GPL-2.0-or-later; the
    rest of the plugin is GPL-3.0-or-later, and the combined plugin is GPL-3.0-or-later.
*/
#include "glassrenderer.h"
#include "glasslog.h"

#include "core/rendertarget.h"
#include "core/renderviewport.h"
#include "opengl/eglcontext.h"
#include "opengl/glframebuffer.h"
#include "opengl/glshader.h"
#include "opengl/glshadermanager.h"
#include "opengl/gltexture.h"
#include "opengl/glvertexbuffer.h"

#include <QMatrix4x4>

#include <algorithm>
#include <chrono>
#include <cmath>

static void ensureResources()
{
    Q_INIT_RESOURCE(glass);
}

namespace Kristall
{

using namespace KWin;

BlurParams blurParamsFor(float radius)
{
    // Dual Kawase spreads roughly twice as far as its nominal radius; the material asks for a
    // visual radius, so halve it before choosing iterations (calibrated by eye on llvmpipe).
    const float r = radius * 0.5f;
    // Ranges follow the offsets KWin's blur found free of artefacts per iteration count
    // ({1..2, 10px}, {2..3, 20px}, {2..5, 50px}, {3..8, 150px}); "reach" is how far the chain
    // reads beyond a pixel, scaled down with the offset actually used.
    if (r < 0.75f) {
        return {0, 0.f, 0.f};
    }
    if (r <= 4.f) {
        const float o = std::clamp(r / 2.f, 1.f, 2.f);
        return {1, o, 10.f * o / 2.f + 2.f};
    }
    if (r <= 10.f) {
        const float o = 2.f + (r - 4.f) / 6.f;
        return {2, o, 20.f * o / 3.f + 2.f};
    }
    if (r <= 24.f) {
        const float o = 2.f + 3.f * (r - 10.f) / 14.f;
        return {3, o, 50.f * o / 5.f + 2.f};
    }
    const float o = 3.f + 5.f * std::min((r - 24.f) / 40.f, 1.f);
    return {4, o, 150.f * o / 8.f + 2.f};
}

GlassRenderer::WindowCache::~WindowCache()
{
    if (luma.fence) {
        glDeleteSync(luma.fence);
    }
    if (luma.pbo) {
        glDeleteBuffers(1, &luma.pbo);
    }
}

GlassRenderer::GlassRenderer() = default;
GlassRenderer::~GlassRenderer() = default;

static bool loadPass(const char *fragment, std::unique_ptr<GLShader> &out)
{
    out = ShaderManager::instance()->generateShaderFromFile(ShaderTrait::MapTexture,
                                                            QStringLiteral(":/effects/kristall_glass/shaders/vertex.vert"),
                                                            QStringLiteral(":/effects/kristall_glass/shaders/%1").arg(QLatin1String(fragment)));
    return out != nullptr;
}

bool GlassRenderer::init()
{
    ensureResources();
    EglContext *context = EglContext::currentContext();
    if (!context) {
        m_error = QStringLiteral("no OpenGL context");
        return false;
    }

    for (auto [pass, file] : {std::pair{&m_down, "downsample.frag"}, std::pair{&m_up, "upsample.frag"}, std::pair{&m_luma, "luma.frag"}}) {
        if (!loadPass(file, pass->shader)) {
            m_error = QStringLiteral("shader %1 failed to compile").arg(QLatin1String(file));
            return false;
        }
        pass->mvp = pass->shader->uniformLocation("modelViewProjectionMatrix");
        pass->cap = pass->shader->uniformLocation("srcCap");
        pass->used = pass->shader->uniformLocation("srcUsed");
        pass->offset = pass->shader->uniformLocation("offset");
        pass->area = pass->shader->uniformLocation("area");
    }
    if (!loadPass("composite.frag", m_comp.shader)) {
        m_error = QStringLiteral("shader composite.frag failed to compile");
        return false;
    }
    GLShader *s = m_comp.shader.get();
    m_comp.mvp = s->uniformLocation("modelViewProjectionMatrix");
    m_comp.sharpTex = s->uniformLocation("sharpTex");
    m_comp.blurTex = s->uniformLocation("blurTex");
    m_comp.captureOrigin = s->uniformLocation("captureOrigin");
    m_comp.sharpInfo = s->uniformLocation("sharpInfo");
    m_comp.blurInfo = s->uniformLocation("blurInfo");
    m_comp.texScale = s->uniformLocation("texScale");
    m_comp.shapeCount = s->uniformLocation("shapeCount");
    m_comp.mergeK = s->uniformLocation("mergeK");
    m_comp.geom = s->uniformLocation("geom");
    m_comp.corner = s->uniformLocation("corner");
    m_comp.lens = s->uniformLocation("lens");
    m_comp.tint = s->uniformLocation("tint");
    m_comp.material = s->uniformLocation("material");
    m_comp.extra = s->uniformLocation("extra");
    m_comp.extra2 = s->uniformLocation("extra2");
    m_comp.lightDir = s->uniformLocation("lightDir");
    m_comp.devScale = s->uniformLocation("devScale");
    m_comp.windowOpacity = s->uniformLocation("windowOpacity");
    m_comp.mode = s->uniformLocation("mode");
    m_comp.opaqueColor = s->uniformLocation("opaqueColor");

    // Asynchronous readback needs PBOs + fences: GL 3.2 / GLES 3.0.
    const int version = epoxy_gl_version();
    m_asyncReadback = epoxy_is_desktop_gl() ? (version >= 32 || epoxy_has_gl_extension("GL_ARB_sync")) : version >= 30;
    if (!m_asyncReadback) {
        qCInfo(KRISTALL_GLASS) << "no PBO/fence support: automatic legibility falls back to the theme";
    }
    m_scratchRects.reserve(64);
    m_uniformScratch.resize(kMaxShapesPerBody * 4 * 7);
    m_valid = true;
    return true;
}

bool GlassRenderer::ensureLevel(Level &level, GLenum format, const QSize &size)
{
    const QSize needed = size.expandedTo(QSize(1, 1));
    if (level.texture && level.texture->internalFormat() == format && level.capacity.width() >= needed.width()
        && level.capacity.height() >= needed.height()) {
        level.used = needed;
        return true;
    }
    // Round capacity up so shapes that animate (a Dock magnifying, a capsule growing) reuse the
    // same textures instead of reallocating every frame.
    const auto roundUp = [](int v) {
        return ((v + v / 4 + 63) / 64) * 64;
    };
    const QSize capacity(roundUp(needed.width()), roundUp(needed.height()));
    level.framebuffer.reset();
    level.texture = GLTexture::allocate(format, capacity);
    if (!level.texture) {
        qCWarning(KRISTALL_GLASS) << "failed to allocate a glass texture" << capacity;
        level.capacity = QSize();
        return false;
    }
    level.texture->setFilter(GL_LINEAR);
    level.texture->setWrapMode(GL_CLAMP_TO_EDGE);
    level.framebuffer = std::make_unique<GLFramebuffer>(level.texture.get());
    if (!level.framebuffer->valid()) {
        qCWarning(KRISTALL_GLASS) << "failed to create a glass framebuffer";
        level.framebuffer.reset();
        level.texture.reset();
        return false;
    }
    GLFramebuffer::pushFramebuffer(level.framebuffer.get());
    glClearColor(0, 0, 0, 0);
    glClear(GL_COLOR_BUFFER_BIT);
    GLFramebuffer::popFramebuffer();
    level.capacity = capacity;
    level.used = needed;
    m_counters.allocations++;
    return true;
}

static Rect globalToDevice(const RenderViewport &viewport, const Rect &global)
{
    // global device px (logical * scale) -> view device px (before the output transform)
    return global.translated(-viewport.scaledRenderRect().topLeft() + viewport.renderOffset());
}

void GlassRenderer::capture(const RenderTarget &renderTarget, const RenderViewport &viewport, const Region &deviceRegion,
                            TargetSet &set, bool full)
{
    Level &l0 = set.levels[0];
    const Rect captureDev = globalToDevice(viewport, set.captureRect);
    const OutputTransform transform = viewport.transform();
    const bool mirrorX = transform == OutputTransform::FlipX;
    const bool mirrorY = transform == OutputTransform::FlipY;
    // Normal and flipped targets (outputs, KWin's own screenshots) are copied pixel-exactly;
    // rotated outputs go through KWin's helper, which works in logical integer rects and can be
    // up to half a device pixel off at fractional scales.
    const bool direct = (transform == OutputTransform::Normal || mirrorX || mirrorY) && EglContext::currentContext()->supportsBlits();

    m_scratchRects.clear();
    if (full || deviceRegion == Region::infinite()) {
        m_scratchRects.push_back(captureDev);
    } else {
        // Only repainted pixels hold the current background; everything else in the render
        // target still shows last frame's glass and must not be captured.
        for (const Rect &r : deviceRegion.rects()) {
            const Rect clipped = r.intersected(captureDev);
            if (!clipped.isEmpty()) {
                m_scratchRects.push_back(clipped);
            }
        }
    }
    for (const Rect &src : m_scratchRects) {
        const Rect dst = src.translated(-captureDev.topLeft());
        if (direct) {
            const Rect rt = transform.map(src, renderTarget.size());
            l0.framebuffer->blitFromFramebuffer(rt, dst, GL_NEAREST, mirrorX, mirrorY);
        } else {
            const Rect logical = viewport.mapFromDeviceCoordinatesAligned(src);
            l0.framebuffer->blitFromRenderTarget(renderTarget, viewport, logical, dst);
        }
    }
    m_counters.captures++;
}

void GlassRenderer::runBlur(TargetSet &set, bool efficient, int vboFirst)
{
    const int n = set.blur.iterations;
    GLVertexBuffer *vbo = GLVertexBuffer::streamingBuffer();
    if (n <= 0) {
        set.resultLevel = 0;
        return;
    }
    // efficient tier: stop the upsample chain one level early (quarter resolution result)
    const int stopLevel = efficient ? std::min(n, 2) : 1;

    ShaderManager::instance()->pushShader(m_down.shader.get());
    m_down.shader->setUniform(m_down.offset, set.blur.offset);
    for (int i = 1; i <= n; ++i) {
        const Level &read = set.levels[i - 1];
        const Level &draw = set.levels[i];
        QMatrix4x4 projection;
        projection.ortho(QRectF(0, 0, draw.capacity.width(), draw.capacity.height()));
        m_down.shader->setUniform(m_down.mvp, projection);
        m_down.shader->setUniform(m_down.cap, QVector2D(read.capacity.width(), read.capacity.height()));
        m_down.shader->setUniform(m_down.used, QVector2D(read.used.width(), read.used.height()));
        read.texture->bind();
        GLFramebuffer::pushFramebuffer(draw.framebuffer.get());
        vbo->draw(GL_TRIANGLES, vboFirst + (i - 1) * 6, 6);
        GLFramebuffer::popFramebuffer();
    }
    ShaderManager::instance()->popShader();

    ShaderManager::instance()->pushShader(m_up.shader.get());
    m_up.shader->setUniform(m_up.offset, set.blur.offset);
    for (int i = n - 1; i >= stopLevel; --i) {
        const Level &read = set.levels[i + 1];
        const Level &draw = set.levels[i];
        QMatrix4x4 projection;
        projection.ortho(QRectF(0, 0, draw.capacity.width(), draw.capacity.height()));
        m_up.shader->setUniform(m_up.mvp, projection);
        m_up.shader->setUniform(m_up.cap, QVector2D(read.capacity.width(), read.capacity.height()));
        m_up.shader->setUniform(m_up.used, QVector2D(read.used.width(), read.used.height()));
        read.texture->bind();
        GLFramebuffer::pushFramebuffer(draw.framebuffer.get());
        vbo->draw(GL_TRIANGLES, vboFirst + (i - 1) * 6, 6);
        GLFramebuffer::popFramebuffer();
    }
    ShaderManager::instance()->popShader();
    set.resultLevel = (n == 1) ? 1 : stopLevel;
    m_counters.blurs++;
}

static inline void putQuad(std::span<GLVertex2D> map, size_t &i, const QRectF &pos, const QRectF &tex)
{
    const QVector2D p00(pos.left(), pos.top()), p10(pos.right(), pos.top()), p01(pos.left(), pos.bottom()), p11(pos.right(), pos.bottom());
    const QVector2D t00(tex.left(), tex.top()), t10(tex.right(), tex.top()), t01(tex.left(), tex.bottom()), t11(tex.right(), tex.bottom());
    map[i++] = GLVertex2D{.position = p00, .texcoord = t00};
    map[i++] = GLVertex2D{.position = p11, .texcoord = t11};
    map[i++] = GLVertex2D{.position = p01, .texcoord = t01};
    map[i++] = GLVertex2D{.position = p00, .texcoord = t00};
    map[i++] = GLVertex2D{.position = p10, .texcoord = t10};
    map[i++] = GLVertex2D{.position = p11, .texcoord = t11};
}

namespace
{
struct ScopedTimer
{
    bool enabled;
    double &target;
    std::chrono::steady_clock::time_point start;
    ScopedTimer(bool on, double &t)
        : enabled(on)
        , target(t)
    {
        if (enabled) {
            glFinish(); // debug timing only: isolate the pass from earlier GPU work
            start = std::chrono::steady_clock::now();
        }
    }
    ~ScopedTimer()
    {
        if (enabled) {
            glFinish();
            target += std::chrono::duration<double, std::milli>(std::chrono::steady_clock::now() - start).count();
        }
    }
};
}

bool GlassRenderer::paint(const RenderTarget &renderTarget, const RenderViewport &viewport, const Region &deviceRegion,
                          WindowCache &cache, const std::vector<DeviceShape> &shapes, const std::vector<DeviceBody> &bodies,
                          const std::vector<DeviceCluster> &clusters, const FrameParams &params)
{
    if (!m_valid || shapes.empty()) {
        return true;
    }
    m_counters.paints++;
    m_times = PassTimes{};
    const bool reduce = params.mode == FrameParams::ReduceTransparency;
    const bool efficient = params.mode == FrameParams::Efficient;
    bool coveredEverything = true;

    // ---- prepare targets ------------------------------------------------------------------
    GLenum format = GL_RGBA8;
    if (renderTarget.texture()) {
        format = renderTarget.texture()->internalFormat();
    }
    if (cache.sets.size() < clusters.size()) {
        cache.sets.resize(clusters.size());
    }
    // which clusters need a new capture / blur this frame
    std::array<bool, 64> recapture{};
    const size_t clusterCount = std::min<size_t>(clusters.size(), recapture.size());
    if (!reduce) {
        for (size_t c = 0; c < clusterCount; ++c) {
            TargetSet &set = cache.sets[c];
            const DeviceCluster &cl = clusters[c];
            BlurParams blur = blurParamsFor(cl.blurRadius);
            if (efficient && blur.iterations > 1) {
                // efficient tier: one iteration less (a slightly softer, cheaper blur)
                blur = blurParamsFor(cl.blurRadius * 0.5f);
                blur.iterations = std::max(1, blur.iterations);
            }
            const bool sameRect = set.contentValid && set.captureRect == cl.captureRect && set.format == format;
            const bool sameBlur = set.blur.iterations == blur.iterations && std::abs(set.blur.offset - blur.offset) < 0.01f;
            set.blur = blur;
            set.format = format;
            set.captureRect = cl.captureRect;
            QSize size = cl.captureRect.size();
            bool ok = ensureLevel(set.levels[0], format, size);
            for (int i = 1; ok && i <= blur.iterations && i < kMaxLevels; ++i) {
                size = QSize((size.width() + 1) / 2, (size.height() + 1) / 2);
                ok = ensureLevel(set.levels[i], format, size);
            }
            if (!ok) {
                set.contentValid = false;
                return true; // out of GPU memory: draw the window without glass this frame
            }
            if (!sameRect) {
                recapture[c] = true;
                // the cached capture is unusable; it must be refilled completely
                const Rect rt = globalToDevice(viewport, cl.captureRect);
                if (deviceRegion != Region::infinite() && !deviceRegion.contains(rt)) {
                    coveredEverything = false;
                }
            } else if (params.backgroundDirty || !sameBlur) {
                recapture[c] = true;
            } else {
                m_counters.cacheHits++;
            }
        }
    }

    // ---- geometry ---------------------------------------------------------------------------
    const QPointF toGlobal = QPointF(viewport.scaledRenderRect().topLeft() - viewport.renderOffset());
    size_t vertexCount = 0;
    std::array<int, 64> blurFirst{};
    if (!reduce) {
        for (size_t c = 0; c < clusterCount; ++c) {
            if (recapture[c]) {
                blurFirst[c] = int(vertexCount);
                vertexCount += 6 * (kMaxLevels - 1);
            }
        }
    }
    const bool infinite = deviceRegion == Region::infinite();
    const int compositeFirst = int(vertexCount);
    std::array<int, 128> bodyFirst{};
    std::array<int, 128> bodyCount{};
    const size_t bodyLimit = std::min<size_t>(bodies.size(), bodyFirst.size());
    // count clip rects per body
    for (size_t b = 0; b < bodyLimit; ++b) {
        int n = 0;
        if (infinite) {
            n = 1;
        } else {
            for (const Rect &r : deviceRegion.rects()) {
                if (QRectF(QRect(r)).translated(toGlobal).intersects(bodies[b].bounds)) {
                    ++n;
                }
            }
        }
        bodyFirst[b] = int(vertexCount);
        bodyCount[b] = n * 6;
        vertexCount += size_t(n) * 6;
    }
    const bool wantLuma = params.wantLuma && m_asyncReadback && !reduce && !lumaPending(cache);
    const int lumaFirst = int(vertexCount);
    if (wantLuma) {
        vertexCount += 6 * kLumaSlots;
    }
    if (vertexCount == 0) {
        return coveredEverything;
    }

    GLVertexBuffer *vbo = GLVertexBuffer::streamingBuffer();
    vbo->reset();
    vbo->setAttribLayout(std::span(GLVertexBuffer::GLVertex2DLayout), sizeof(GLVertex2D));
    if (auto result = vbo->map<GLVertex2D>(vertexCount)) {
        auto map = *result;
        size_t i = 0;
        if (!reduce) {
            for (size_t c = 0; c < clusterCount; ++c) {
                if (!recapture[c]) {
                    continue;
                }
                for (int l = 1; l < kMaxLevels; ++l) {
                    const QSize used = cache.sets[c].levels[l].texture ? cache.sets[c].levels[l].used : QSize(1, 1);
                    const QRectF r(0, 0, used.width(), used.height());
                    putQuad(map, i, r, r);
                }
            }
        }
        for (size_t b = 0; b < bodyLimit; ++b) {
            const QRectF bounds = bodies[b].bounds;
            if (infinite) {
                putQuad(map, i, bounds, bounds);
                continue;
            }
            for (const Rect &r : deviceRegion.rects()) {
                const QRectF clip = QRectF(QRect(r)).translated(toGlobal).intersected(bounds);
                if (!clip.isEmpty()) {
                    putQuad(map, i, clip, clip);
                } else if (QRectF(QRect(r)).translated(toGlobal).intersects(bounds)) {
                    putQuad(map, i, QRectF(), QRectF()); // degenerate, keeps the count consistent
                }
            }
        }
        if (wantLuma) {
            for (int s = 0; s < kLumaSlots; ++s) {
                const QRectF r(s, 0, 1, 1);
                putQuad(map, i, r, r);
            }
        }
        vbo->unmap();
    } else {
        qCWarning(KRISTALL_GLASS) << "failed to map the vertex buffer";
        return coveredEverything;
    }
    vbo->bindArrays();

    // ---- capture + blur (skipped when the cached blur is still valid) ------------------------
    if (!reduce) {
        for (size_t c = 0; c < clusterCount; ++c) {
            if (!recapture[c]) {
                continue;
            }
            TargetSet &set = cache.sets[c];
            {
                ScopedTimer t(params.timing, m_times.captureMs);
                capture(renderTarget, viewport, deviceRegion, set, false);
            }
            {
                ScopedTimer t(params.timing, m_times.blurMs);
                runBlur(set, efficient, blurFirst[c]);
            }
            set.contentValid = true;
        }
    }

    // ---- composite --------------------------------------------------------------------------
    {
        ScopedTimer t(params.timing, m_times.compositeMs);
        ShaderManager::instance()->pushShader(m_comp.shader.get());
        GLShader *s = m_comp.shader.get();
        s->setUniform(m_comp.mvp, viewport.projectionMatrix());
        s->setUniform(m_comp.sharpTex, 0);
        s->setUniform(m_comp.blurTex, 1);
        s->setUniform(m_comp.lightDir, params.lightDir);
        s->setUniform(m_comp.devScale, params.devScale);
        s->setUniform(m_comp.windowOpacity, params.windowOpacity);
        s->setUniform(m_comp.mode, int(params.mode));
        s->setUniform(m_comp.opaqueColor, params.opaqueColor);

        glEnable(GL_BLEND);
        glBlendFunc(GL_ONE, GL_ONE_MINUS_SRC_ALPHA);
        int boundCluster = -1;
        for (size_t b = 0; b < bodyLimit; ++b) {
            const DeviceBody &body = bodies[b];
            if (bodyCount[b] == 0) {
                continue;
            }
            if (!reduce && body.cluster != boundCluster && size_t(body.cluster) < clusterCount) {
                const TargetSet &set = cache.sets[body.cluster];
                const Level &sharp = set.levels[0];
                const Level &blurred = set.levels[set.resultLevel];
                glActiveTexture(GL_TEXTURE1);
                blurred.texture->bind();
                glActiveTexture(GL_TEXTURE0);
                sharp.texture->bind();
                s->setUniform(m_comp.captureOrigin, QVector2D(set.captureRect.x(), set.captureRect.y()));
                s->setUniform(m_comp.sharpInfo, QVector4D(sharp.capacity.width(), sharp.capacity.height(), sharp.used.width(), sharp.used.height()));
                s->setUniform(m_comp.blurInfo, QVector4D(blurred.capacity.width(), blurred.capacity.height(), blurred.used.width(), blurred.used.height()));
                s->setUniform(m_comp.texScale, QVector2D(1.0f, 1.0f / float(1 << set.resultLevel)));
                boundCluster = body.cluster;
            }
            const int n = std::min(body.count, kMaxShapesPerBody);
            float *u = m_uniformScratch.data();
            const auto upload = [&](int location, QVector4D DeviceShape::*member) {
                for (int k = 0; k < n; ++k) {
                    const QVector4D &v = shapes[body.first + k].*member;
                    u[k * 4 + 0] = v.x();
                    u[k * 4 + 1] = v.y();
                    u[k * 4 + 2] = v.z();
                    u[k * 4 + 3] = v.w();
                }
                glUniform4fv(location, n, u);
            };
            upload(m_comp.geom, &DeviceShape::geom);
            upload(m_comp.corner, &DeviceShape::corner);
            upload(m_comp.lens, &DeviceShape::lens);
            upload(m_comp.tint, &DeviceShape::tint);
            upload(m_comp.material, &DeviceShape::material);
            upload(m_comp.extra, &DeviceShape::extra);
            upload(m_comp.extra2, &DeviceShape::extra2);
            s->setUniform(m_comp.shapeCount, n);
            s->setUniform(m_comp.mergeK, body.mergeK);
            vbo->draw(GL_TRIANGLES, bodyFirst[b], bodyCount[b]);
            m_counters.composites++;
        }
        glDisable(GL_BLEND);
        ShaderManager::instance()->popShader();
    }

    // ---- legibility: luminance under each tracked shape, read back asynchronously --------------
    if (wantLuma) {
        bool anyRecaptured = false;
        for (size_t c = 0; c < clusterCount; ++c) {
            anyRecaptured |= recapture[c];
        }
        if (anyRecaptured || !cache.luma.everIssued) {
            ScopedTimer t(params.timing, m_times.lumaMs);
            issueLuma(cache, shapes, bodies, lumaFirst);
        }
    }

    vbo->unbindArrays();
    Q_UNUSED(compositeFirst);
    return coveredEverything;
}

void GlassRenderer::issueLuma(WindowCache &cache, const std::vector<DeviceShape> &shapes, const std::vector<DeviceBody> &bodies, int vboFirst)
{
    LumaReadback &luma = cache.luma;
    if (!luma.texture) {
        luma.texture = GLTexture::allocate(GL_RGBA8, QSize(kLumaSlots, 1));
        if (!luma.texture) {
            return;
        }
        luma.texture->setFilter(GL_NEAREST);
        luma.framebuffer = std::make_unique<GLFramebuffer>(luma.texture.get());
        glGenBuffers(1, &luma.pbo);
        glBindBuffer(GL_PIXEL_PACK_BUFFER, luma.pbo);
        glBufferData(GL_PIXEL_PACK_BUFFER, kLumaSlots * 4, nullptr, GL_STREAM_READ);
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    }
    GLVertexBuffer *vbo = GLVertexBuffer::streamingBuffer();
    ShaderManager::instance()->pushShader(m_luma.shader.get());
    QMatrix4x4 projection;
    projection.ortho(QRectF(0, 0, kLumaSlots, 1));
    m_luma.shader->setUniform(m_luma.mvp, projection);
    GLFramebuffer::pushFramebuffer(luma.framebuffer.get());
    int maxSlot = -1;
    for (const DeviceBody &body : bodies) {
        if (size_t(body.cluster) >= cache.sets.size()) {
            continue;
        }
        const TargetSet &set = cache.sets[body.cluster];
        const Level &src = set.levels[set.resultLevel];
        if (!src.texture) {
            continue;
        }
        const float scale = 1.0f / float(1 << set.resultLevel);
        for (int k = 0; k < body.count; ++k) {
            const DeviceShape &shape = shapes[body.first + k];
            if (shape.lumaSlot < 0 || shape.lumaSlot >= kLumaSlots) {
                continue;
            }
            // sample the inner 80% of the shape, where text is drawn
            const QRectF inner = shape.bounds.adjusted(shape.bounds.width() * 0.1, shape.bounds.height() * 0.1,
                                                       -shape.bounds.width() * 0.1, -shape.bounds.height() * 0.1);
            const QRectF area = inner.translated(-set.captureRect.x(), -set.captureRect.y());
            m_luma.shader->setUniform(m_luma.area, QVector4D(area.left() * scale, area.top() * scale, area.right() * scale, area.bottom() * scale));
            m_luma.shader->setUniform(m_luma.cap, QVector2D(src.capacity.width(), src.capacity.height()));
            m_luma.shader->setUniform(m_luma.used, QVector2D(src.used.width(), src.used.height()));
            src.texture->bind();
            vbo->draw(GL_TRIANGLES, vboFirst + shape.lumaSlot * 6, 6);
            maxSlot = std::max(maxSlot, shape.lumaSlot);
        }
    }
    if (maxSlot >= 0) {
        // The texture is GL-oriented, so pixel row 0 of the readback is the strip itself.
        glBindBuffer(GL_PIXEL_PACK_BUFFER, luma.pbo);
        glPixelStorei(GL_PACK_ALIGNMENT, 1);
        while (glGetError() != GL_NO_ERROR) { }
        glReadPixels(0, 0, maxSlot + 1, 1, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
        if (const GLenum e = glGetError(); e != GL_NO_ERROR) {
            qCWarning(KRISTALL_GLASS) << "legibility readback failed, GL error" << Qt::hex << e;
        }
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
        luma.fence = glFenceSync(GL_SYNC_GPU_COMMANDS_COMPLETE, 0);
        luma.slotCount = maxSlot + 1;
        luma.sinceIssue.start();
        luma.everIssued = true;
        m_counters.lumaReads++;
    }
    GLFramebuffer::popFramebuffer();
    ShaderManager::instance()->popShader();
}

bool GlassRenderer::pollLuma(WindowCache &cache, std::vector<LumaResult> &out)
{
    LumaReadback &luma = cache.luma;
    if (!luma.fence) {
        return false;
    }
    // never waits; the flush bit makes sure the fence can signal even if nothing else flushes
    const GLenum status = glClientWaitSync(luma.fence, GL_SYNC_FLUSH_COMMANDS_BIT, 0);
    if (status != GL_ALREADY_SIGNALED && status != GL_CONDITION_SATISFIED) {
        return false;
    }
    glDeleteSync(luma.fence);
    luma.fence = nullptr;
    glBindBuffer(GL_PIXEL_PACK_BUFFER, luma.pbo);
    const void *data = glMapBufferRange(GL_PIXEL_PACK_BUFFER, 0, luma.slotCount * 4, GL_MAP_READ_BIT);
    out.clear();
    if (!data) {
        qCWarning(KRISTALL_GLASS) << "mapping the legibility readback failed, GL error" << Qt::hex << glGetError();
    }
    if (data) {
        const uint8_t *px = static_cast<const uint8_t *>(data);
        for (int s = 0; s < luma.slotCount; ++s) {
            out.push_back(LumaResult{s, px[s * 4] / 255.0f, px[s * 4 + 1] / 255.0f, px[s * 4 + 2] / 255.0f});
        }
        glUnmapBuffer(GL_PIXEL_PACK_BUFFER);
    }
    glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
    return data != nullptr;
}

} // namespace Kristall
