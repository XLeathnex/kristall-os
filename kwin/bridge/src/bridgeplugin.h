/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include "plugin.h"

#include <memory>

namespace Kristall
{

class Server;
class LayerScopes;
class WindowModel;
class HelperClient;
class Agent;
class Screenshotter;
class BusNameClaim;

class BridgePlugin : public KWin::Plugin
{
    Q_OBJECT
public:
    BridgePlugin();
    ~BridgePlugin() override;

    // false: the bridge disabled itself (reason logged once); KWin then drops the plugin
    bool init();

private:
    void registerSessionMethods();
    void setupMenuView();

    // org.kde.kappmenuview: owned for KWin's whole life (apps decide once, at their first menu
    // bar, whether to export it). org.kristall.AppMenuView: owned while a client displays app menus
    // (`menus` subscribers); apps watch it to show their own menu bars while nobody does.
    BusNameClaim *m_appMenuView = nullptr;
    BusNameClaim *m_kristallMenuView = nullptr;

    Server *m_server = nullptr;
    LayerScopes *m_scopes = nullptr;
    WindowModel *m_windows = nullptr;
    HelperClient *m_helper = nullptr;
    Agent *m_agent = nullptr;
    Screenshotter *m_screenshots = nullptr;
};

} // namespace Kristall
