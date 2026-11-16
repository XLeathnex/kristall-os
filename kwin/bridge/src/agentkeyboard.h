/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#pragma once

#include "server.h"

#include <QObject>
#include <QPointer>

#include <memory>

namespace KWin
{
class Window;
class SurfaceInterface;
}

namespace Kristall
{

class Agent;
class WindowModel;
class HelperClient;
struct TextJob;

// agent.key and agent.text. Keyboard focus is singular: the target's surface gets the seat's
// keyboard focus for the duration of the call (Wayland clients: keyboard focus only, the window
// is neither raised nor activated; XWayland clients: real activation, because X11 input focus is
// set by the window manager), and the previous state is restored afterwards.
//
// Text paths, chosen per target and per character (reported in the result):
//   textInput        the focused client has text-input-v3 (or v2) enabled: one commit_string
//   keymap           the character exists in the active layout: its key with the level's modifiers
//   temporaryKeymap  native Wayland client, character not in the layout: a one-key keymap is sent
//                    to that client only, the key typed, and the real keymap sent back
//   clipboard        XWayland client, character not in the layout: the clipboard is saved, set
//                    to the text, Ctrl+V (Ctrl+Shift+V in terminals) sent, and the clipboard restored
// Where the text switches between text-input and a key path, the client is synchronised (ping/pong)
// first, because toolkits apply text-input commits and key events from different queues.
class AgentKeyboard : public QObject
{
    Q_OBJECT
public:
    AgentKeyboard(Agent *agent, Server *server, WindowModel *windows, HelperClient *helper);
    ~AgentKeyboard() override;

    void registerMethods();
    void abortAll(const QString &why);
    void ownerKey(quint32 scanCode);

private:
    void key(Params &p, const ReplyPtr &reply);
    void text(Params &p, const ReplyPtr &reply);
    void runJob(const std::shared_ptr<TextJob> &job);
    void step(const std::shared_ptr<TextJob> &job);
    void barrier(const std::shared_ptr<TextJob> &job);
    void finishJob(const std::shared_ptr<TextJob> &job, const QString &errorCode = QString(), const QString &error = QString());

    Agent *m_agent;
    Server *m_server;
    WindowModel *m_windows;
    HelperClient *m_helper;
    std::shared_ptr<TextJob> m_job;
    std::shared_ptr<TextJob> m_focusHolder; // the job (text or key) that holds keyboard focus
};

} // namespace Kristall
