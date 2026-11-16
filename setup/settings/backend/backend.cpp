/*
    Kristall OS — the backend of Kristall's pages in System Settings
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "backend.h"

#include <QDBusConnection>
#include <QDBusMessage>
#include <QDBusPendingCall>
#include <QDate>
#include <QJSValue>
#include <QDir>
#include <QFile>
#include <QFileInfo>
#include <QJsonArray>
#include <QJsonDocument>
#include <QSaveFile>
#include <QStandardPaths>
#include <QQuickItem>
#include <QUrl>

// ------------------------------------------------------------------------------------ Settings

// JavaScript objects and arrays arrive from QML as QJSValue: make them plain variants
static QVariant plain(const QVariant &v)
{
    if (v.metaType() == QMetaType::fromType<QJSValue>()) {
        return v.value<QJSValue>().toVariant(QJSValue::ConvertJSObjects);
    }
    return v;
}

KristallSettings::KristallSettings(QObject *parent)
    : QObject(parent)
{
    startWatch();
}

KristallSettings::~KristallSettings()
{
    if (m_watch) {
        m_watch->disconnect(this);
        m_watch->kill();
        m_watch->waitForFinished(500);
    }
}

QString KristallSettings::tool() const
{
    const QString env = qEnvironmentVariable("KRISTALL_SETTINGS_CMD");
    return env.isEmpty() ? QStringLiteral("kristall-settings") : env;
}

void KristallSettings::startWatch()
{
    m_watch = new QProcess(this);
    m_watch->setProcessChannelMode(QProcess::ForwardedErrorChannel);
    connect(m_watch, &QProcess::readyReadStandardOutput, this, [this]() {
        m_buf += m_watch->readAllStandardOutput();
        int nl;
        bool changed = false;
        while ((nl = m_buf.indexOf('\n')) >= 0) {
            const QByteArray line = m_buf.left(nl);
            m_buf.remove(0, nl + 1);
            const QJsonObject o = QJsonDocument::fromJson(line).object();
            if (o.contains(QStringLiteral("settings"))) {
                m_data = o.value(QStringLiteral("settings")).toObject().toVariantMap();
                m_loaded = true;
                changed = true;
            }
        }
        if (changed) {
            // what the file now says replaces what we wrote optimistically
            for (auto it = m_pending.begin(); it != m_pending.end();) {
                QVariant cur = m_data;
                for (const QString &p : it.key().split(QLatin1Char('.'))) {
                    cur = cur.toMap().value(p);
                }
                if (QJsonValue::fromVariant(cur) == QJsonValue::fromVariant(it.value())) {
                    it = m_pending.erase(it);
                } else {
                    ++it;
                }
            }
            Q_EMIT dataChanged();
        }
    });
    connect(m_watch, &QProcess::finished, this, [this]() {
        // the tool should never exit; if it does, try again in a few seconds (fail soft)
        QTimer::singleShot(3000, this, [this]() {
            m_watch->start(tool(), {QStringLiteral("watch"), QStringLiteral("--full"), QStringLiteral("--initial")});
        });
    });
    m_watch->start(tool(), {QStringLiteral("watch"), QStringLiteral("--full"), QStringLiteral("--initial")});
}

QVariant KristallSettings::value(const QString &path, const QVariant &fallback) const
{
    if (m_pending.contains(path)) {
        return m_pending.value(path);
    }
    QVariant cur = m_data;
    for (const QString &p : path.split(QLatin1Char('.'))) {
        const QVariantMap m = cur.toMap();
        if (!m.contains(p)) {
            return fallback;
        }
        cur = m.value(p);
    }
    return cur.isNull() ? fallback : cur;
}

void KristallSettings::set(const QString &path, const QVariant &rawValue)
{
    const QVariant value = plain(rawValue);
    QJsonValue jv = QJsonValue::fromVariant(value);
    QByteArray json;
    if (jv.isObject()) {
        json = QJsonDocument(jv.toObject()).toJson(QJsonDocument::Compact);
    } else if (jv.isArray()) {
        json = QJsonDocument(jv.toArray()).toJson(QJsonDocument::Compact);
    } else {
        // a scalar: wrap in an array and strip the brackets
        json = QJsonDocument(QJsonArray{jv}).toJson(QJsonDocument::Compact);
        json = json.mid(1, json.size() - 2);
    }
    m_pending.insert(path, value);
    Q_EMIT dataChanged();
    QProcess::startDetached(tool(), {QStringLiteral("set"), path, QString::fromUtf8(json)});
}

void KristallSettings::unset(const QString &path)
{
    m_pending.remove(path);
    QProcess::startDetached(tool(), {QStringLiteral("unset"), path});
}

// ------------------------------------------------------------------------------------ JsonProcess

JsonProcess::JsonProcess(QObject *parent)
    : QObject(parent)
{
}

JsonProcess::~JsonProcess()
{
    if (m_proc) {
        m_proc->disconnect(this);
        if (m_proc->state() != QProcess::NotRunning) {
            m_proc->terminate();
            m_proc->waitForFinished(500);
        }
    }
}

void JsonProcess::setProgram(const QString &p)
{
    if (p != m_program) {
        m_program = p;
        Q_EMIT changed();
    }
}

void JsonProcess::setArguments(const QStringList &a)
{
    if (a != m_args) {
        m_args = a;
        Q_EMIT changed();
    }
}

void JsonProcess::run(const QStringList &args)
{
    setArguments(args);
    start();
}

void JsonProcess::start()
{
    if (running()) {
        return;
    }
    if (!m_proc) {
        m_proc = new QProcess(this);
        m_proc->setProcessChannelMode(QProcess::ForwardedErrorChannel);
        connect(m_proc, &QProcess::readyReadStandardOutput, this, [this]() {
            const QByteArray data = m_proc->readAllStandardOutput();
            m_buf += data;
            m_output += QString::fromUtf8(data);
            int nl;
            while ((nl = m_buf.indexOf('\n')) >= 0) {
                const QByteArray l = m_buf.left(nl).trimmed();
                m_buf.remove(0, nl + 1);
                QJsonParseError err;
                const QJsonDocument doc = QJsonDocument::fromJson(l, &err);
                if (err.error == QJsonParseError::NoError && (doc.isObject() || doc.isArray())) {
                    m_result = doc.toVariant();
                    Q_EMIT line(m_result);
                }
            }
        });
        connect(m_proc, &QProcess::stateChanged, this, &JsonProcess::runningChanged);
        connect(m_proc, &QProcess::finished, this, [this](int code) {
            Q_EMIT finished(code, m_result);
        });
        connect(m_proc, &QProcess::errorOccurred, this, [this](QProcess::ProcessError e) {
            if (e == QProcess::FailedToStart) {
                m_result = QVariantMap{{QStringLiteral("ok"), false}, {QStringLiteral("error"), QStringLiteral("not-installed")}};
                Q_EMIT finished(127, m_result);
            }
        });
    }
    m_buf.clear();
    m_output.clear();
    m_result = QVariant();
    m_proc->start(m_program, m_args);
}

void JsonProcess::write(const QString &l)
{
    if (running()) {
        m_proc->write(l.toUtf8() + "\n");
    }
}

void JsonProcess::terminate()
{
    if (running()) {
        m_proc->terminate();
    }
}

// ------------------------------------------------------------------------------------ JsonFile

JsonFile::JsonFile(QObject *parent)
    : QObject(parent)
{
    m_debounce.setSingleShot(true);
    m_debounce.setInterval(50);
    connect(&m_debounce, &QTimer::timeout, this, &JsonFile::reload);
    connect(&m_watcher, &QFileSystemWatcher::directoryChanged, &m_debounce, qOverload<>(&QTimer::start));
    connect(&m_watcher, &QFileSystemWatcher::fileChanged, &m_debounce, qOverload<>(&QTimer::start));
}

void JsonFile::setPath(const QString &p)
{
    if (p == m_path) {
        return;
    }
    if (!m_watcher.directories().isEmpty()) {
        m_watcher.removePaths(m_watcher.directories());
    }
    m_path = p;
    const QString dir = QFileInfo(p).absolutePath();
    if (QFileInfo::exists(dir)) {
        m_watcher.addPath(dir);
    }
    Q_EMIT pathChanged();
    reload();
}

void JsonFile::reload()
{
    QFile f(m_path);
    QVariant d;
    const bool ex = f.open(QIODevice::ReadOnly);
    if (ex) {
        d = QJsonDocument::fromJson(f.readAll()).toVariant();
    }
    if (d != m_data || ex != m_exists) {
        m_data = d;
        m_exists = ex;
        Q_EMIT dataChanged();
    }
}

bool JsonFile::write(const QVariant &rawData)
{
    const QVariant data = plain(rawData);
    QDir().mkpath(QFileInfo(m_path).absolutePath());
    QSaveFile f(m_path);
    if (!f.open(QIODevice::WriteOnly)) {
        return false;
    }
    f.setPermissions(QFileDevice::ReadOwner | QFileDevice::WriteOwner);
    f.write(QJsonDocument::fromVariant(data).toJson(QJsonDocument::Indented));
    const bool ok = f.commit();
    reload();
    return ok;
}

// ------------------------------------------------------------------------------------ System

KristallSystem::KristallSystem(QObject *parent)
    : QObject(parent)
{
}

QString KristallSystem::env(const QString &name, const QString &fallback) const
{
    const QString v = qEnvironmentVariable(name.toUtf8().constData());
    return v.isEmpty() ? fallback : v;
}

QString KristallSystem::runtimeDir() const
{
    return qEnvironmentVariable("XDG_RUNTIME_DIR", QStringLiteral("/tmp"));
}

QString KristallSystem::homeDir() const
{
    return QDir::homePath();
}

QString KristallSystem::desktopDir() const
{
    const QString d = QStandardPaths::writableLocation(QStandardPaths::DesktopLocation);
    if (!d.isEmpty() && d != QDir::homePath()) {
        QDir().mkpath(d);
        return d;
    }
    return QDir::homePath();
}

bool KristallSystem::copyFile(const QString &from, const QString &to)
{
    QFile::remove(to);
    return QFile::copy(from, to);
}

bool KristallSystem::exists(const QString &path) const
{
    return QFileInfo::exists(path);
}

void KristallSystem::openUrl(const QString &url)
{
    QProcess::startDetached(QStringLiteral("xdg-open"), {url});
}

void KristallSystem::showInFiles(const QString &path)
{
    QDBusMessage msg = QDBusMessage::createMethodCall(QStringLiteral("org.freedesktop.FileManager1"), QStringLiteral("/org/freedesktop/FileManager1"),
                                                      QStringLiteral("org.freedesktop.FileManager1"), QStringLiteral("ShowItems"));
    msg << QStringList{QUrl::fromLocalFile(path).toString()} << QString();
    QDBusConnection::sessionBus().asyncCall(msg);
}

void KristallSystem::launch(const QStringList &argv)
{
    if (!argv.isEmpty()) {
        QProcess::startDetached(argv.first(), argv.mid(1));
    }
}

QString KristallSystem::today() const
{
    return QDate::currentDate().toString(Qt::ISODate);
}

QString KristallSystem::formatBytes(double bytes, const QString &lang) const
{
    // decimal units, like the Mac and like disk labels: 1 TB = 10^12 bytes
    const char *units[] = {"B", "KB", "MB", "GB", "TB"};
    int i = 0;
    while (bytes >= 1000 && i < 4) {
        bytes /= 1000;
        ++i;
    }
    QString n = QString::number(bytes, 'f', bytes < 10 && i > 0 ? 1 : 0);
    if (lang == QLatin1String("de")) {
        n.replace(QLatin1Char('.'), QLatin1Char(','));
    }
    return n + QStringLiteral(" ") + QLatin1String(units[i]);
}

// ------------------------------------------------------------------------------------ test hook

void KristallSystem::registerTestRoot(QObject *root)
{
    const QString dir = qEnvironmentVariable("KRISTALL_SETTINGS_TEST_DIR");
    if (dir.isEmpty()) {
        return;
    }
    m_testRoot = root;
    if (!m_testWatch) {
        QDir().mkpath(dir);
        m_testWatch = new QFileSystemWatcher({dir}, this);
        connect(m_testWatch, &QFileSystemWatcher::directoryChanged, this, &KristallSystem::answerTest);
    }
}

static QObject *findNamed(QObject *o, const QString &name)
{
    if (!o) {
        return nullptr;
    }
    if (o->objectName() == name) {
        auto *it = qobject_cast<QQuickItem *>(o);
        if (!it || it->isVisible()) {
            return o;
        }
    }
    if (auto *it = qobject_cast<QQuickItem *>(o)) {
        const auto kids = it->childItems();
        for (QQuickItem *k : kids) {
            if (QObject *f = findNamed(k, name)) {
                return f;
            }
        }
    }
    const auto kids = o->children();
    for (QObject *k : kids) {
        if (QObject *f = findNamed(k, name)) {
            return f;
        }
    }
    return nullptr;
}

void KristallSystem::answerTest()
{
    const QString dir = qEnvironmentVariable("KRISTALL_SETTINGS_TEST_DIR");
    QFile q(dir + QStringLiteral("/query"));
    if (!q.open(QIODevice::ReadOnly)) {
        return;
    }
    const QString name = QString::fromUtf8(q.readAll()).trimmed();
    q.close();
    QFile::remove(q.fileName());
    QJsonObject a{{QStringLiteral("name"), name}};
    QObject *o = findNamed(m_testRoot, name);
    if (auto *it = qobject_cast<QQuickItem *>(o)) {
        // window coordinates (Wayland reports no global position: mapToGlobal is window-relative)
        const QPointF p = it->mapToGlobal(QPointF(0, 0));
        a.insert(QStringLiteral("x"), p.x());
        a.insert(QStringLiteral("y"), p.y());
        a.insert(QStringLiteral("w"), it->width());
        a.insert(QStringLiteral("h"), it->height());
        for (const char *prop : {"checked", "value", "text", "currentIndex", "enabled"}) {
            const QVariant v = it->property(prop);
            if (v.isValid()) {
                a.insert(QLatin1String(prop), QJsonValue::fromVariant(v));
            }
        }
    }
    QSaveFile f(dir + QStringLiteral("/answer.json"));
    if (f.open(QIODevice::WriteOnly)) {
        f.write(QJsonDocument(a).toJson(QJsonDocument::Compact));
        f.commit();
    }
}
