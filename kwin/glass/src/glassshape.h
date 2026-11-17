/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    The shape model of the glass protocol (docs/contracts/glass.md, "Shape object").
*/
#pragma once

#include <QColor>
#include <QJsonObject>
#include <QList>
#include <QPointF>
#include <QRectF>
#include <QString>

#include <optional>

namespace Kristall
{

enum class ShapeKind {
    Rect,
    Capsule,
};

enum class Variant {
    Regular,
    Clear,
};

/// One glass shape exactly as a client declared it (surface-local logical pixels).
struct ShapeSpec
{
    QString id;
    ShapeKind kind = ShapeKind::Rect;
    QRectF rect;
    double radius = 16.0; ///< corner radius, rect only
    double smoothing = 0.6; ///< corner smoothing 0 (circular) .. 1 (very continuous), rect only
    Variant variant = Variant::Regular;
    std::optional<QColor> tint;
    std::optional<double> tintAmount;
    std::optional<double> depth; ///< max refraction displacement at the rim, logical px
    std::optional<double> bezel; ///< width of the curved rim, logical px
    std::optional<QPointF> pointer; ///< surface-local pointer position for the follow highlight
    bool pressed = false;
    QString group; ///< shapes with the same non-empty group may merge
    double merge = 12.0; ///< smooth-union distance for the group, logical px
    double opacity = 1.0;

    bool operator==(const ShapeSpec &) const = default;

    double effectiveRadius() const;
    double effectiveSmoothing() const;
    double effectiveBezel() const;
    double effectiveDepth() const;
};

namespace Limits
{
constexpr int maxShapesPerSurface = 64;
constexpr int maxIdLength = 128;
constexpr double maxCoordinate = 100000.0;
constexpr double maxDepth = 64.0;
constexpr double maxBezel = 128.0;
constexpr double maxMerge = 200.0;
}

/// Parses a complete shape object. Unknown keys are ignored. Returns std::nullopt and sets
/// @p error on invalid input.
std::optional<ShapeSpec> parseShape(const QJsonObject &object, QString *error);

/// Applies the fields present in @p object onto @p shape (used by "patch"). "id" is ignored.
bool patchShape(ShapeSpec &shape, const QJsonObject &object, QString *error);

/// Parses "#RRGGBB", "#RRGGBBAA" or [r,g,b(,a)] with components 0..1.
std::optional<QColor> parseColor(const QJsonValue &value);

} // namespace Kristall
