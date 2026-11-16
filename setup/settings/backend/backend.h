/*
    Kristall OS — the backend of Kristall's pages in System Settings (QML module org.kristall.settings)
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QFileSystemWatcher>
#include <QJsonObject>
#include <QObject>
#include <QPointer>
#include <QProcess>
#include <QQmlEngine>
#include <QTimer>
#include <QVariant>

// The shared settings (docs/contracts/settings.md) through `kristall-settings`: one long-lived
// `watch --full --initial` for reading (live, inotify inside the tool), `set` for writing.
// A written value shows at once (optimistic) and is confirmed by the watch.
class KristallSettings : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(Settings)
    QML_SINGLETON
    Q_PROPERTY(QVariantMap data READ data NOTIFY dataChanged)
    Q_PROPERTY(bool loaded READ loaded NOTIFY dataChanged)
public:
    explicit KristallSettings(QObject *parent = nullptr);
    ~KristallSettings() override;
    QVariantMap data() const { return m_data; }
    bool loaded() const { return m_loaded; }
    Q_INVOKABLE QVariant value(const QString &path, const QVariant &fallback = QVariant()) const;
    Q_INVOKABLE void set(const QString &path, const QVariant &value);
    Q_INVOKABLE void unset(const QString &path);
Q_SIGNALS:
    void dataChanged();

private:
    void startWatch();
    QString tool() const;
    QProcess *m_watch = nullptr;
    QByteArray m_buf;
    QVariantMap m_data;
    QVariantMap m_pending; // path -> value written, not yet seen in the watch
    bool m_loaded = false;
};

// A command that prints JSON lines (kristall-update, kristall-power, kristall-setup-helper,
// kristall-assistant-account …): every object is reported as `line`; the last one is `result`.
class JsonProcess : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString program READ program WRITE setProgram NOTIFY changed)
    Q_PROPERTY(QStringList arguments READ arguments WRITE setArguments NOTIFY changed)
    Q_PROPERTY(bool running READ running NOTIFY runningChanged)
    Q_PROPERTY(QVariant result READ result NOTIFY finished)
    Q_PROPERTY(QString output READ output NOTIFY finished)
public:
    explicit JsonProcess(QObject *parent = nullptr);
    ~JsonProcess() override;
    QString program() const { return m_program; }
    void setProgram(const QString &p);
    QStringList arguments() const { return m_args; }
    void setArguments(const QStringList &a);
    bool running() const { return m_proc && m_proc->state() != QProcess::NotRunning; }
    QVariant result() const { return m_result; }
    QString output() const { return m_output; }
    Q_INVOKABLE void start();
    Q_INVOKABLE void run(const QStringList &args); // start with these arguments
    Q_INVOKABLE void write(const QString &line);
    Q_INVOKABLE void terminate();
Q_SIGNALS:
    void changed();
    void runningChanged();
    void line(const QVariant &object);
    void finished(int exitCode, const QVariant &result);

private:
    QString m_program;
    QStringList m_args;
    QProcess *m_proc = nullptr;
    QByteArray m_buf;
    QVariant m_result;
    QString m_output;
};

// A JSON file other components publish (kristall-update's state, the keyboard plugin's status,
// the assistant's "always allow" grants), re-read when it is replaced (inotify on the directory).
class JsonFile : public QObject
{
    Q_OBJECT
    QML_ELEMENT
    Q_PROPERTY(QString path READ path WRITE setPath NOTIFY pathChanged)
    Q_PROPERTY(QVariant data READ data NOTIFY dataChanged)
    Q_PROPERTY(bool exists READ exists NOTIFY dataChanged)
public:
    explicit JsonFile(QObject *parent = nullptr);
    QString path() const { return m_path; }
    void setPath(const QString &p);
    QVariant data() const { return m_data; }
    bool exists() const { return m_exists; }
    Q_INVOKABLE void reload();
    // atomic write (temp + rename), mode 0600 — for the assistant's permissions file (assistant-ipc §7.1)
    Q_INVOKABLE bool write(const QVariant &data);
Q_SIGNALS:
    void pathChanged();
    void dataChanged();

private:
    QString m_path;
    QVariant m_data;
    bool m_exists = false;
    QFileSystemWatcher m_watcher;
    QTimer m_debounce;
};

// Small things a page needs from the system.
class KristallSystem : public QObject
{
    Q_OBJECT
    QML_NAMED_ELEMENT(System)
    QML_SINGLETON
public:
    explicit KristallSystem(QObject *parent = nullptr);
    Q_INVOKABLE QString env(const QString &name, const QString &fallback = QString()) const;
    Q_INVOKABLE QString runtimeDir() const;
    Q_INVOKABLE QString homeDir() const;
    Q_INVOKABLE QString desktopDir() const; // XDG desktop (Schreibtisch), else home
    Q_INVOKABLE bool copyFile(const QString &from, const QString &to); // replaces `to`
    Q_INVOKABLE bool exists(const QString &path) const;
    Q_INVOKABLE void openUrl(const QString &url);
    Q_INVOKABLE void showInFiles(const QString &path);
    Q_INVOKABLE void launch(const QStringList &argv);
    Q_INVOKABLE QString today() const; // yyyy-MM-dd
    Q_INVOKABLE QString formatBytes(double bytes, const QString &lang) const;
    // tests only (KRISTALL_SETTINGS_TEST_DIR set): answers "where is the control named X, and what
    // does it show" through files in that directory, so a test can click it with the real pointer
    Q_INVOKABLE void registerTestRoot(QObject *root);

private:
    void answerTest();
    QPointer<QObject> m_testRoot;
    QFileSystemWatcher *m_testWatch = nullptr;
};
