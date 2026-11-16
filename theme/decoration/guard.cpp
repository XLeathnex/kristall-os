// SPDX-License-Identifier: GPL-3.0-or-later
// Plugin factory with a crash guard. KWin already falls back to Breeze when this plugin is
// missing or fails to load. What it cannot catch is a decoration that loads but crashes KWin:
// KWin would restart and crash again. So every KWin start that loads us is counted in
// $XDG_RUNTIME_DIR/kristall/decoration.guard; a start that stays up for 30 s clears the count.
// On the third start within that pattern we hand out Breeze decorations for the rest of the
// login session (the file stays until logout; delete it to retry).
#include "button.h"
#include "decoration.h"

#include <KPluginFactory>
#include <KPluginMetaData>

#include <QCoreApplication>
#include <QDateTime>
#include <QDir>
#include <QFile>
#include <QTimer>
#include <QtGlobal>

namespace Kristall
{
namespace
{
QString guardPath()
{
    const QByteArray runtime = qgetenv("XDG_RUNTIME_DIR");
    if (runtime.isEmpty()) {
        return QString();
    }
    return QString::fromLocal8Bit(runtime) + QStringLiteral("/kristall/decoration.guard");
}

// returns true when this start should use the fallback decoration
bool countStart()
{
    if (qEnvironmentVariableIsSet("KRISTALL_DECORATION_FORCE_FALLBACK")) {
        return true;
    }
    // only KWin's own starts count (System Settings previews and kde-gtk-config load us too)
    if (!QCoreApplication::applicationName().startsWith(QLatin1String("kwin"))) {
        return false;
    }
    const QString path = guardPath();
    if (path.isEmpty()) {
        return false;
    }
    QDir().mkpath(QFileInfo(path).absolutePath());
    int count = 0;
    QFile f(path);
    if (f.open(QIODevice::ReadOnly)) {
        count = QString::fromLatin1(f.readAll()).trimmed().split(QLatin1Char(' ')).value(0).toInt();
        f.close();
    }
    if (count >= 2) { // two unhealthy starts already: this is the third
        return true;
    }
    if (f.open(QIODevice::WriteOnly | QIODevice::Truncate)) {
        f.write(QByteArray::number(count + 1) + ' ' + QByteArray::number(QDateTime::currentSecsSinceEpoch()) + '\n');
        f.close();
    }
    // healthy after 30 s: clear the count (one-shot timer, no polling)
    QTimer::singleShot(30000, [path] {
        QFile g(path);
        if (g.open(QIODevice::ReadOnly)) {
            const int c = QString::fromLatin1(g.readAll()).trimmed().split(QLatin1Char(' ')).value(0).toInt();
            g.close();
            if (c < 3) {
                QFile::remove(path);
            }
        }
    });
    return false;
}
} // namespace

class DecorationFactory : public KPluginFactory
{
    Q_OBJECT
    Q_PLUGIN_METADATA(IID KPluginFactory_iid FILE "kristall.json")
    Q_INTERFACES(KPluginFactory)
public:
    DecorationFactory()
    {
        if (countStart()) {
            const auto md = KPluginMetaData::findPluginById(QStringLiteral("org.kde.kdecoration3"), QStringLiteral("org.kde.breeze"));
            if (md.isValid()) {
                if (auto r = KPluginFactory::loadFactory(md)) {
                    m_fallback = r.plugin;
                    qWarning("kristall-decoration: crash guard active, using the Breeze decoration for this session");
                }
            }
        }
        registerPlugin<Kristall::Decoration>();
    }

protected:
    QObject *create(const char *iface, QWidget *parentWidget, QObject *parent, const QVariantList &args) override
    {
        if (m_fallback && qstrcmp(iface, KDecoration3::Decoration::staticMetaObject.className()) == 0) {
            return m_fallback->create<KDecoration3::Decoration>(parent, args);
        }
        return KPluginFactory::create(iface, parentWidget, parent, args);
    }

private:
    KPluginFactory *m_fallback = nullptr;
};

} // namespace Kristall

#include "guard.moc"
