/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "bridgeplugin.h"
#include "agent.h"
#include "busname.h"
#include "helperclient.h"
#include "screenshot.h"
#include "server.h"
#include "windows.h"

#include "config-kwin.h"
#include "input.h"
#include "wayland_server.h"
#include "workspace.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QJsonArray>
#include <QTimer>

namespace Kristall
{

BridgePlugin::BridgePlugin() = default;

BridgePlugin::~BridgePlugin()
{
    // teardown order: input first (gives the seat back), then everything that serves clients
    delete m_agent;
    delete m_screenshots;
    delete m_windows;
    delete m_helper;
    delete m_scopes;
    delete m_server;
}

bool BridgePlugin::init()
{
#if KRISTALL_BRIDGE_TEST_BROKEN
    logWarning(QStringLiteral("disabled: built with KRISTALL_BRIDGE_TEST_BROKEN (test of fail-soft handling)"));
    return false;
#endif
    if (!KWin::waylandServer() || !KWin::workspace() || !KWin::input() || !KWin::waylandServer()->seat()) {
        logWarning(QStringLiteral("disabled: KWin is not running as a Wayland compositor"));
        return false;
    }
    const QString runtimeDir = qEnvironmentVariable("XDG_RUNTIME_DIR");
    m_server = new Server(this);
    if (!m_server->listen(runtimeDir)) {
        delete m_server;
        m_server = nullptr;
        return false;
    }
    m_server->isLocked = []() {
        return KWin::waylandServer()->isScreenLocked();
    };

    m_scopes = new LayerScopes(this);
    m_helper = new HelperClient(m_scopes, this);
    const bool helperOk = m_helper->start();
    m_windows = new WindowModel(m_server, m_scopes, this);
    m_windows->setHelper(helperOk ? m_helper : nullptr);
    m_agent = new Agent(m_server, m_windows, m_scopes, m_helper, this);
    m_screenshots = new Screenshotter(m_server, m_windows, m_scopes, runtimeDir, this);

    m_server->setCapabilityAvailable(QStringLiteral("windows"), true);
    m_server->setCapabilityAvailable(QStringLiteral("menus"), true);
    m_server->setCapabilityAvailable(QStringLiteral("iconGeometry"), helperOk);
    m_server->setCapabilityAvailable(QStringLiteral("agentInput"), true);
    m_server->setCapabilityAvailable(QStringLiteral("agentText"), true);
    // informational: agent.text keeps the order across text-input and key paths, and outputs carry
    // workArea (clients of older bridges restrict agent.text to key paths for multi-line text)
    m_server->setCapabilityAvailable(QStringLiteral("orderedText"), true);
    m_server->setCapabilityAvailable(QStringLiteral("workArea"), true);
    m_server->setCapabilityAvailable(QStringLiteral("screenshot"), Screenshotter::supported());
    if (!Screenshotter::supported()) {
        logOnce(QStringLiteral("noshot"), QStringLiteral("screenshots unavailable: compositing does not use OpenGL"));
    }
    registerSessionMethods();
    setupMenuView();
    return true;
}

// Global menus (README "Global menus"). Qt decides once per process, when it creates its first
// menu bar, whether menus are exported: only if com.canonical.AppMenu.Registrar exists at that
// moment, which kded's appmenu module publishes while somebody owns org.kde.kappmenuview. Tying
// that name to the shell (as before) meant that every app started while the shell was not
// subscribed — at login before the shell, during a shell restart — kept its in-window menu bar
// for good, and apps that did export lost their menus while the shell was away. So the bridge
// owns org.kde.kappmenuview for KWin's whole life, and signals "a menu bar displays app menus"
// separately with org.kristall.AppMenuView, owned while at least one client is subscribed to the
// "menus" topic. The app side (appmenu/: Qt platform theme, GTK module) watches that name and shows
// the app's own menu bar while it is missing.
void BridgePlugin::setupMenuView()
{
    m_appMenuView = new BusNameClaim(QStringLiteral("org.kde.kappmenuview"), this);
    m_appMenuView->setWanted(true);
    m_kristallMenuView = new BusNameClaim(QStringLiteral("org.kristall.AppMenuView"), this);
    QObject::connect(m_server, &Server::subscribersChanged, this, [this]() {
        m_kristallMenuView->setWanted(m_server->hasSubscribers(QStringLiteral("menus")));
    });
}

void BridgePlugin::registerSessionMethods()
{
    Server *server = m_server;
    server->registerMethod(QStringLiteral("hello"), MethodSpec{false, QString(), [server](Params &p, const ReplyPtr &r) {
                                                         const auto client = p.string(QStringLiteral("client"), false, 64);
                                                         const auto version = p.integer(QStringLiteral("version"), false, 0, 1000000, 1);
                                                         if (!client || !version) {
                                                             return;
                                                         }
                                                         Connection *c = r->connection();
                                                         if (c) {
                                                             c->setClientName(*client);
                                                         }
                                                         r->ok(QJsonObject{
                                                             {QStringLiteral("version"), 1},
                                                             {QStringLiteral("kwin"), QString(KWIN_VERSION_STRING)},
                                                             {QStringLiteral("capabilities"), QJsonArray::fromStringList(server->capabilities())},
                                                             // additions: what this connection may do
                                                             {QStringLiteral("privileged"), c && c->privileged()},
                                                             {QStringLiteral("locked"), KWin::waylandServer()->isScreenLocked()},
                                                         });
                                                     }});
    server->registerMethod(QStringLiteral("subscribe"), MethodSpec{false, QString(), [server](Params &p, const ReplyPtr &r) {
                                                             const auto events = p.stringList(QStringLiteral("events"), true, 16, 32);
                                                             if (!events) {
                                                                 return;
                                                             }
                                                             for (const QString &t : *events) {
                                                                 if (!Server::topics().contains(t)) {
                                                                     r->fail(Err::Invalid, QStringLiteral("unknown topic '%1'").arg(t));
                                                                     return;
                                                                 }
                                                             }
                                                             const QStringList topics = *events;
                                                             // snapshots are taken, and topics activated, when the reply is written:
                                                             // no delta can precede its snapshot
                                                             r->ok(QJsonObject(), [server, topics](Connection *c) {
                                                                 for (const QString &t : topics) {
                                                                     if (c->subscribed(t)) {
                                                                         continue;
                                                                     }
                                                                     c->subscribe({t});
                                                                     for (const QJsonObject &ev : server->snapshot(t)) {
                                                                         c->sendObject(ev);
                                                                     }
                                                                 }
                                                                 Q_EMIT server->subscribersChanged();
                                                             });
                                                         }});
}

} // namespace Kristall
