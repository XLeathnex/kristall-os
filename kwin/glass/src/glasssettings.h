/*
    Kristall OS — Liquid Glass compositor effect
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later

    Reads the shared settings file (docs/ARCHITECTURE.md §3, key "appearance") and the inputs
    that resolve "auto" values: the Plasma colour scheme for theme=auto and UPower's OnBattery
    for glassQuality=auto. Everything is event driven (file watcher, D-Bus signals); nothing polls.
*/
#pragma once

#include <QFileSystemWatcher>
#include <QJsonObject>
#include <QObject>
#include <QTimer>
#include <QVariantMap>

#include <optional>

#include <KConfigWatcher>

namespace Kristall
{

enum class QualityTier {
    High,
    Efficient,
};

class GlassSettings : public QObject
{
    Q_OBJECT

public:
    explicit GlassSettings(QObject *parent = nullptr);

    double glass() const { return m_glass; } ///< 0 ultra-clear .. 1 fully tinted
    QString themeSetting() const { return m_theme; } ///< "light" | "dark" | "auto"
    bool darkTheme() const; ///< resolved
    QString qualitySetting() const { return m_quality; } ///< "auto" | "high" | "efficient"
    bool reduceTransparency() const { return m_reduceTransparency; }
    std::optional<bool> onBattery() const { return m_onBattery; }

    QString userFile() const { return m_userFile; }

Q_SIGNALS:
    void changed();

private Q_SLOTS:
    void onUPowerPropertiesChanged(const QString &interface, const QVariantMap &changedProps, const QStringList &invalidated);

private:
    void scheduleReload();
    void reload();
    void reloadPlasmaScheme();
    void rewatch();
    void setupUPower();

    QString m_userFile;
    QString m_defaultsFile;
    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
    KConfigWatcher::Ptr m_kdeglobalsWatcher;

    double m_glass = 0.3;
    QString m_theme = QStringLiteral("auto");
    QString m_quality = QStringLiteral("auto");
    bool m_reduceTransparency = false;
    bool m_plasmaDark = false;
    std::optional<bool> m_onBattery;
};

} // namespace Kristall
