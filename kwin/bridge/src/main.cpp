/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "bridgeplugin.h"

#include "plugin.h"

namespace Kristall
{

class BridgePluginFactory : public KWin::PluginFactory
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID PluginFactory_iid FILE "metadata.json")
    Q_INTERFACES(KWin::PluginFactory)

public:
    explicit BridgePluginFactory() = default;

    // Returning nullptr makes KWin skip the plugin: the session carries on without the bridge.
    std::unique_ptr<KWin::Plugin> create() const override
    {
        auto plugin = std::make_unique<BridgePlugin>();
        if (!plugin->init()) {
            return nullptr;
        }
        return plugin;
    }
};

} // namespace Kristall

#include "main.moc"
