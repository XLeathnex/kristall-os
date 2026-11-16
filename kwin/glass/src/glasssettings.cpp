/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "glasssettings.h"
#include "glasslog.h"

#include <QColor>
#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCallWatcher>
#include <QDBusPendingReply>
#include <QDBusVariant>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonDocument>
#include <QStandardPaths>

#include <KConfigGroup>
#include <KSharedConfig>

#include <algorithm>
#include <cmath>

namespace Kristall
{

static QJsonObject readJsonFile(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        return {};
    }
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(f.read(4 * 1024 * 1024), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        qCWarning(KRISTALL_GLASS) << "ignoring unparsable settings file" << path << err.errorString();
        return {};
    }
    return doc.object();
}

// "user file overrides defaults key by key": objects merge recursively, anything else replaces.
static QJsonObject merged(QJsonObject base, const QJsonObject &over)
{
    for (auto it = over.begin(); it != over.end(); ++it) {
        if (it->isObject() && base.value(it.key()).isObject()) {
            base[it.key()] = merged(base.value(it.key()).toObject(), it->toObject());
        } else {
            base[it.key()] = *it;
        }
    }
    return base;
}

GlassSettings::GlassSettings(QObject *parent)
    : QObject(parent)
{
    QString configHome = qEnvironmentVariable("XDG_CONFIG_HOME");
    if (configHome.isEmpty()) {
        configHome = QDir::homePath() + QStringLiteral("/.config");
    }
    m_userFile = configHome + QStringLiteral("/kristall/settings.json");
    m_defaultsFile = qEnvironmentVariable("KRISTALL_DEFAULTS_SETTINGS", QStringLiteral(KRISTALL_DEFAULTS_FILE));

    m_debounce.setSingleShot(true);
    m_debounce.setInterval(50);
    connect(&m_debounce, &QTimer::timeout, this, &GlassSettings::reload);
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, &GlassSettings::scheduleReload);
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, &GlassSettings::scheduleReload);

    m_kdeglobalsWatcher = KConfigWatcher::create(KSharedConfig::openConfig(QStringLiteral("kdeglobals")));
    connect(m_kdeglobalsWatcher.data(), &KConfigWatcher::configChanged, this, [this](const KConfigGroup &group) {
        if (group.name() == QLatin1String("Colors:Window") || group.name() == QLatin1String("General")) {
            const bool before = darkTheme();
            reloadPlasmaScheme();
            if (before != darkTheme()) {
                Q_EMIT changed();
            }
        }
    });
    reloadPlasmaScheme();
    setupUPower();
    reload();
}

void GlassSettings::scheduleReload()
{
    m_debounce.start();
}

void GlassSettings::rewatch()
{
    // Writers replace the file atomically (rename), which drops a file watch, so watch the
    // directory as well and re-add the file every time.
    const QStringList files = m_watcher.files();
    if (!files.isEmpty()) {
        m_watcher.removePaths(files);
    }
    const QStringList dirs = m_watcher.directories();
    if (!dirs.isEmpty()) {
        m_watcher.removePaths(dirs);
    }
    QStringList paths;
    for (const QString &file : {m_userFile, m_defaultsFile}) {
        if (QFileInfo::exists(file)) {
            paths << file;
        }
        // watch the nearest existing ancestor directory so creation is noticed too
        QDir dir = QFileInfo(file).absoluteDir();
        while (!dir.exists() && dir.cdUp()) { }
        if (dir.exists()) {
            paths << dir.absolutePath();
        }
    }
    paths.removeDuplicates();
    if (!paths.isEmpty()) {
        m_watcher.addPaths(paths);
    }
}

void GlassSettings::reload()
{
    const QJsonObject all = merged(readJsonFile(m_defaultsFile), readJsonFile(m_userFile));
    const QJsonObject appearance = all.value(QLatin1String("appearance")).toObject();

    const double glassBefore = m_glass;
    const QString themeBefore = m_theme;
    const QString qualityBefore = m_quality;
    const bool reduceBefore = m_reduceTransparency;

    const QJsonValue glass = appearance.value(QLatin1String("glass"));
    if (glass.isDouble() && std::isfinite(glass.toDouble())) {
        m_glass = std::clamp(glass.toDouble(), 0.0, 1.0);
    } else {
        m_glass = 0.3;
    }
    const QString theme = appearance.value(QLatin1String("theme")).toString();
    m_theme = (theme == QLatin1String("light") || theme == QLatin1String("dark")) ? theme : QStringLiteral("auto");
    const QString quality = appearance.value(QLatin1String("glassQuality")).toString();
    m_quality = (quality == QLatin1String("high") || quality == QLatin1String("efficient")) ? quality : QStringLiteral("auto");
    m_reduceTransparency = appearance.value(QLatin1String("reduceTransparency")).toBool(false);

    rewatch();

    if (!qFuzzyCompare(glassBefore, m_glass) || themeBefore != m_theme || qualityBefore != m_quality || reduceBefore != m_reduceTransparency) {
        qCInfo(KRISTALL_GLASS) << "settings: glass" << m_glass << "theme" << m_theme << "quality" << m_quality
                               << "reduceTransparency" << m_reduceTransparency;
        Q_EMIT changed();
    }
}

void GlassSettings::reloadPlasmaScheme()
{
    KSharedConfig::Ptr config = KSharedConfig::openConfig(QStringLiteral("kdeglobals"));
    config->reparseConfiguration();
    const QColor bg = config->group(QStringLiteral("Colors:Window")).readEntry("BackgroundNormal", QColor(239, 240, 241));
    m_plasmaDark = bg.lightnessF() < 0.5;
}

bool GlassSettings::darkTheme() const
{
    if (m_theme == QLatin1String("dark")) {
        return true;
    }
    if (m_theme == QLatin1String("light")) {
        return false;
    }
    return m_plasmaDark;
}

void GlassSettings::setupUPower()
{
    QDBusConnection bus = QDBusConnection::systemBus();
    if (!bus.isConnected()) {
        qCInfo(KRISTALL_GLASS) << "no system bus; glassQuality=auto will use the high tier";
        return;
    }
    bus.connect(QStringLiteral("org.freedesktop.UPower"), QStringLiteral("/org/freedesktop/UPower"),
                QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("PropertiesChanged"), this,
                SLOT(onUPowerPropertiesChanged(QString, QVariantMap, QStringList)));
    QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.UPower"), QStringLiteral("/org/freedesktop/UPower"),
                                                      QStringLiteral("org.freedesktop.DBus.Properties"), QStringLiteral("Get"));
    msg << QStringLiteral("org.freedesktop.UPower") << QStringLiteral("OnBattery");
    // asynchronous: the compositor thread must never block on D-Bus
    auto *watcher = new QDBusPendingCallWatcher(bus.asyncCall(msg), this);
    connect(watcher, &QDBusPendingCallWatcher::finished, this, [this](QDBusPendingCallWatcher *w) {
        QDBusPendingReply<QDBusVariant> reply = *w;
        if (!reply.isError()) {
            const bool v = reply.value().variant().toBool();
            if (m_onBattery != v) {
                m_onBattery = v;
                Q_EMIT changed();
            }
        }
        w->deleteLater();
    });
}

void GlassSettings::onUPowerPropertiesChanged(const QString &interface, const QVariantMap &changedProps, const QStringList &)
{
    if (interface != QLatin1String("org.freedesktop.UPower")) {
        return;
    }
    const auto it = changedProps.find(QStringLiteral("OnBattery"));
    if (it != changedProps.end() && m_onBattery != it->toBool()) {
        m_onBattery = it->toBool();
        qCInfo(KRISTALL_GLASS) << "power source changed, on battery:" << *m_onBattery;
        Q_EMIT changed();
    }
}

} // namespace Kristall
