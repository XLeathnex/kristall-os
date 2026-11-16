/*
    Kristall OS — Mac-style keyboard inside the compositor
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QFileSystemWatcher>
#include <QJsonObject>
#include <QLoggingCategory>
#include <QObject>
#include <QStringList>
#include <QTimer>

Q_DECLARE_LOGGING_CATEGORY(KRISTALL_KEYBOARD)

namespace Kristall
{

// The `keyboard` key of the shared settings (docs/contracts/settings.md), merged exactly like
// kristall-settings does (defaults file, settings.d drop-ins in name order, /etc drop-ins, the
// user file; deep merge). Watched with inotify on the directories (writers replace files by
// rename); bursts are coalesced for 50 ms. Nothing is read on the input path.
class KeySettings : public QObject
{
    Q_OBJECT
public:
    explicit KeySettings(QObject *parent = nullptr);

    bool macShortcuts() const { return m_mac; }
    QStringList passthroughApps() const { return m_passthrough; }
    QStringList terminalApps() const { return m_terminals; }

Q_SIGNALS:
    void changed();

private:
    void reload();
    void rewatch();
    QStringList layerFiles() const;
    QStringList watchDirs() const;

    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
    bool m_mac = true;
    QStringList m_passthrough;
    QStringList m_terminals;
};

} // namespace Kristall
