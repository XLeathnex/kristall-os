/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once
#include <QLoggingCategory>

// Messages go to KWin's journal stream; filter with:
//   journalctl --user -b | grep kristall.glass     (or QT_LOGGING_RULES="kristall.glass.debug=true")
Q_DECLARE_LOGGING_CATEGORY(KRISTALL_GLASS)
