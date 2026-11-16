/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include "server.h"

#include <QImage>
#include <QObject>
#include <QPointer>
#include <QRectF>
#include <QTimer>

namespace KWin
{
class Window;
}

namespace Kristall
{

class WindowModel;
class LayerScopes;

// Silent screenshots for the assistant: the scene is rendered into an offscreen texture inside
// the compositor (no portal, no flash, no sound), read back, and encoded/written to
// $XDG_RUNTIME_DIR/kristall/shots/ on a worker thread so the compositor never waits for disk or
// PNG encoding.
class Screenshotter : public QObject
{
    Q_OBJECT
public:
    Screenshotter(Server *server, WindowModel *windows, LayerScopes *scopes, const QString &runtimeDir, QObject *parent);
    static bool supported();

private:
    struct Job
    {
        ReplyPtr reply;
        QPointer<KWin::Window> window;
        QString outputName;
        QRectF area;
        qreal scale = 1;
        int maxW = 0;
        int maxH = 0;
        bool includeCursor = false;
        bool excludeShell = false;
        bool isWindow = false;
    };
    void take(Params &p, const ReplyPtr &reply);
    void renderNext();

    Server *m_server;
    WindowModel *m_windows;
    LayerScopes *m_scopes;
    QString m_dir;
    QList<Job> m_queue;
    QTimer m_pacing;
};

} // namespace Kristall
