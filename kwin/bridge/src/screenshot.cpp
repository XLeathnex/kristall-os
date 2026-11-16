/*
    Kristall OS — compositor bridge

    The offscreen rendering below follows KWin's screenshot plugin
    (src/plugins/screenshot/screenshot.cpp, KWin 6.8.3,
    SPDX-FileCopyrightText: 2010 Martin Gräßlin, 2021 Vlad Zahorodnii).

    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "screenshot.h"
#include "screenshotlayer.h"
#include "windows.h"

#include "compositor.h"
#include "core/output.h"
#include "core/renderdevice.h"
#include "core/rendertarget.h"
#include "core/renderviewport.h"
#include "effect/effect.h"
#include "main.h"
#include "opengl/eglcontext.h"
#include "opengl/glframebuffer.h"
#include "opengl/gltexture.h"
#include "opengl/glutils.h"
#include "scene/decorationitem.h"
#include "scene/item.h"
#include "scene/itemrenderer.h"
#include "scene/shadowitem.h"
#include "scene/windowitem.h"
#include "scene/workspacescene.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"

#include <QDateTime>
#include <QElapsedTimer>
#include <QDir>
#include <QFile>
#include <QFutureWatcher>
#include <QScopeGuard>
#include <QtConcurrent/QtConcurrentRun>

#include <cerrno>
#include <cmath>
#include <fcntl.h>
#include <sys/stat.h>
#include <unistd.h>

using namespace KWin;

namespace Kristall
{

constexpr int kMaxPixels = 16384; // per dimension, after scaling to native resolution
constexpr int kMaxShotsInflight = 4; // queued screenshot requests
constexpr int kMinRenderIntervalMs = 100;

Screenshotter::Screenshotter(Server *server, WindowModel *windows, LayerScopes *scopes, const QString &runtimeDir, QObject *parent)
    : QObject(parent)
    , m_server(server)
    , m_windows(windows)
    , m_scopes(scopes)
    , m_dir(runtimeDir + QStringLiteral("/kristall/shots"))
{
    server->registerMethod(QStringLiteral("screenshot"), MethodSpec{true, QStringLiteral("screenshot"), [this](Params &p, const ReplyPtr &r) {
                                                             take(p, r);
                                                         }});
    m_pacing.setSingleShot(true);
    connect(&m_pacing, &QTimer::timeout, this, &Screenshotter::renderNext);
}

bool Screenshotter::supported()
{
    RenderDevice *device = Compositor::self() ? Compositor::self()->primaryDevice() : nullptr;
    return device && device->eglContext();
}

static std::optional<QImage> renderArea(LogicalOutput *output, const RectF &area, qreal scale, const std::function<bool(Window *)> &filter, bool includeCursor)
{
    RenderDevice *device = Compositor::self()->primaryDevice();
    const auto context = device ? device->eglContext() : nullptr;
    if (!context || !context->makeCurrent()) {
        return std::nullopt;
    }
    const QSize nativeSize(int(std::lround(area.width() * scale)), int(std::lround(area.height() * scale)));
    const auto texture = GLTexture::allocate(GL_RGBA8, nativeSize);
    if (!texture) {
        return std::nullopt;
    }
    texture->setContentTransform(OutputTransform::FlipY);
    texture->setFilter(GL_LINEAR);
    texture->setWrapMode(GL_CLAMP_TO_EDGE);
    const auto target = std::make_unique<GLFramebuffer>(texture.get());
    if (!target->valid()) {
        return std::nullopt;
    }
    OffscreenLayer layer(output, target.get());
    if (!layer.preparePresentationTest()) {
        return std::nullopt;
    }
    SceneView sceneView(kwinApp()->scene(), output, nullptr, &layer, device);
    std::unique_ptr<ItemTreeView> cursorView;
    if (!includeCursor) {
        cursorView = std::make_unique<ItemTreeView>(&sceneView, kwinApp()->scene()->cursorItem(), output, nullptr, nullptr);
        cursorView->setExclusive(true);
    }
    sceneView.addWindowFilter(filter);
    const Rect fullDamage(QPoint(), target->size());
    sceneView.setViewport(area);
    sceneView.setScale(scale);
    sceneView.prePaint();
    const auto _ = qScopeGuard([&sceneView]() {
        sceneView.postPaint();
    });
    const auto beginInfo = layer.beginFrame();
    if (!beginInfo) {
        return std::nullopt;
    }
    sceneView.paint(beginInfo->renderTarget, QPoint(), fullDamage);
    if (!layer.endFrame(fullDamage, fullDamage, nullptr)) {
        return std::nullopt;
    }
    GLFramebuffer::pushFramebuffer(target.get());
    QImage image(texture->size(), QImage::Format_RGBX8888);
    context->glReadnPixels(0, 0, image.width(), image.height(), GL_RGBA, GL_UNSIGNED_BYTE, image.sizeInBytes(), static_cast<GLvoid *>(image.bits()));
    GLFramebuffer::popFramebuffer();
    return image;
}

static std::optional<QImage> renderWindow(Window *window, const RectF &geometry, qreal scale, bool includeCursor)
{
    RenderDevice *device = Compositor::self()->primaryDevice();
    const auto context = device ? device->eglContext() : nullptr;
    if (!context || !context->makeCurrent()) {
        return std::nullopt;
    }
    const QSize nativeSize(int(std::lround(geometry.width() * scale)), int(std::lround(geometry.height() * scale)));
    const auto texture = GLTexture::allocate(GL_RGBA8, nativeSize);
    if (!texture) {
        return std::nullopt;
    }
    texture->setContentTransform(OutputTransform::FlipY);
    GLFramebuffer target(texture.get());
    RenderTarget renderTarget(&target);
    RenderViewport viewport(geometry, scale, renderTarget, QPoint());
    WorkspaceScene *scene = kwinApp()->scene();
    auto renderer = scene->renderer(device);
    renderer->beginFrame(renderTarget, viewport);
    glClearColor(0.0, 0.0, 0.0, 0.0);
    glClear(GL_COLOR_BUFFER_BIT);
    const bool ok = renderer->renderItem(renderTarget, viewport, window->windowItem(), Scene::PAINT_WINDOW_TRANSFORMED, Region::infinite(), WindowPaintData{}, [w = window->windowItem()](Item *item) {
        return item == w->shadowItem(); // frame including the decoration, without the shadow
    }, {});
    if (!ok) {
        return std::nullopt;
    }
    if (includeCursor && scene->cursorItem()->isVisible()) {
        renderer->renderItem(renderTarget, viewport, scene->cursorItem(), 0, Region::infinite(), WindowPaintData{}, {}, {});
    }
    renderer->endFrame();
    GLFramebuffer::pushFramebuffer(&target);
    QImage image(texture->size(), QImage::Format_RGBA8888_Premultiplied);
    context->glReadnPixels(0, 0, image.width(), image.height(), GL_RGBA, GL_UNSIGNED_BYTE, image.sizeInBytes(), static_cast<GLvoid *>(image.bits()));
    GLFramebuffer::popFramebuffer();
    return image;
}

struct ShotResult
{
    QString path;
    int width = 0;
    int height = 0;
    QString error;
};

// Runs on a worker thread: scale, encode, write (0600, O_EXCL), and prune forgotten files.
static ShotResult encode(QImage image, int maxW, int maxH, const QString &dir, const QString &name)
{
    ShotResult r;
    if (maxW > 0 || maxH > 0) {
        const int bw = maxW > 0 ? maxW : INT_MAX;
        const int bh = maxH > 0 ? maxH : INT_MAX;
        if (image.width() > bw || image.height() > bh) {
            image = image.scaled(QSize(std::min(bw, image.width()), std::min(bh, image.height())), Qt::KeepAspectRatio, Qt::SmoothTransformation);
        }
    }
    const QByteArray d = QFile::encodeName(dir);
    if (::mkdir(d.constData(), 0700) != 0 && errno != EEXIST) {
        r.error = QStringLiteral("cannot create %1").arg(dir);
        return r;
    }
    // callers delete their files; anything older than 30 minutes was forgotten
    const QDateTime cutoff = QDateTime::currentDateTimeUtc().addSecs(-1800);
    const QFileInfoList old = QDir(dir).entryInfoList({QStringLiteral("shot-*.png")}, QDir::Files, QDir::Time);
    for (int i = 0; i < old.size(); ++i) {
        if (old.at(i).lastModified(QTimeZone::UTC) < cutoff || i >= 200) {
            QFile::remove(old.at(i).absoluteFilePath());
        }
    }
    const QString path = dir + QLatin1Char('/') + name;
    const int fd = ::open(QFile::encodeName(path).constData(), O_WRONLY | O_CREAT | O_EXCL | O_CLOEXEC, 0600);
    if (fd < 0) {
        r.error = QStringLiteral("cannot create %1").arg(path);
        return r;
    }
    QFile f;
    if (!f.open(fd, QIODevice::WriteOnly, QFileDevice::AutoCloseHandle) || !image.save(&f, "PNG", 80)) {
        f.close();
        QFile::remove(path);
        r.error = QStringLiteral("cannot write %1").arg(path);
        return r;
    }
    f.close();
    r.path = path;
    r.width = image.width();
    r.height = image.height();
    return r;
}

void Screenshotter::take(Params &p, const ReplyPtr &reply)
{
    const auto maxW = p.integer(QStringLiteral("maxWidth"), false, 0, kMaxPixels, 0);
    const auto maxH = p.integer(QStringLiteral("maxHeight"), false, 0, kMaxPixels, 0);
    const auto includeCursor = p.boolean(QStringLiteral("includeCursor"), false, false);
    const auto excludeShell = p.boolean(QStringLiteral("excludeShell"), false, false);
    if (!maxW || !maxH || !includeCursor || !excludeShell) {
        return;
    }
    if (!supported()) {
        reply->fail(Err::Unsupported, QStringLiteral("screenshots need OpenGL compositing"));
        return;
    }
    const QJsonValue targetV = p.raw().value(QStringLiteral("target"));
    const QList<LogicalOutput *> outputs = workspace()->outputs();
    if (outputs.isEmpty()) {
        reply->fail(Err::Unsupported, QStringLiteral("no outputs"));
        return;
    }
    LogicalOutput *viewOutput = outputs.front();
    RectF area;
    qreal scale = 1.0;
    Window *window = nullptr;
    auto maxScaleOver = [&](const RectF &r) {
        qreal s = 0;
        for (LogicalOutput *o : outputs) {
            if (o->geometryF().intersects(r)) {
                s = std::max(s, o->scale());
            }
        }
        return s > 0 ? s : 1.0;
    };
    if (targetV.isUndefined() || targetV.isNull() || (targetV.isString() && targetV.toString() == QLatin1String("desktop"))) {
        for (LogicalOutput *o : outputs) {
            area = area.isEmpty() ? o->geometryF() : area.united(o->geometryF());
        }
        scale = maxScaleOver(area);
    } else if (targetV.isObject()) {
        Params t(targetV.toObject());
        if (t.has(QStringLiteral("output"))) {
            const auto name = t.string(QStringLiteral("output"), true, 128);
            if (!name) {
                reply->fail(t.error());
                return;
            }
            LogicalOutput *o = workspace()->findOutput(*name);
            if (!o) {
                reply->fail(Err::NotFound, QStringLiteral("no output '%1'").arg(*name));
                return;
            }
            viewOutput = o;
            area = o->geometryF();
            scale = o->scale();
        } else if (t.has(QStringLiteral("window"))) {
            const auto id = t.string(QStringLiteral("window"), true, 64);
            if (!id) {
                reply->fail(t.error());
                return;
            }
            window = m_windows->find(*id);
            if (!window) {
                reply->fail(Err::NotFound, QStringLiteral("no window with id '%1'").arg(*id));
                return;
            }
            if (window->excludeFromCapture()) {
                reply->fail(Err::Denied, QStringLiteral("the owner excluded this window from screenshots"));
                return;
            }
            if (!window->windowItem() || window->isMinimized() || window->isHidden()) {
                reply->fail(Err::Invalid, QStringLiteral("the window is not visible"));
                return;
            }
            area = window->frameGeometry();
            scale = window->targetScale();
        } else if (t.has(QStringLiteral("region"))) {
            const auto region = t.object(QStringLiteral("region"), true);
            if (!region) {
                reply->fail(t.error());
                return;
            }
            Params rp(*region);
            const auto x = rp.number(QStringLiteral("x"), true, -kCoordLimit, kCoordLimit);
            const auto y = rp.number(QStringLiteral("y"), true, -kCoordLimit, kCoordLimit);
            const auto w = rp.number(QStringLiteral("w"), true, 1, 32768);
            const auto h = rp.number(QStringLiteral("h"), true, 1, 32768);
            if (!x || !y || !w || !h) {
                reply->fail(rp.error());
                return;
            }
            area = RectF(*x, *y, *w, *h);
            scale = maxScaleOver(area);
        } else {
            reply->fail(Err::Invalid, QStringLiteral("'target' must be \"desktop\" or have output, window or region"));
            return;
        }
    } else {
        reply->fail(Err::Invalid, QStringLiteral("'target' must be \"desktop\" or an object"));
        return;
    }
    if (area.isEmpty() || area.width() * scale > kMaxPixels || area.height() * scale > kMaxPixels) {
        reply->fail(Err::Invalid, QStringLiteral("the requested area is empty or too large"));
        return;
    }

    if (m_queue.size() >= kMaxShotsInflight) {
        reply->fail(Err::Busy, QStringLiteral("too many screenshots queued"));
        return;
    }
    m_queue.append(Job{reply, QPointer<Window>(window), viewOutput->name(), area, scale, *maxW, *maxH, *includeCursor, *excludeShell, window != nullptr});
    if (!m_pacing.isActive()) {
        renderNext();
    }
}

// Renders run on the compositor thread (the GPU readback is synchronous, as in KWin's own
// screenshot plugin), so they are paced: at most one every kMinRenderIntervalMs, which keeps a
// client that asks for screenshots in a loop from eating the compositor's frame budget.
void Screenshotter::renderNext()
{
    while (!m_queue.isEmpty()) {
        Job job = m_queue.takeFirst();
        if (!job.reply->alive()) {
            job.reply->fail(Err::Internal, QStringLiteral("client went away"));
            continue;
        }
        if (waylandServer()->isScreenLocked()) {
            job.reply->fail(Err::Denied, QStringLiteral("the screen is locked"));
            continue;
        }
        LogicalOutput *viewOutput = workspace()->findOutput(job.outputName);
        if (!viewOutput && !workspace()->outputs().isEmpty()) {
            viewOutput = workspace()->outputs().front();
        }
        if (!viewOutput || (job.isWindow && !job.window)) {
            job.reply->fail(Err::NotFound, QStringLiteral("the window or output went away"));
            continue;
        }
        LayerScopes *scopes = m_scopes;
        const bool exclude = job.excludeShell;
        auto filter = [scopes, exclude](Window *w) {
            // windows the owner hid from capture stay hidden from the assistant too
            return w->excludeFromCapture() || scopes->isBridgeInternal(w) || (exclude && scopes->isAssistantOverlay(w));
        };
        QElapsedTimer t;
        t.start();
        std::optional<QImage> image = job.isWindow ? renderWindow(job.window, job.area, job.scale, job.includeCursor)
                                                   : renderArea(viewOutput, job.area, job.scale, filter, job.includeCursor);
        const qint64 renderMs = t.elapsed();
        if (!image || image->isNull()) {
            job.reply->fail(Err::Internal, QStringLiteral("rendering the screenshot failed"));
            continue;
        }
        static quint64 counter = 0;
        const QString name = QStringLiteral("shot-%1-%2-%3.png").arg(QString::number(::getpid()), QString::number(++counter), randomToken(4));
        const RectF logical = job.area;
        ReplyPtr reply = job.reply;
        auto *watcher = new QFutureWatcher<ShotResult>(this);
        connect(watcher, &QFutureWatcher<ShotResult>::finished, this, [watcher, reply, logical, renderMs]() {
            const ShotResult r = watcher->result();
            watcher->deleteLater();
            if (!r.error.isEmpty()) {
                reply->fail(Err::Internal, r.error);
                return;
            }
            if (!reply->alive()) {
                QFile::remove(r.path);
                reply->fail(Err::Internal, QStringLiteral("client went away"));
                return;
            }
            reply->ok(QJsonObject{
                {QStringLiteral("path"), r.path},
                {QStringLiteral("width"), r.width},
                {QStringLiteral("height"), r.height},
                {QStringLiteral("originX"), logical.x()},
                {QStringLiteral("originY"), logical.y()},
                {QStringLiteral("logicalWidth"), logical.width()},
                {QStringLiteral("logicalHeight"), logical.height()},
                {QStringLiteral("scaleX"), double(r.width) / logical.width()},
                {QStringLiteral("scaleY"), double(r.height) / logical.height()},
                {QStringLiteral("renderMs"), double(renderMs)},
            });
        });
        watcher->setFuture(QtConcurrent::run(encode, *image, job.maxW, job.maxH, m_dir, name));
        m_pacing.start(std::max<qint64>(kMinRenderIntervalMs, 2 * renderMs));
        return;
    }
}

} // namespace Kristall
