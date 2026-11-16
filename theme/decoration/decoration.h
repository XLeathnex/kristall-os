// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall window decoration (KDecoration3, KWin 6.8).
#pragma once

#include <KDecoration3/Decoration>
#include <KDecoration3/DecorationButtonGroup>

#include <QColor>
#include <QVariant>
#include <QPointer>

namespace Kristall
{

// Metrics in logical pixels (docs/contracts/theme.md §3; design.md §5 "windows (theme)").
namespace Metrics
{
constexpr qreal TitleBarHeight = 28;   // titlebar-only height of a Mac window
constexpr qreal ButtonDiameter = 12;
constexpr qreal ButtonSpacing = 8;     // gap between circles (centre distance 20)
constexpr qreal ButtonInset = 12;      // window edge to the first circle
constexpr qreal RadiusSmall = 16;      // dialogs, fixed-size windows
constexpr qreal Radius = 20;           // resizable main windows (they carry a toolbar)
constexpr qreal ResizeBorder = 6;      // invisible resize margin outside the window
}

class Decoration : public KDecoration3::Decoration
{
    Q_OBJECT
public:
    explicit Decoration(QObject *parent = nullptr, const QVariantList &args = QVariantList());
    ~Decoration() override;

    bool init() override;
    void paint(QPainter *painter, const QRectF &repaintArea) override;

    // state shared with the buttons
    bool groupHovered() const { return m_hoveredButtons > 0; }
    void buttonHoverChanged(bool hovered);
    bool isDark() const;
    QColor titleBarColor() const;
    QColor textColor() const;
    qreal cornerRadius() const;

private:
    void recalculate();
    void layoutButtons();
    void updateShadow();
    bool isTiledOrMaximized() const;

    KDecoration3::DecorationButtonGroup *m_left = nullptr;
    KDecoration3::DecorationButtonGroup *m_right = nullptr;
    int m_hoveredButtons = 0;
};

} // namespace Kristall
