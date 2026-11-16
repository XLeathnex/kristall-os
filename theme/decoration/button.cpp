// SPDX-License-Identifier: GPL-3.0-or-later
// Window buttons in the Mac's manner: close, minimise, zoom as 12-px circles. Coloured in the
// active window (and in an inactive one while the pointer is over the group), grey otherwise;
// their symbols appear while the pointer is anywhere over the group. Zoom maximises/restores
// (see theme.md §3 for why it is not full screen).
#include "button.h"
#include "decoration.h"

#include <KDecoration3/DecoratedWindow>

#include <QPainter>
#include <QPainterPath>

namespace Kristall
{
using KDecoration3::DecorationButtonType;

namespace
{
struct Colors {
    QColor fill, edge, glyph;
};

Colors colorsFor(DecorationButtonType type)
{
    switch (type) {
    case DecorationButtonType::Close:
        return {QColor(0xFF, 0x5F, 0x57), QColor(0xE0, 0x44, 0x3E), QColor(0x4D, 0x00, 0x00)};
    case DecorationButtonType::Minimize:
        return {QColor(0xFE, 0xBC, 0x2E), QColor(0xDE, 0xA1, 0x23), QColor(0x99, 0x57, 0x00)};
    default:
        return {QColor(0x28, 0xC8, 0x40), QColor(0x1A, 0xAB, 0x29), QColor(0x00, 0x65, 0x00)};
    }
}
} // namespace

Button::Button(DecorationButtonType type, Decoration *decoration, QObject *parent)
    : KDecoration3::DecorationButton(type, decoration, parent)
{
    const qreal box = Metrics::ButtonDiameter + Metrics::ButtonSpacing;
    setGeometry(QRectF(0, 0, box, Metrics::TitleBarHeight));
    connect(this, &DecorationButton::hoveredChanged, decoration, &Decoration::buttonHoverChanged);
    // zoom: maximise/restore with any mouse button (KWin's middle/right = vertical/horizontal
    // maximise would surprise a Mac owner)
    if (type == DecorationButtonType::Maximize) {
        setAcceptedButtons(Qt::LeftButton);
    }
    // enabled state and the click actions are wired by KDecoration3::DecorationButton itself
    auto w = decoration->window();
    connect(w, &KDecoration3::DecoratedWindow::maximizedChanged, this, [this] {
        update();
    });
    connect(w, &KDecoration3::DecoratedWindow::activeChanged, this, [this] {
        update();
    });
}

bool Button::supported(DecorationButtonType type)
{
    return type == DecorationButtonType::Close || type == DecorationButtonType::Minimize || type == DecorationButtonType::Maximize;
}

KDecoration3::DecorationButton *Button::create(DecorationButtonType type, KDecoration3::Decoration *decoration, QObject *parent)
{
    auto d = qobject_cast<Decoration *>(decoration);
    if (!d || !supported(type)) {
        return nullptr; // the Mac has no other title-bar buttons; KWin skips null buttons
    }
    return new Button(type, d, parent);
}

Decoration *Button::kristall() const
{
    return static_cast<Decoration *>(decoration());
}

void Button::paint(QPainter *painter, const QRectF &repaintArea)
{
    Q_UNUSED(repaintArea)
    if (!isVisible()) {
        return;
    }
    auto deco = kristall();
    auto w = deco->window();
    const qreal d = Metrics::ButtonDiameter;
    const QRectF g = geometry();
    const QRectF circle(g.center().x() - d / 2, g.center().y() - d / 2, d, d);

    const bool hovered = deco->groupHovered();
    const bool coloured = isEnabled() && (w->isActive() || hovered);
    Colors c = colorsFor(type());
    if (!coloured) {
        const bool dark = deco->isDark();
        c.fill = dark ? QColor(0x4A, 0x4A, 0x4C) : QColor(0xDC, 0xDC, 0xDE);
        c.edge = dark ? QColor(0x3C, 0x3C, 0x3E) : QColor(0xC8, 0xC8, 0xCA);
    } else if (isPressed()) {
        c.fill = c.fill.darker(118);
        c.edge = c.edge.darker(118);
        c.glyph = c.glyph.darker(140);
    }

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);
    // the edge is half a logical pixel inside the circle (one device pixel at 2x)
    const qreal edge = 0.5;
    painter->setPen(Qt::NoPen);
    painter->setBrush(c.edge);
    painter->drawEllipse(circle);
    painter->setBrush(c.fill);
    painter->drawEllipse(circle.adjusted(edge, edge, -edge, -edge));

    if (coloured && hovered) {
        QColor glyph = c.glyph;
        glyph.setAlphaF(0.85);
        const QPointF o = circle.center();
        const qreal s = d;
        QPen pen(glyph, 1.1, Qt::SolidLine, Qt::RoundCap, Qt::RoundJoin);
        switch (type()) {
        case DecorationButtonType::Close: {
            painter->setPen(pen);
            const qreal k = 0.20 * s;
            painter->drawLine(QPointF(o.x() - k, o.y() - k), QPointF(o.x() + k, o.y() + k));
            painter->drawLine(QPointF(o.x() - k, o.y() + k), QPointF(o.x() + k, o.y() - k));
            break;
        }
        case DecorationButtonType::Minimize: {
            pen.setWidthF(1.2);
            painter->setPen(pen);
            const qreal k = 0.27 * s;
            painter->drawLine(QPointF(o.x() - k, o.y()), QPointF(o.x() + k, o.y()));
            break;
        }
        default: {
            // two triangles: outward when the window is not maximised, inward when it is
            painter->setPen(Qt::NoPen);
            painter->setBrush(glyph);
            const QPointF tl = circle.topLeft();
            auto P = [&](qreal x, qreal y) {
                return QPointF(tl.x() + x * s, tl.y() + y * s);
            };
            QPainterPath path;
            if (!w->isMaximized()) {
                path.moveTo(P(0.27, 0.27));
                path.lineTo(P(0.63, 0.27));
                path.lineTo(P(0.27, 0.63));
                path.closeSubpath();
                path.moveTo(P(0.73, 0.73));
                path.lineTo(P(0.37, 0.73));
                path.lineTo(P(0.73, 0.37));
                path.closeSubpath();
            } else {
                path.moveTo(P(0.47, 0.47));
                path.lineTo(P(0.47, 0.16));
                path.lineTo(P(0.16, 0.47));
                path.closeSubpath();
                path.moveTo(P(0.53, 0.53));
                path.lineTo(P(0.53, 0.84));
                path.lineTo(P(0.84, 0.53));
                path.closeSubpath();
            }
            painter->drawPath(path);
            break;
        }
        }
    }
    painter->restore();
}

} // namespace Kristall
