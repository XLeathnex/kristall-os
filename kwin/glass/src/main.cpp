/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "glasseffect.h"

namespace Kristall
{

KWIN_EFFECT_FACTORY_SUPPORTED(GlassEffect, "metadata.json", return GlassEffect::supported();)

} // namespace Kristall

#include "main.moc"
