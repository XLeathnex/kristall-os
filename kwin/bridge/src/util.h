/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include <QJsonArray>
#include <QJsonObject>
#include <QJsonValue>
#include <QLoggingCategory>
#include <QString>

#include <chrono>
#include <optional>
#include <sys/types.h>

Q_DECLARE_LOGGING_CATEGORY(KRISTALL_BRIDGE)

namespace Kristall
{

// Logs to the journal with SYSLOG_IDENTIFIER=kristall-bridge (and to KWin's stderr via the Qt
// category). Rate limited per message key so a misbehaving client cannot flood the journal.
void logInfo(const QString &msg);
void logWarning(const QString &msg);
void logOnce(const QString &key, const QString &msg);

// Error codes from docs/contracts/bridge.md
namespace Err
{
inline const QString Invalid = QStringLiteral("invalid");
inline const QString NotFound = QStringLiteral("not_found");
inline const QString Busy = QStringLiteral("busy");
inline const QString Unsupported = QStringLiteral("unsupported");
inline const QString Denied = QStringLiteral("denied");
inline const QString Internal = QStringLiteral("internal");
}

struct BridgeError
{
    QString code;
    QString message;
};

// Strict parameter readers. Each returns std::nullopt and fills `err` when the value is present
// but malformed, or absent while required. Numbers must be finite and inside [min, max].
class Params
{
public:
    explicit Params(const QJsonObject &obj)
        : m_obj(obj)
    {
    }
    const QJsonObject &raw() const
    {
        return m_obj;
    }
    bool has(const QString &key) const
    {
        return m_obj.contains(key) && !m_obj.value(key).isNull();
    }
    std::optional<QString> string(const QString &key, bool required, int maxLen = 4096, const QString &def = {});
    std::optional<double> number(const QString &key, bool required, double min, double max, double def = 0);
    std::optional<int> integer(const QString &key, bool required, int min, int max, int def = 0);
    std::optional<bool> boolean(const QString &key, bool required, bool def = false);
    std::optional<QJsonObject> object(const QString &key, bool required);
    std::optional<QStringList> stringList(const QString &key, bool required, int maxItems, int maxLen);

    bool failed() const
    {
        return m_failed;
    }
    BridgeError error() const
    {
        return {Err::Invalid, m_error};
    }

private:
    void fail(const QString &msg)
    {
        if (!m_failed) {
            m_failed = true;
            m_error = msg;
        }
    }
    QJsonObject m_obj;
    bool m_failed = false;
    QString m_error;
};

// Coordinates are logical pixels in global compositor space. Anything outside this range is
// certainly a client bug, and rejecting it early keeps float maths sane.
constexpr double kCoordLimit = 1.0e6;

struct PeerInfo
{
    pid_t pid = -1;
    uid_t uid = uid_t(-1);
    QString exe;
    bool trusted = false; // executable is one of our installed binaries
    QString reason; // why trusted/untrusted (for logs and denial messages)
};

// Reads SO_PEERCRED (and SO_PEERPIDFD where available, to rule out pid reuse) and decides whether
// the peer is one of our installed binaries.
PeerInfo identifyPeer(int fd);

// Exposed for unit tests through the "debug.trustCheck" method in development mode.
bool isTrustedPath(const QString &path);
bool isTrustedCommand(const QString &exe, const QList<QByteArray> &argv, QString *reason);

std::chrono::microseconds monotonicNow();

QString randomToken(int bytes = 16);

} // namespace Kristall
