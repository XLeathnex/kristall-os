/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "keysettings.h"
#include "remapper.h"

#include "plugin.h"

namespace Kristall
{

class KeyboardPlugin : public KWin::Plugin
{
    Q_OBJECT
public:
    KeyboardPlugin()
        : m_settings(new KeySettings(this))
        , m_remapper(new Remapper(m_settings, this))
    {
    }
    ~KeyboardPlugin() override
    {
        // give every device back to KWin and release whatever we hold before anything else goes
        m_remapper->stop();
    }
    bool init()
    {
#if KRISTALL_KEYBOARD_TEST_BROKEN
        qCWarning(KRISTALL_KEYBOARD) << "disabled: built with KRISTALL_KEYBOARD_TEST_BROKEN (fail-safe test)";
        Remapper::writeStatus(false, false, QStringLiteral("not-loaded"));
        return false;
#endif
        return m_remapper->start();
    }

private:
    KeySettings *m_settings;
    Remapper *m_remapper;
};

class KeyboardPluginFactory : public KWin::PluginFactory
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID PluginFactory_iid FILE "metadata.json")
    Q_INTERFACES(KWin::PluginFactory)

public:
    explicit KeyboardPluginFactory() = default;

    // nullptr: KWin carries on without us and every key behaves as stock (the fail-safe)
    std::unique_ptr<KWin::Plugin> create() const override
    {
        auto plugin = std::make_unique<KeyboardPlugin>();
        if (!plugin->init()) {
            return nullptr;
        }
        return plugin;
    }
};

} // namespace Kristall

#include "main.moc"
