/*
    Kristall OS — app side of the global menu bar (Qt 6)
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    A Qt platform-theme plugin with the key "kristall" (QT_QPA_PLATFORMTHEME=kristall, set for the
    session by /usr/lib/environment.d/50-kristall-appmenu.conf). It does not theme anything: it
    creates the theme Qt would have used anyway (KDE's, from plasma-integration) and returns that
    very object, so every app looks and behaves exactly as before. It only adds a small guard to
    widget apps that keeps their menu bars usable:

    * While a Kristall menu bar displays application menus (the bridge owns the D-Bus name
      org.kristall.AppMenuView), menu bars stay native: exported over DBusMenu to the top menu bar,
      hidden in the window. That is Qt's normal behaviour.
    * When that name is gone for a moment (the shell crashed and is restarting, or no shell at all),
      Qt alone would leave the app without any menus: its menu bar is native and hidden for the rest
      of the process. The guard then turns such menu bars into ordinary in-window menu bars, and
      back into native ones (exported again) as soon as the name returns.

    Without the KDE theme (plasma-integration missing) the plugin returns nothing and Qt picks its
    usual theme; Flatpak apps do not see the plugin and are not affected either.
*/
#include <QActionEvent>
#include <QApplication>
#include <QDBusConnection>
#include <QDBusConnectionInterface>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusServiceWatcher>
#include <QMenu>
#include <QMenuBar>
#include <QPointer>
#include <QTimer>
#include <QWindow>
#include <qpa/qplatformmenu.h>
#include <qpa/qplatformtheme.h>
#include <qpa/qplatformthemefactory_p.h>
#include <qpa/qplatformthemeplugin.h>

namespace
{

const QString kViewName = QStringLiteral("org.kristall.AppMenuView");
const char *const kInWindowProperty = "_kristall_inWindowMenuBar"; // set on menu bars the guard made in-window

// How long the menu bar may be missing before apps show their own: long enough that a shell
// restart (about 2 s) does not make window contents jump, short enough to be a fallback.
int graceMs(bool seenBefore)
{
    bool ok = false;
    const int forced = qEnvironmentVariableIntValue("KRISTALL_APPMENU_FALLBACK_MS", &ok); // tests
    if (ok && forced >= 0) {
        return forced;
    }
    return seenBefore ? 3000 : 8000; // at login the shell may start a few seconds after the app
}

bool hasVisibleMenus(const QMenuBar *bar)
{
    const auto actions = bar->actions();
    for (const QAction *a : actions) {
        if (a->isVisible() && a->menu()) {
            return true;
        }
    }
    return false;
}

class MenuBarGuard : public QObject
{
public:
    explicit MenuBarGuard(QApplication *app)
        : QObject(app)
    {
        QDBusConnection bus = QDBusConnection::sessionBus();
        if (!bus.isConnected() || !bus.interface()) {
            return; // no session bus: no global menus either; Qt keeps in-window menu bars
        }
        m_grace.setSingleShot(true);
        connect(&m_grace, &QTimer::timeout, this, [this]() {
            setFallback(true);
        });
        auto *watcher = new QDBusServiceWatcher(kViewName, bus, QDBusServiceWatcher::WatchForOwnerChange, this);
        connect(watcher, &QDBusServiceWatcher::serviceOwnerChanged, this, [this](const QString &, const QString &, const QString &owner) {
            viewChanged(!owner.isEmpty());
        });
        auto *call = new QDBusPendingCallWatcher(bus.interface()->asyncCall(QStringLiteral("NameHasOwner"), kViewName), this);
        connect(call, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *w) {
            const QDBusPendingReply<bool> reply = *w;
            w->deleteLater();
            if (!m_known) { // a NameOwnerChanged that arrived first is newer
                viewChanged(reply.isValid() && reply.value());
            }
        });
    }

    bool eventFilter(QObject *object, QEvent *event) override
    {
        // installed only while falling back: menu bars created or filled meanwhile become in-window too
        switch (event->type()) {
        case QEvent::ActionAdded:
        case QEvent::ActionChanged:
        case QEvent::Polish:
            if (auto *bar = qobject_cast<QMenuBar *>(object); bar && bar->isNativeMenuBar()) {
                QPointer<QMenuBar> guarded(bar);
                QMetaObject::invokeMethod(
                    this,
                    [this, guarded]() {
                        if (guarded) {
                            apply(guarded);
                        }
                    },
                    Qt::QueuedConnection);
            }
            break;
        default:
            break;
        }
        return false;
    }

private:
    void viewChanged(bool present)
    {
        m_known = true;
        if (present) {
            const bool lost = m_lost;
            m_seen = true;
            m_lost = false;
            m_grace.stop();
            if (m_fallback) {
                setFallback(false);
            } else if (lost) {
                reannounce(); // KWin may have restarted meanwhile: tell the new one where the menus are
            }
        } else {
            m_lost = m_seen;
            if (!m_fallback && !m_grace.isActive()) {
                m_grace.start(graceMs(m_seen));
            }
        }
    }

    void setFallback(bool on)
    {
        if (m_fallback == on) {
            return;
        }
        m_fallback = on;
        if (on) {
            qApp->installEventFilter(this);
        } else {
            qApp->removeEventFilter(this);
        }
        const auto widgets = QApplication::allWidgets();
        for (QWidget *w : widgets) {
            if (auto *bar = qobject_cast<QMenuBar *>(w)) {
                apply(bar);
            }
        }
    }

    void apply(QMenuBar *bar)
    {
        if (m_fallback) {
            if (bar->isNativeMenuBar() && hasVisibleMenus(bar)) {
                bar->setProperty(kInWindowProperty, true);
                bar->setNativeMenuBar(false); // drops the export and shows the bar in the window
            }
        } else if (bar->property(kInWindowProperty).toBool()) {
            bar->setProperty(kInWindowProperty, QVariant());
            makeNative(bar);
        }
    }

    // QMenuBar::setNativeMenuBar(true) only creates the platform menu bar; it neither fills it nor
    // attaches it to the window (QMenuBar does both when menus are added and when it is reparented).
    static void makeNative(QMenuBar *bar)
    {
        bar->setNativeMenuBar(true);
        if (!bar->isNativeMenuBar()) {
            return; // the theme declined (no registrar when this process made its first menu bar)
        }
        bar->setVisible(false);
        const auto actions = bar->actions();
        for (QAction *a : actions) { // remove + add again: QMenuBar fills the new platform menu bar
            QActionEvent removed(QEvent::ActionRemoved, a);
            QCoreApplication::sendEvent(bar, &removed);
        }
        for (qsizetype i = 0; i < actions.size(); ++i) {
            QActionEvent added(QEvent::ActionAdded, actions.at(i), i + 1 < actions.size() ? actions.at(i + 1) : nullptr);
            QCoreApplication::sendEvent(bar, &added);
        }
        attach(bar);
    }

    static void attach(QMenuBar *bar)
    {
        QWidget *window = bar->window();
        if (bar->platformMenuBar() && window && window->windowHandle()) {
            bar->platformMenuBar()->handleReparent(window->windowHandle());
        }
    }

    void reannounce()
    {
        const auto widgets = QApplication::allWidgets();
        for (QWidget *w : widgets) {
            if (auto *bar = qobject_cast<QMenuBar *>(w); bar && bar->isNativeMenuBar()) {
                attach(bar);
            }
        }
    }

    QTimer m_grace;
    bool m_known = false;
    bool m_seen = false; // the menu bar was there at some point in this process
    bool m_lost = false;
    bool m_fallback = false;
};

void installGuard()
{
    auto *app = qobject_cast<QApplication *>(QCoreApplication::instance());
    if (!app || qEnvironmentVariableIsSet("KDE_NO_GLOBAL_MENU")) {
        return; // Qt Quick-only processes have no QMenuBar; KDE_NO_GLOBAL_MENU: never exported
    }
    if (QGuiApplication::platformName().startsWith(QLatin1String("wayland-org.kde.kwin"))) {
        return; // KWin itself
    }
    new MenuBarGuard(app);
}

} // namespace

class KristallMenuThemePlugin : public QPlatformThemePlugin
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID QPlatformThemeFactoryInterface_iid FILE "kristall.json")
public:
    QPlatformTheme *create(const QString &key, const QStringList &paramList) override
    {
        Q_UNUSED(key)
        Q_UNUSED(paramList)
        QString inner = qEnvironmentVariable("KRISTALL_QPA_PLATFORMTHEME", QStringLiteral("kde"));
        if (inner.isEmpty() || inner == QLatin1String("kristall")) {
            inner = QStringLiteral("kde");
        }
        QPlatformTheme *theme = QPlatformThemeFactory::create(inner);
        if (!theme) {
            return nullptr; // Qt goes on with its usual list of themes
        }
        // the application object is still being constructed: install once the event loop runs
        if (QCoreApplication::instance()) {
            QMetaObject::invokeMethod(QCoreApplication::instance(), &installGuard, Qt::QueuedConnection);
        }
        return theme;
    }
};

#include "kristallmenutheme.moc"
