// SPDX-License-Identifier: GPL-3.0-or-later
#pragma once

#include <QString>

namespace Kristall
{
// The title as the owner should read it: Qt appends the app's own product name to every window
// title ("Home — Dolphin"); for the apps we rename (Files, Text Editor …) that name becomes ours
// ("Home — Dateien"). The names come from the app manifest's product_names
// (docs/contracts/apps.md), read once per process; every other title is returned unchanged.
QString ownerCaption(const QString &caption);
}
