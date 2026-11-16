/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "keysettings.h"

#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QStandardPaths>

Q_LOGGING_CATEGORY(KRISTALL_KEYBOARD, "kristall.keyboard", QtInfoMsg)

namespace Kristall
{

static QJsonObject readObject(const QString &path)
{
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        return {};
    }
    QJsonParseError err;
    const QJsonDocument doc = QJsonDocument::fromJson(f.read(4 * 1024 * 1024), &err);
    if (err.error != QJsonParseError::NoError || !doc.isObject()) {
        qCWarning(KRISTALL_KEYBOARD) << "ignoring invalid settings file" << path;
        return {};
    }
    return doc.object();
}

static void deepMerge(QJsonObject &into, const QJsonObject &from)
{
    for (auto it = from.begin(); it != from.end(); ++it) {
        if (it.value().isObject() && into.value(it.key()).isObject()) {
            QJsonObject sub = into.value(it.key()).toObject();
            deepMerge(sub, it.value().toObject());
            into.insert(it.key(), sub);
        } else {
            into.insert(it.key(), it.value());
        }
    }
}

static QString userFile()
{
    const QString env = qEnvironmentVariable("KRISTALL_SETTINGS_FILE");
    if (!env.isEmpty()) {
        return env;
    }
    return QStandardPaths::writableLocation(QStandardPaths::GenericConfigLocation) + QStringLiteral("/kristall/settings.json");
}

static QStringList dropinDirs()
{
    const QString env = qEnvironmentVariable("KRISTALL_SETTINGS_DROPIN_DIRS");
    if (!env.isEmpty()) {
        return env.split(QLatin1Char(':'), Qt::SkipEmptyParts);
    }
    return {QStringLiteral("/usr/share/kristall/defaults/settings.d"), QStringLiteral("/etc/kristall/settings.d")};
}

KeySettings::KeySettings(QObject *parent)
    : QObject(parent)
{
    m_debounce.setSingleShot(true);
    m_debounce.setInterval(50);
    connect(&m_debounce, &QTimer::timeout, this, [this]() {
        rewatch();
        reload();
    });
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, this, [this]() {
        m_debounce.start();
    });
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, this, [this]() {
        m_debounce.start();
    });
    rewatch();
    reload();
}

QStringList KeySettings::layerFiles() const
{
    QStringList files;
    const QString defaults = qEnvironmentVariable("KRISTALL_SETTINGS_DEFAULTS", QStringLiteral("/usr/share/kristall/defaults/settings.json"));
    files << defaults;
    for (const QString &dir : dropinDirs()) {
        QDir d(dir);
        const QStringList names = d.entryList({QStringLiteral("*.json")}, QDir::Files, QDir::Name);
        for (const QString &n : names) {
            files << d.filePath(n);
        }
    }
    files << userFile();
    return files;
}

QStringList KeySettings::watchDirs() const
{
    QStringList dirs = dropinDirs();
    const QString user = QFileInfo(userFile()).absolutePath();
    QDir().mkpath(user); // like `kristall-settings watch`: the directory must exist to be watched
    dirs << user;
    return dirs;
}

void KeySettings::rewatch()
{
    const QStringList want = watchDirs();
    QStringList have = m_watcher.directories();
    for (const QString &d : want) {
        if (QFileInfo::exists(d) && !have.contains(d)) {
            m_watcher.addPath(d);
        }
    }
}

void KeySettings::reload()
{
    QJsonObject merged;
    for (const QString &f : layerFiles()) {
        deepMerge(merged, readObject(f));
    }
    const QJsonObject kb = merged.value(QStringLiteral("keyboard")).toObject();
    const bool mac = kb.value(QStringLiteral("macShortcuts")).toBool(true);
    auto strings = [](const QJsonValue &v) {
        QStringList out;
        for (const QJsonValue &x : v.toArray()) {
            if (x.isString() && !x.toString().isEmpty()) {
                out << x.toString().toLower();
            }
        }
        return out;
    };
    const QStringList pass = strings(kb.value(QStringLiteral("passthroughApps")));
    const QStringList terms = strings(kb.value(QStringLiteral("terminalApps")));
    if (mac == m_mac && pass == m_passthrough && terms == m_terminals) {
        return;
    }
    m_mac = mac;
    m_passthrough = pass;
    m_terminals = terms;
    qCInfo(KRISTALL_KEYBOARD) << "settings: macShortcuts" << m_mac << "passthrough" << m_passthrough << "terminals" << m_terminals;
    Q_EMIT changed();
}

} // namespace Kristall
