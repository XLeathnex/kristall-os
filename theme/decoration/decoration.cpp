// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall window decoration: a 28-px title bar in the window's header colour (so it reads as one
// surface with the app's toolbar), Mac window buttons on the left, the title centred, large
// rounded corners on all four sides (KWin clips the client with the decoration's border radius),
// a one-device-pixel outline so dark windows separate from dark backgrounds, and a soft layered
// shadow. Structure follows the Breeze decoration (GPL-2.0-or-later, KDE) without sharing code.
#include "decoration.h"
#include "button.h"
#include "shadow.h"
#include "titles.h"

#include <KDecoration3/DecoratedWindow>
#include <KDecoration3/DecorationSettings>
#include <KDecoration3/ScaleHelpers>

#include <QFontMetricsF>
#include <QPainter>
#include <QPainterPath>
#include <QTimer>

namespace Kristall
{
using KDecoration3::ColorGroup;
using KDecoration3::ColorRole;

Decoration::Decoration(QObject *parent, const QVariantList &args)
    : KDecoration3::Decoration(parent, args)
{
}

Decoration::~Decoration() = default;

bool Decoration::init()
{
    auto w = window();
    auto s = settings();

    auto relayout = [this] {
        recalculate();
        layoutButtons();
        updateShadow();
        update();
    };
    connect(w, &KDecoration3::DecoratedWindow::activeChanged, this, [this] {
        recalculate(); // outline colour
        updateShadow();
        update();
    });
    connect(w, &KDecoration3::DecoratedWindow::captionChanged, this, [this] {
        update(titleBar());
    });
    connect(w, &KDecoration3::DecoratedWindow::maximizedChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::adjacentScreenEdgesChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::widthChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::shadedChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::resizeableChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::paletteChanged, this, relayout);
    connect(w, &KDecoration3::DecoratedWindow::nextScaleChanged, this, relayout);
    connect(s.get(), &KDecoration3::DecorationSettings::fontChanged, this, relayout);
    connect(s.get(), &KDecoration3::DecorationSettings::reconfigured, this, relayout);
    connect(s.get(), &KDecoration3::DecorationSettings::decorationButtonsLeftChanged, this, [this] {
        QTimer::singleShot(0, this, &Decoration::layoutButtons);
    });
    connect(s.get(), &KDecoration3::DecorationSettings::decorationButtonsRightChanged, this, [this] {
        QTimer::singleShot(0, this, &Decoration::layoutButtons);
    });

    m_left = new KDecoration3::DecorationButtonGroup(KDecoration3::DecorationButtonGroup::Position::Left, this, &Button::create);
    m_right = new KDecoration3::DecorationButtonGroup(KDecoration3::DecorationButtonGroup::Position::Right, this, &Button::create);
    m_left->setSpacing(0);
    m_right->setSpacing(0);

    recalculate();
    layoutButtons();
    updateShadow();
    return true;
}

bool Decoration::isTiledOrMaximized() const
{
    return window()->isMaximized() || window()->adjacentScreenEdges() != Qt::Edges();
}

qreal Decoration::cornerRadius() const
{
    if (isTiledOrMaximized()) {
        return 0;
    }
    auto w = window();
    // design.md §5: titlebar-only windows 16, windows with a toolbar 20. A decoration cannot see
    // the toolbar; resizable non-modal windows are main windows (they carry one), the rest are
    // dialogs and panels.
    return (w->isModal() || !w->isResizeable()) ? Metrics::RadiusSmall : Metrics::Radius;
}

QColor Decoration::titleBarColor() const
{
    auto w = window();
    return w->color(w->isActive() ? ColorGroup::Active : ColorGroup::Inactive, ColorRole::TitleBar);
}

QColor Decoration::textColor() const
{
    auto w = window();
    return w->color(w->isActive() ? ColorGroup::Active : ColorGroup::Inactive, ColorRole::Foreground);
}

bool Decoration::isDark() const
{
    const QColor c = window()->color(ColorGroup::Active, ColorRole::TitleBar);
    return qGray(c.rgb()) < 128;
}

void Decoration::recalculate()
{
    auto w = window();
    const qreal scale = w->nextScale();
    const bool tiled = isTiledOrMaximized();
    const qreal top = w->isShaded() ? Metrics::TitleBarHeight : KDecoration3::snapToPixelGrid(Metrics::TitleBarHeight, scale);
    setBorders(QMarginsF(0, top, 0, 0));
    const qreal ext = tiled ? 0 : KDecoration3::snapToPixelGrid(Metrics::ResizeBorder, scale);
    setResizeOnlyBorders(QMarginsF(ext, w->isMaximizedVertically() ? 0 : ext, ext, ext));
    setTitleBar(QRectF(0, 0, w->width(), top));

    const qreal r = cornerRadius();
    setBorderRadius(KDecoration3::BorderRadius(r));
    if (w->isMaximized()) {
        setBorderOutline(KDecoration3::BorderOutline());
    } else {
        // one device pixel: black 15 % on light windows, white 20 % on dark ones
        QColor edge = isDark() ? QColor(255, 255, 255, w->isActive() ? 51 : 38) : QColor(0, 0, 0, w->isActive() ? 38 : 28);
        setBorderOutline(KDecoration3::BorderOutline(KDecoration3::pixelSize(scale), edge, KDecoration3::BorderRadius(r)));
    }
    setOpaque(w->isMaximized());
}

void Decoration::layoutButtons()
{
    if (!m_left || !m_right) {
        return;
    }
    const qreal box = Metrics::ButtonDiameter + Metrics::ButtonSpacing;
    const qreal h = borderTop();
    for (auto *b : m_left->buttons() + m_right->buttons()) {
        b->setGeometry(QRectF(0, 0, box, h));
    }
    // the first circle sits ButtonInset from the window edge; its box starts half a gap earlier
    const qreal edgeOffset = Metrics::ButtonInset - Metrics::ButtonSpacing / 2;
    m_left->setPos(QPointF(edgeOffset, 0));
    m_right->setPos(QPointF(size().width() - m_right->geometry().width() - edgeOffset, 0));
    update();
}

void Decoration::updateShadow()
{
    if (isTiledOrMaximized()) {
        // tiled/maximised windows still get a faint shadow so they read as separate from neighbours
        setShadow(windowShadow(0, isDark(), false));
        return;
    }
    setShadow(windowShadow(cornerRadius(), isDark(), window()->isActive()));
}

void Decoration::buttonHoverChanged(bool hovered)
{
    m_hoveredButtons = std::max(0, m_hoveredButtons + (hovered ? 1 : -1));
    for (auto *b : m_left->buttons() + m_right->buttons()) {
        b->update();
    }
}

void Decoration::paint(QPainter *painter, const QRectF &repaintArea)
{
    Q_UNUSED(repaintArea)
    auto w = window();
    const QRectF bar = titleBar();
    const qreal r = cornerRadius();

    painter->save();
    painter->setRenderHint(QPainter::Antialiasing, true);
    painter->setPen(Qt::NoPen);
    painter->setBrush(titleBarColor());
    if (r > 0) {
        // rounded top corners; the straight bottom edge meets the client's own header colour
        QPainterPath path;
        path.addRoundedRect(QRectF(bar.x(), bar.y(), bar.width(), bar.height() + r), r, r);
        painter->setClipRect(bar);
        painter->drawPath(path);
        painter->setClipping(false);
    } else {
        painter->drawRect(bar);
    }

    // title: centred over the whole width, elided so it never runs under the buttons; our app
    // names instead of KDE's product names ("Home — Dateien", titles.h)
    const QString caption = ownerCaption(w->caption());
    if (!caption.isEmpty()) {
        // the system title font (kdeglobals [WM] activeFont, Inter 13 px); Mac titles are bold
        QFont font = settings()->font();
        font.setWeight(QFont::Bold);
        painter->setFont(font);
        painter->setPen(textColor());
        const QFontMetricsF fm(font);
        const qreal buttonsRight = m_left ? m_left->geometry().right() + 8 : 0;
        const qreal rightLimit = (m_right && !m_right->buttons().isEmpty()) ? m_right->geometry().left() - 8 : bar.width() - 8;
        const qreal half = std::max<qreal>(0, std::min(bar.width() / 2 - buttonsRight, rightLimit - bar.width() / 2));
        const QRectF textRect(bar.width() / 2 - half, bar.y(), 2 * half, bar.height());
        const QString text = fm.elidedText(caption, Qt::ElideRight, textRect.width());
        painter->drawText(textRect, Qt::AlignCenter | Qt::TextSingleLine, text);
    }
    painter->restore();

    if (m_left) {
        m_left->paint(painter, repaintArea);
    }
    if (m_right) {
        m_right->paint(painter, repaintArea);
    }
}

} // namespace Kristall
