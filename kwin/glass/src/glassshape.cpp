/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "glassshape.h"

#include <QJsonArray>

#include <algorithm>
#include <cmath>

namespace Kristall
{

double ShapeSpec::effectiveRadius() const
{
    const double half = std::min(rect.width(), rect.height()) * 0.5;
    if (kind == ShapeKind::Capsule) {
        return half;
    }
    return std::clamp(radius, 0.0, half);
}

double ShapeSpec::effectiveSmoothing() const
{
    return kind == ShapeKind::Capsule ? 0.0 : std::clamp(smoothing, 0.0, 1.0);
}

double ShapeSpec::effectiveBezel() const
{
    const double minSide = std::min(rect.width(), rect.height());
    const double b = bezel.value_or(std::clamp(0.22 * minSide, 4.0, 24.0));
    // the bezel can never be wider than half the shape, otherwise the lens has no flat middle
    return std::clamp(b, 0.0, std::max(0.0, minSide * 0.5));
}

double ShapeSpec::effectiveDepth() const
{
    return std::clamp(depth.value_or(effectiveBezel() * 0.55), 0.0, Limits::maxDepth);
}

static bool isFiniteNumber(const QJsonValue &v)
{
    return v.isDouble() && std::isfinite(v.toDouble());
}

std::optional<QColor> parseColor(const QJsonValue &value)
{
    if (value.isString()) {
        const QString s = value.toString();
        if (!s.startsWith(QLatin1Char('#')) || (s.size() != 7 && s.size() != 9)) {
            return std::nullopt;
        }
        bool ok = false;
        const uint v = s.mid(1).toUInt(&ok, 16);
        if (!ok) {
            return std::nullopt;
        }
        if (s.size() == 7) {
            return QColor::fromRgb((v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff);
        }
        return QColor::fromRgb((v >> 24) & 0xff, (v >> 16) & 0xff, (v >> 8) & 0xff, v & 0xff);
    }
    if (value.isArray()) {
        const QJsonArray a = value.toArray();
        if (a.size() != 3 && a.size() != 4) {
            return std::nullopt;
        }
        double c[4] = {0, 0, 0, 1};
        for (int i = 0; i < a.size(); ++i) {
            if (!isFiniteNumber(a[i])) {
                return std::nullopt;
            }
            c[i] = std::clamp(a[i].toDouble(), 0.0, 1.0);
        }
        return QColor::fromRgbF(c[0], c[1], c[2], c[3]);
    }
    return std::nullopt;
}

namespace
{
struct Ctx
{
    QString *error;
    bool fail(const QString &msg)
    {
        if (error) {
            *error = msg;
        }
        return false;
    }
};

bool readNumber(const QJsonObject &o, const char *key, double lo, double hi, double &out, Ctx &ctx, bool *present = nullptr)
{
    const auto it = o.find(QLatin1String(key));
    if (it == o.end()) {
        if (present) {
            *present = false;
        }
        return true;
    }
    if (present) {
        *present = true;
    }
    if (!isFiniteNumber(*it)) {
        return ctx.fail(QStringLiteral("field '%1' must be a finite number").arg(QLatin1String(key)));
    }
    out = std::clamp(it->toDouble(), lo, hi);
    return true;
}

bool readOptionalNumber(const QJsonObject &o, const char *key, double lo, double hi, std::optional<double> &out, Ctx &ctx)
{
    const auto it = o.find(QLatin1String(key));
    if (it == o.end()) {
        return true;
    }
    if (it->isNull()) {
        out.reset();
        return true;
    }
    double v = 0;
    if (!readNumber(o, key, lo, hi, v, ctx)) {
        return false;
    }
    out = v;
    return true;
}
} // namespace

bool patchShape(ShapeSpec &s, const QJsonObject &o, QString *error)
{
    Ctx ctx{error};

    if (const auto it = o.find(QLatin1String("kind")); it != o.end()) {
        const QString k = it->toString();
        if (k == QLatin1String("rect")) {
            s.kind = ShapeKind::Rect;
        } else if (k == QLatin1String("capsule")) {
            s.kind = ShapeKind::Capsule;
        } else {
            return ctx.fail(QStringLiteral("field 'kind' must be \"rect\" or \"capsule\""));
        }
    }

    double x = s.rect.x(), y = s.rect.y(), w = s.rect.width(), h = s.rect.height();
    if (!readNumber(o, "x", -Limits::maxCoordinate, Limits::maxCoordinate, x, ctx)
        || !readNumber(o, "y", -Limits::maxCoordinate, Limits::maxCoordinate, y, ctx)
        || !readNumber(o, "w", 0, Limits::maxCoordinate, w, ctx)
        || !readNumber(o, "h", 0, Limits::maxCoordinate, h, ctx)) {
        return false;
    }
    s.rect = QRectF(x, y, w, h);

    if (!readNumber(o, "radius", 0, Limits::maxCoordinate, s.radius, ctx)
        || !readNumber(o, "smoothing", 0, 1, s.smoothing, ctx)
        || !readNumber(o, "merge", 0, Limits::maxMerge, s.merge, ctx)
        || !readNumber(o, "opacity", 0, 1, s.opacity, ctx)
        || !readOptionalNumber(o, "tintAmount", 0, 1, s.tintAmount, ctx)
        || !readOptionalNumber(o, "depth", 0, Limits::maxDepth, s.depth, ctx)
        || !readOptionalNumber(o, "bezel", 0, Limits::maxBezel, s.bezel, ctx)) {
        return false;
    }

    if (const auto it = o.find(QLatin1String("variant")); it != o.end()) {
        const QString v = it->toString();
        if (v == QLatin1String("regular")) {
            s.variant = Variant::Regular;
        } else if (v == QLatin1String("clear")) {
            s.variant = Variant::Clear;
        } else {
            return ctx.fail(QStringLiteral("field 'variant' must be \"regular\" or \"clear\""));
        }
    }

    if (const auto it = o.find(QLatin1String("tint")); it != o.end()) {
        if (it->isNull()) {
            s.tint.reset();
        } else if (auto c = parseColor(*it)) {
            s.tint = *c;
        } else {
            return ctx.fail(QStringLiteral("field 'tint' must be null, \"#RRGGBB\", \"#RRGGBBAA\" or [r,g,b(,a)]"));
        }
    }

    if (const auto it = o.find(QLatin1String("pointer")); it != o.end()) {
        if (it->isNull()) {
            s.pointer.reset();
        } else {
            const QJsonArray a = it->toArray();
            if (!it->isArray() || a.size() != 2 || !isFiniteNumber(a[0]) || !isFiniteNumber(a[1])) {
                return ctx.fail(QStringLiteral("field 'pointer' must be null or [x, y]"));
            }
            s.pointer = QPointF(std::clamp(a[0].toDouble(), -Limits::maxCoordinate, Limits::maxCoordinate),
                                std::clamp(a[1].toDouble(), -Limits::maxCoordinate, Limits::maxCoordinate));
        }
    }

    if (const auto it = o.find(QLatin1String("pressed")); it != o.end()) {
        if (!it->isBool()) {
            return ctx.fail(QStringLiteral("field 'pressed' must be a boolean"));
        }
        s.pressed = it->toBool();
    }

    if (const auto it = o.find(QLatin1String("group")); it != o.end()) {
        if (it->isNull()) {
            s.group.clear();
        } else if (it->isString() && it->toString().size() <= Limits::maxIdLength) {
            s.group = it->toString();
        } else {
            return ctx.fail(QStringLiteral("field 'group' must be null or a string of at most 128 characters"));
        }
    }
    return true;
}

std::optional<ShapeSpec> parseShape(const QJsonObject &o, QString *error)
{
    const QJsonValue id = o.value(QLatin1String("id"));
    if (!id.isString() || id.toString().isEmpty() || id.toString().size() > Limits::maxIdLength) {
        if (error) {
            *error = QStringLiteral("every shape needs a non-empty string 'id' of at most 128 characters");
        }
        return std::nullopt;
    }
    for (const char *key : {"x", "y", "w", "h"}) {
        if (!o.contains(QLatin1String(key))) {
            if (error) {
                *error = QStringLiteral("shape '%1' is missing '%2'").arg(id.toString(), QLatin1String(key));
            }
            return std::nullopt;
        }
    }
    ShapeSpec s;
    s.id = id.toString();
    if (!patchShape(s, o, error)) {
        return std::nullopt;
    }
    return s;
}

} // namespace Kristall
