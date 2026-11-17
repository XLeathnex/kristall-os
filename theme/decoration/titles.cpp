// SPDX-License-Identifier: GPL-3.0-or-later
#include "titles.h"

#include <QFile>
#include <QHash>
#include <QJsonArray>
#include <QJsonDocument>
#include <QJsonObject>
#include <QLocale>

namespace Kristall
{
namespace
{
const QString separator = QStringLiteral(" — "); // Qt's own (QPlatformWindow::formatWindowTitle)

QHash<QString, QString> load()
{
    QHash<QString, QString> map;
    QString path = qEnvironmentVariable("KRISTALL_APPS_MANIFEST");
    if (path.isEmpty()) {
        path = QStringLiteral("/usr/share/kristall/apps/apps.json");
    }
    QFile f(path);
    if (!f.open(QIODevice::ReadOnly)) {
        return map;
    }
    QString lang = qEnvironmentVariable("KRISTALL_LANG").left(2);
    if (lang.isEmpty()) {
        lang = QLocale().name().startsWith(QLatin1String("de")) ? QStringLiteral("de") : QStringLiteral("en");
    }
    const auto apps = QJsonDocument::fromJson(f.readAll()).object().value(QLatin1String("apps")).toArray();
    for (const auto &v : apps) {
        const auto a = v.toObject();
        const auto names = a.value(QLatin1String("name")).toObject();
        const QString ours = names.value(lang).toString(names.value(QLatin1String("en")).toString());
        if (ours.isEmpty()) {
            continue;
        }
        for (const auto &p : a.value(QLatin1String("product_names")).toArray()) {
            if (!p.toString().isEmpty()) {
                map.insert(p.toString(), ours);
            }
        }
    }
    return map;
}
}

QString ownerCaption(const QString &caption)
{
    static const QHash<QString, QString> products = load();
    if (products.isEmpty() || caption.isEmpty()) {
        return caption;
    }
    const qsizetype cut = caption.lastIndexOf(separator);
    const QString tail = cut >= 0 ? caption.mid(cut + separator.size()) : caption;
    const auto it = products.constFind(tail);
    if (it == products.constEnd()) {
        return caption;
    }
    return cut >= 0 ? caption.left(cut) + separator + it.value() : it.value();
}
}
