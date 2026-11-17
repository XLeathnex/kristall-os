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
    void syncMenuView();
    void retryMenuView();
    int m_menuViewRetries = 0;
    bool m_menuViewWanted = false;
    bool m_menuViewOwned = false;

    Server *m_server = nullptr;
    LayerScopes *m_scopes = nullptr;
    WindowModel *m_windows = nullptr;
    HelperClient *m_helper = nullptr;
    Agent *m_agent = nullptr;
    Screenshotter *m_screenshots = nullptr;
};

} // namespace Kristall
