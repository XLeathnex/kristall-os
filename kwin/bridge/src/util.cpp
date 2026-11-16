/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "util.h"

#include <QElapsedTimer>
#include <QFile>
#include <QHash>
#include <QRandomGenerator>
#include <QRegularExpression>

#include <cerrno>
#include <climits>
#include <cmath>
#include <fcntl.h>
#include <sys/socket.h>
#include <sys/syscall.h>
#include <time.h>
#include <unistd.h>

#if KRISTALL_HAVE_SYSTEMD
#include <syslog.h>
#include <systemd/sd-journal.h>
#endif

#ifndef SO_PEERPIDFD
#define SO_PEERPIDFD 77
#endif

Q_LOGGING_CATEGORY(KRISTALL_BRIDGE, "kristall.bridge", QtInfoMsg)

namespace Kristall
{

static void journal(int priority, const QString &msg)
{
#if KRISTALL_HAVE_SYSTEMD
    const QByteArray m = msg.toUtf8();
    sd_journal_send("MESSAGE=%s", m.constData(), "PRIORITY=%i", priority, "SYSLOG_IDENTIFIER=kristall-bridge", nullptr);
#else
    Q_UNUSED(priority)
    Q_UNUSED(msg)
#endif
}

// at most 20 messages per 10 s window; protects the journal (and KWin's stderr) from floods
static bool rateOk()
{
    static QElapsedTimer window;
    static int count = 0;
    if (!window.isValid() || window.elapsed() > 10000) {
        window.restart();
        count = 0;
    }
    return ++count <= 20;
}

void logInfo(const QString &msg)
{
    if (!rateOk()) {
        return;
    }
    qCInfo(KRISTALL_BRIDGE).noquote() << msg;
#if KRISTALL_HAVE_SYSTEMD
    journal(LOG_INFO, msg);
#endif
}

void logWarning(const QString &msg)
{
    if (!rateOk()) {
        return;
    }
    qCWarning(KRISTALL_BRIDGE).noquote() << msg;
#if KRISTALL_HAVE_SYSTEMD
    journal(LOG_WARNING, msg);
#endif
}

void logOnce(const QString &key, const QString &msg)
{
    static QSet<QString> seen;
    if (seen.contains(key) || seen.size() > 256) {
        return;
    }
    seen.insert(key);
    logWarning(msg);
}

// ------------------------------------------------------------------------------------ Params

std::optional<QString> Params::string(const QString &key, bool required, int maxLen, const QString &def)
{
    if (!has(key)) {
        if (required) {
            fail(QStringLiteral("missing parameter '%1'").arg(key));
            return std::nullopt;
        }
        return def;
    }
    const QJsonValue v = m_obj.value(key);
    if (!v.isString()) {
        fail(QStringLiteral("parameter '%1' must be a string").arg(key));
        return std::nullopt;
    }
    const QString s = v.toString();
    if (s.size() > maxLen) {
        fail(QStringLiteral("parameter '%1' is too long (max %2)").arg(key).arg(maxLen));
        return std::nullopt;
    }
    return s;
}

std::optional<double> Params::number(const QString &key, bool required, double min, double max, double def)
{
    if (!has(key)) {
        if (required) {
            fail(QStringLiteral("missing parameter '%1'").arg(key));
            return std::nullopt;
        }
        return def;
    }
    const QJsonValue v = m_obj.value(key);
    if (!v.isDouble()) {
        fail(QStringLiteral("parameter '%1' must be a number").arg(key));
        return std::nullopt;
    }
    const double d = v.toDouble();
    if (!std::isfinite(d) || d < min || d > max) {
        fail(QStringLiteral("parameter '%1' is out of range [%2, %3]").arg(key).arg(min).arg(max));
        return std::nullopt;
    }
    return d;
}

std::optional<int> Params::integer(const QString &key, bool required, int min, int max, int def)
{
    const auto d = number(key, required, min, max, def);
    if (!d) {
        return std::nullopt;
    }
    if (std::floor(*d) != *d) {
        fail(QStringLiteral("parameter '%1' must be an integer").arg(key));
        return std::nullopt;
    }
    return int(*d);
}

std::optional<bool> Params::boolean(const QString &key, bool required, bool def)
{
    if (!has(key)) {
        if (required) {
            fail(QStringLiteral("missing parameter '%1'").arg(key));
            return std::nullopt;
        }
        return def;
    }
    const QJsonValue v = m_obj.value(key);
    if (!v.isBool()) {
        fail(QStringLiteral("parameter '%1' must be a boolean").arg(key));
        return std::nullopt;
    }
    return v.toBool();
}

std::optional<QJsonObject> Params::object(const QString &key, bool required)
{
    if (!has(key)) {
        if (required) {
            fail(QStringLiteral("missing parameter '%1'").arg(key));
            return std::nullopt;
        }
        return QJsonObject();
    }
    const QJsonValue v = m_obj.value(key);
    if (!v.isObject()) {
        fail(QStringLiteral("parameter '%1' must be an object").arg(key));
        return std::nullopt;
    }
    return v.toObject();
}

std::optional<QStringList> Params::stringList(const QString &key, bool required, int maxItems, int maxLen)
{
    if (!has(key)) {
        if (required) {
            fail(QStringLiteral("missing parameter '%1'").arg(key));
            return std::nullopt;
        }
        return QStringList();
    }
    const QJsonValue v = m_obj.value(key);
    if (!v.isArray()) {
        fail(QStringLiteral("parameter '%1' must be an array of strings").arg(key));
        return std::nullopt;
    }
    const QJsonArray a = v.toArray();
    if (a.size() > maxItems) {
        fail(QStringLiteral("parameter '%1' has too many items").arg(key));
        return std::nullopt;
    }
    QStringList out;
    for (const QJsonValue &item : a) {
        if (!item.isString() || item.toString().size() > maxLen) {
            fail(QStringLiteral("parameter '%1' must be an array of short strings").arg(key));
            return std::nullopt;
        }
        out << item.toString();
    }
    return out;
}

// ------------------------------------------------------------------------------------ peers

bool isTrustedPath(const QString &path)
{
    if (!path.startsWith(QLatin1Char('/')) || path.contains(QLatin1String("/../")) || path.contains(QLatin1String("/./"))
        || path.endsWith(QLatin1String("/..")) || path.contains(QLatin1String("//"))) {
        return false;
    }
    if (path.startsWith(QLatin1String("/usr/lib/kristall/")) && path.size() > int(sizeof("/usr/lib/kristall/"))) {
        return true;
    }
    static const QRegularExpression bin(QStringLiteral("^/usr/bin/kristall-[A-Za-z0-9._-]+$"));
    return bin.match(path).hasMatch();
}

// The assistant's tools are Python programs, whose /proc/<pid>/exe is the interpreter. For a
// system Python interpreter we accept the peer when the script it runs (the first non-option
// argument) is one of our installed files. /usr is read-only, so only our files live there.
bool isTrustedCommand(const QString &exe, const QList<QByteArray> &argv, QString *reason)
{
    if (isTrustedPath(exe)) {
        *reason = QStringLiteral("executable %1").arg(exe);
        return true;
    }
    static const QRegularExpression python(QStringLiteral("^/usr/bin/python3(\\.[0-9]+)?$"));
    if (!python.match(exe).hasMatch()) {
        *reason = QStringLiteral("executable %1 is not a Kristall binary").arg(exe);
        return false;
    }
    // options of CPython that take no argument / that take one
    static const QSet<QByteArray> noArg = {"-I", "-s", "-S", "-E", "-B", "-P", "-O", "-OO", "-u", "-b", "-bb", "-q", "-R"};
    static const QSet<QByteArray> withArg = {"-W", "-X"};
    for (int i = 1; i < argv.size(); ++i) {
        const QByteArray &a = argv.at(i);
        if (a.isEmpty()) {
            break;
        }
        if (noArg.contains(a)) {
            continue;
        }
        if (withArg.contains(a)) {
            ++i;
            continue;
        }
        if (a.startsWith("-W") || a.startsWith("-X")) {
            continue;
        }
        if (a.startsWith('-')) { // -c, -m, - and anything unknown: cannot attribute the code
            *reason = QStringLiteral("python peer runs '%1', not an installed Kristall script").arg(QString::fromUtf8(a.left(64)));
            return false;
        }
        const QString script = QString::fromUtf8(a);
        if (isTrustedPath(script)) {
            *reason = QStringLiteral("python script %1").arg(script);
            return true;
        }
        *reason = QStringLiteral("python script %1 is not a Kristall binary").arg(script.left(200));
        return false;
    }
    *reason = QStringLiteral("python peer without a script");
    return false;
}

static QString readExe(pid_t pid)
{
    char buf[PATH_MAX];
    const QByteArray link = "/proc/" + QByteArray::number(pid) + "/exe";
    const ssize_t n = readlink(link.constData(), buf, sizeof(buf) - 1);
    if (n <= 0) {
        return QString();
    }
    buf[n] = 0;
    return QString::fromUtf8(buf, n);
}

static QList<QByteArray> readCmdline(pid_t pid)
{
    // procfs read of a few KiB: does not block on I/O
    const QByteArray path = "/proc/" + QByteArray::number(pid) + "/cmdline";
    const int fd = open(path.constData(), O_RDONLY | O_CLOEXEC);
    if (fd < 0) {
        return {};
    }
    QByteArray data(8192, Qt::Uninitialized);
    const ssize_t n = read(fd, data.data(), data.size());
    close(fd);
    if (n <= 0) {
        return {};
    }
    data.truncate(n);
    QList<QByteArray> argv = data.split('\0');
    if (!argv.isEmpty() && argv.last().isEmpty()) {
        argv.removeLast();
    }
    return argv;
}

PeerInfo identifyPeer(int fd)
{
    PeerInfo info;
    struct ucred cred;
    socklen_t len = sizeof(cred);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERCRED, &cred, &len) != 0) {
        info.reason = QStringLiteral("SO_PEERCRED failed");
        return info;
    }
    info.pid = cred.pid;
    info.uid = cred.uid;

    int pidfd = -1;
    socklen_t pidfdLen = sizeof(pidfd);
    if (getsockopt(fd, SOL_SOCKET, SO_PEERPIDFD, &pidfd, &pidfdLen) != 0) {
        pidfd = -1;
    }

    info.exe = readExe(info.pid);
    const QList<QByteArray> argv = readCmdline(info.pid);
    QString reason;
    bool trusted = !info.exe.isEmpty() && isTrustedCommand(info.exe, argv, &reason);
    if (pidfd >= 0) {
        // the pid we inspected must still be the peer (no exit + pid reuse in between)
        if (syscall(SYS_pidfd_send_signal, pidfd, 0, nullptr, 0) != 0) {
            trusted = false;
            reason = QStringLiteral("peer exited during identification");
        }
        close(pidfd);
    }
    if (info.exe.endsWith(QLatin1String(" (deleted)"))) {
        trusted = false;
        reason = QStringLiteral("peer executable was deleted");
    }
    info.trusted = trusted;
    info.reason = reason;
    return info;
}

std::chrono::microseconds monotonicNow()
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return std::chrono::seconds(ts.tv_sec) + std::chrono::microseconds(ts.tv_nsec / 1000);
}

QString randomToken(int bytes)
{
    QByteArray b(bytes, Qt::Uninitialized);
    QRandomGenerator::system()->fillRange(reinterpret_cast<quint32 *>(b.data()), bytes / 4);
    return QString::fromLatin1(b.toHex());
}

} // namespace Kristall
