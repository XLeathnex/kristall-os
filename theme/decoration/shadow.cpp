// SPDX-License-Identifier: GPL-3.0-or-later
// Soft layered window shadow (design.md §7 "window"): a large ambient layer (blur 48, y 16,
// opacity 0.32 light / ×1.6 dark, ≤ 0.6) plus a tight contact layer. Rendered once per
// (radius, dark, active) into a nine-patch and shared by all windows.
#include "shadow.h"

#include <QHash>
#include <QImage>
#include <QPainter>
#include <QPainterPath>
#include <cmath>
#include <vector>

namespace Kristall
{
namespace
{
struct Layer {
    qreal blur;
    qreal y;
    qreal opacity;
};

// separable gaussian on the alpha channel of an ARGB32 premultiplied image (black shadow)
void blurAlpha(std::vector<float> &a, int w, int h, qreal sigma)
{
    if (sigma < 0.5) {
        return;
    }
    const int r = int(std::ceil(sigma * 3));
    std::vector<float> k(2 * r + 1);
    float sum = 0;
    for (int i = -r; i <= r; ++i) {
        k[i + r] = std::exp(-(i * i) / (2 * sigma * sigma));
        sum += k[i + r];
    }
    for (float &v : k) {
        v /= sum;
    }
    std::vector<float> tmp(a.size());
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            float s = 0;
            for (int i = -r; i <= r; ++i) {
                const int xx = std::clamp(x + i, 0, w - 1);
                s += a[y * w + xx] * k[i + r];
            }
            tmp[y * w + x] = s;
        }
    }
    for (int y = 0; y < h; ++y) {
        for (int x = 0; x < w; ++x) {
            float s = 0;
            for (int i = -r; i <= r; ++i) {
                const int yy = std::clamp(y + i, 0, h - 1);
                s += tmp[yy * w + x] * k[i + r];
            }
            a[y * w + x] = s;
        }
    }
}

std::vector<float> shapeMask(int w, int h, const QRectF &rect, qreal radius)
{
    QImage img(w, h, QImage::Format_Alpha8);
    img.fill(0);
    QPainter p(&img);
    p.setRenderHint(QPainter::Antialiasing);
    p.setPen(Qt::NoPen);
    p.setBrush(Qt::black);
    p.drawRoundedRect(rect, radius, radius);
    p.end();
    std::vector<float> out(size_t(w) * h);
    for (int y = 0; y < h; ++y) {
        const uchar *line = img.constScanLine(y);
        for (int x = 0; x < w; ++x) {
            out[size_t(y) * w + x] = line[x] / 255.0f;
        }
    }
    return out;
}
} // namespace

std::shared_ptr<KDecoration3::DecorationShadow> windowShadow(qreal radius, bool dark, bool active)
{
    static QHash<QString, std::shared_ptr<KDecoration3::DecorationShadow>> cache;
    const QString key = QStringLiteral("%1-%2-%3").arg(radius).arg(dark).arg(active);
    if (auto it = cache.constFind(key); it != cache.constEnd()) {
        return *it;
    }

    const qreal darkFactor = dark ? 1.6 : 1.0;
    const qreal inactive = active ? 1.0 : 0.55;
    const qreal shrink = active ? 1.0 : 0.7;
    const Layer layers[] = {
        {48 * shrink, 16 * shrink, std::min(0.32 * darkFactor, 0.6) * inactive},
        {3, 1, std::min(0.18 * darkFactor, 0.4) * (active ? 1.0 : 0.8)},
    };

    const int margin = int(std::ceil(48 * 1.25 + 16));
    const int core = int(std::ceil(2 * radius)) + 1;
    const int w = 2 * margin + core;
    const int h = w;
    const QRectF window(margin, margin, core, core);

    std::vector<float> total(size_t(w) * h, 0.0f);
    for (const Layer &l : layers) {
        auto a = shapeMask(w, h, window.translated(0, l.y), radius);
        blurAlpha(a, w, h, l.blur / 2.0);
        for (size_t i = 0; i < a.size(); ++i) {
            // layers combine like stacked translucent paint
            total[i] = total[i] + a[i] * l.opacity * (1.0f - total[i]);
        }
    }
    // cut out the window itself so translucent windows do not show their own shadow
    const auto hole = shapeMask(w, h, window, radius);

    QImage img(w, h, QImage::Format_ARGB32_Premultiplied);
    for (int y = 0; y < h; ++y) {
        auto *line = reinterpret_cast<QRgb *>(img.scanLine(y));
        for (int x = 0; x < w; ++x) {
            const size_t i = size_t(y) * w + x;
            const int alpha = std::clamp(int(std::lround(total[i] * (1.0f - hole[i]) * 255.0f)), 0, 255);
            line[x] = qRgba(0, 0, 0, alpha);
        }
    }

    auto shadow = std::make_shared<KDecoration3::DecorationShadow>();
    shadow->setPadding(QMarginsF(margin, margin, margin, margin));
    shadow->setInnerShadowRect(QRectF(margin, margin, core, core));
    shadow->setShadow(img);
    cache.insert(key, shadow);
    return shadow;
}

} // namespace Kristall
