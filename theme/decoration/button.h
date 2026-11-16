// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <KDecoration3/DecorationButton>

namespace Kristall
{
class Decoration;

// One window button ("traffic light"). Its hit box is the circle plus half the gap on each side,
// so the three buttons form one continuous hover region (symbols show on all three at once).
class Button : public KDecoration3::DecorationButton
{
    Q_OBJECT
public:
    Button(KDecoration3::DecorationButtonType type, Decoration *decoration, QObject *parent = nullptr);
    static KDecoration3::DecorationButton *create(KDecoration3::DecorationButtonType type, KDecoration3::Decoration *decoration, QObject *parent);

    void paint(QPainter *painter, const QRectF &repaintArea) override;
    static bool supported(KDecoration3::DecorationButtonType type);

private:
    Decoration *kristall() const;
};

} // namespace Kristall
