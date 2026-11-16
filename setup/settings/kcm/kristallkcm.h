/*
    Kristall OS — one generic System Settings module class for all of Kristall's pages
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <KQuickConfigModule>

// Every page applies a change the moment it is made (like the Mac's settings, and like the
// Setup Assistant), so there is nothing to Apply, Reset or Default: no buttons. The page itself
// is QML (main.qml in the plugin's resources) on the org.kristall.settings backend.
class KristallKcm : public KQuickConfigModule
{
    Q_OBJECT
public:
    KristallKcm(QObject *parent, const KPluginMetaData &data)
        : KQuickConfigModule(parent, data)
    {
        setButtons(NoAdditionalButton);
    }
};
