// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once
#include <KDecoration3/DecorationShadow>
#include <memory>

namespace Kristall
{
std::shared_ptr<KDecoration3::DecorationShadow> windowShadow(qreal radius, bool dark, bool active);
}
