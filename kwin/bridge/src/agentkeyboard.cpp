/*
    Kristall OS — compositor bridge
    SPDX-FileCopyrightText: 2026 Kristall OS contributors
    SPDX-License-Identifier: GPL-3.0-or-later
*/
#include "agentkeyboard.h"
#include "agent.h"
#include "helperclient.h"
#include "windows.h"

#include "input.h"
#include "keyboard_input.h"
#include "main.h"
#include "wayland/clientconnection.h"
#include "wayland/display.h"
#include "wayland/keyboard.h"
#include "wayland/seat.h"
#include "wayland/surface.h"
#include "wayland/textinput_v2.h"
#include "wayland/textinput_v3.h"
#include "wayland/xdgshell.h"
#include "wayland_server.h"
#include "window.h"
#include "workspace.h"
#include "x11window.h"
#include "xkb.h"

#include <wayland-server-core.h>
#include <wayland-server-protocol.h>
#include <xcb/xcb.h>
#include <xcb/xcbext.h> // xcb_poll_for_reply
#include <xkbcommon/xkbcommon.h>

#include <QElapsedTimer>
#include <QJsonArray>
#include <QTimer>

#include <cstring>
#include <functional>
#include <fcntl.h>
#include <linux/input-event-codes.h>
#include <sys/mman.h>
#include <unistd.h>

using namespace KWin;

namespace Kristall
{

extern xkb_mod_mask_t modifierMask(const QStringList &mods); // agent.cpp

constexpr int kMaxTextLength = 20000; // code points per agent.text call
// Typing is paced: a burst of tens of thousands of key events could fill a slow client's
// connection buffer (1 MiB in KWin), and libwayland disconnects a client whose buffer overflows.
// 32 characters every 8 ms is ~4000 characters per second.
constexpr int kKeysPerTurn = 32;
constexpr int kTurnIntervalMs = 8;
constexpr int kTextInputWaitMs = 300; // how long a focused client may take to enable text-input
constexpr int kPasteServeWaitMs = 1500;
constexpr int kPasteGraceMs = 300;
// Toolkits do not apply text-input commits and key events in one queue: Qt and GTK apply a
// text-input commit while they read it from the socket but queue key events and process them
// afterwards, so a commit and a key press that arrive in the same read are applied out of order
// ("Hallo\nWelt" became "HalloWelt\n" in a QTextEdit). Wherever the text switches between the
// text-input path and a key path, the bridge therefore waits until the client has dispatched
// everything sent so far (an xdg_wm_base ping answered with pong), plus a short settle time in
// which the toolkit drains its event queue, before it sends the next segment.
constexpr int kBarrierSettleMs = 8;
constexpr int kBarrierTimeoutMs = 1000; // a client that does not answer the ping in time
constexpr int kBarrierFallbackMs = 50; // surfaces without xdg_surface (layer shell): a plain pause
// XWayland targets: X11 input focus is set by KWin over its X11 connection, keys travel over
// Xwayland's Wayland connection, and nothing orders the two. Keys sent before Xwayland has applied
// the activation's SetInputFocus, or still unread when the focus is handed back, reach whichever
// X window has focus at that moment (the "lost key after typing" defect). The bridge therefore
// uses an X round trip as a barrier (xBarrier): GetInputFocus on KWin's X11 connection, sent after
// the Wayland events were flushed. Xwayland reads every ready socket in one wait and converts input
// before it executes requests, so once the reply is there, every key sent before it has been routed;
// and the reply says whether the target has X focus yet (if not, ask again until kXFocusWaitMs).
constexpr int kXFocusWaitMs = 500;

enum class Path {
    TextInput,
    Keymap,
    TemporaryKeymap,
    Clipboard,
};

static QString pathName(Path p)
{
    switch (p) {
    case Path::TextInput:
        return QStringLiteral("textInput");
    case Path::Keymap:
        return QStringLiteral("keymap");
    case Path::TemporaryKeymap:
        return QStringLiteral("temporaryKeymap");
    case Path::Clipboard:
        return QStringLiteral("clipboard");
    }
    return QString();
}

struct Segment
{
    Path path;
    QList<char32_t> chars;
};

// text-input commits and key events reach applications through different queues (see above)
static bool isKeyPath(Path p)
{
    return p != Path::TextInput;
}

struct TextJob
{
    ReplyPtr reply;
    QPointer<Window> target;
    QPointer<SurfaceInterface> surface;
    QPointer<Window> prevActive;
    QPointer<SurfaceInterface> prevSurface; // what KWin had focused before the agent took focus
    bool restoreFocus = true;
    bool holdsFocus = false;
    bool activated = false; // we activated the target (XWayland, or restoreFocus false)
    bool xwayland = false;
    QList<char32_t> text;
    QList<Segment> segments;
    int segment = 0;
    int offset = 0;
    QStringList paths;
    QJsonArray report;
    bool done = false;
    bool waiting = false;
    // ordering between the text-input path and the key paths
    int lastKind = -1; // -1 nothing delivered yet, 0 text-input, 1 key events
    bool barrierPassed = false; // for the current segment
    // clipboard path
    bool haveSaved = false;
    ClipboardData saved;
    QJsonObject targetJson;
    QString pasteChord;
};

// ------------------------------------------------------------------------------------ xkb helpers

struct KeyStroke
{
    xkb_keycode_t evdev = 0; // keycode - 8
    xkb_mod_mask_t mods = 0;
};

// Finds the key producing `sym` in the active layout: main-keyboard keys first (X11 cannot carry
// keycodes above 255, and e.g. EuroSign also sits on the KEY_EURO multimedia key), then the
// lowest shift level.
static std::optional<KeyStroke> strokeFor(xkb_keysym_t sym)
{
    Xkb *xkb = input()->keyboard()->xkb();
    xkb_keymap *keymap = xkb->keymap();
    if (!keymap || !xkb->state()) {
        return std::nullopt;
    }
    const xkb_layout_index_t layout = xkb_state_serialize_layout(xkb->state(), XKB_STATE_LAYOUT_EFFECTIVE);
    const xkb_keycode_t min = xkb_keymap_min_keycode(keymap);
    const xkb_keycode_t max = xkb_keymap_max_keycode(keymap);
    struct Range
    {
        xkb_keycode_t from, to;
    };
    const Range ranges[] = {{min, std::min<xkb_keycode_t>(max, 255)}, {256, max}};
    for (const Range &range : ranges)
    for (xkb_level_index_t level = 0; level < 8; ++level) {
        for (xkb_keycode_t kc = range.from; kc <= range.to; ++kc) {
            if (level >= xkb_keymap_num_levels_for_key(keymap, kc, layout)) {
                continue;
            }
            const xkb_keysym_t *syms = nullptr;
            const int n = xkb_keymap_key_get_syms_by_level(keymap, kc, layout, level, &syms);
            if (n != 1 || syms[0] != sym) {
                continue;
            }
            xkb_mod_mask_t masks[4];
            const size_t nm = xkb_keymap_key_get_mods_for_level(keymap, kc, layout, level, masks, 4);
            if (level > 0 && nm == 0) {
                continue; // level not reachable through modifiers
            }
            KeyStroke s;
            s.evdev = kc - 8;
            s.mods = nm > 0 ? masks[0] : 0;
            // a mask that includes Lock would toggle caps state; take another one if possible
            for (size_t i = 0; i < nm; ++i) {
                const xkb_mod_index_t lock = xkb_keymap_mod_get_index(keymap, XKB_MOD_NAME_CAPS);
                if (lock == XKB_MOD_INVALID || !(masks[i] & (1u << lock))) {
                    s.mods = masks[i];
                    break;
                }
            }
            return s;
        }
    }
    return std::nullopt;
}

static xkb_keysym_t keysymForChar(char32_t c)
{
    if (c == U'\n') {
        return XKB_KEY_Return;
    }
    if (c == U'\t') {
        return XKB_KEY_Tab;
    }
    if (c == U'\b') {
        return XKB_KEY_BackSpace;
    }
    return xkb_utf32_to_keysym(c);
}

static void restoreRealModifiers()
{
    Xkb *xkb = input()->keyboard()->xkb();
    if (!xkb->state()) {
        return;
    }
    waylandServer()->seat()->notifyKeyboardModifiers(xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_DEPRESSED),
                                                     xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_LATCHED),
                                                     xkb_state_serialize_mods(xkb->state(), XKB_STATE_MODS_LOCKED),
                                                     xkb->currentLayout());
}

static void tap(const KeyStroke &s)
{
    SeatInterface *seat = waylandServer()->seat();
    KWin::Display *display = waylandServer()->display();
    seat->setTimestamp(monotonicNow());
    seat->notifyKeyboardModifiers(s.mods, 0, 0, input()->keyboard()->xkb()->currentLayout());
    seat->notifyKeyboardKey(s.evdev, KeyboardKeyState::Pressed, display->nextSerial());
    seat->notifyKeyboardKey(s.evdev, KeyboardKeyState::Released, display->nextSerial());
}

// Sends a keymap to every wl_keyboard of one client (only that client sees it).
static int sendKeymapToClient(ClientConnection *client, const QByteArray &keymap)
{
    if (!client || keymap.isEmpty()) {
        return 0;
    }
    const int fd = memfd_create("kristall-bridge-keymap", MFD_CLOEXEC | MFD_ALLOW_SEALING);
    if (fd < 0) {
        return 0;
    }
    const QByteArray data = keymap + QByteArray(1, '\0');
    if (write(fd, data.constData(), data.size()) != data.size()) {
        close(fd);
        return 0;
    }
    fcntl(fd, F_ADD_SEALS, F_SEAL_SHRINK | F_SEAL_GROW | F_SEAL_WRITE | F_SEAL_SEAL);
    struct Ctx
    {
        int fd;
        uint32_t size;
        int sent;
    } ctx{fd, uint32_t(data.size()), 0};
    wl_client_for_each_resource(
        client->client(),
        [](wl_resource *res, void *user) -> wl_iterator_result {
            auto *c = static_cast<Ctx *>(user);
            if (std::strcmp(wl_resource_get_class(res), "wl_keyboard") == 0) {
                wl_keyboard_send_keymap(res, WL_KEYBOARD_KEYMAP_FORMAT_XKB_V1, c->fd, c->size);
                c->sent++;
            }
            return WL_ITERATOR_CONTINUE;
        },
        &ctx);
    close(fd); // libwayland duplicated it for each event
    return ctx.sent;
}

static bool textInputActiveFor(SurfaceInterface *surface)
{
    SeatInterface *seat = waylandServer()->seat();
    if (!surface || seat->focusedTextInputSurface() != surface) {
        return false;
    }
    if (auto *t3 = seat->textInputV3(); t3 && t3->isEnabled() && t3->surface() == surface) {
        return true;
    }
    if (auto *t2 = seat->textInputV2(); t2 && t2->isEnabled() && t2->surface() == surface) {
        return true;
    }
    return false;
}

static bool clientSupportsTextInput(SurfaceInterface *surface)
{
    SeatInterface *seat = waylandServer()->seat();
    if (!surface) {
        return false;
    }
    return (seat->textInputV3() && seat->textInputV3()->clientSupportsTextInput(surface->client()))
        || (seat->textInputV2() && seat->textInputV2()->clientSupportsTextInput(surface->client()));
}

static void commitText(const QString &text)
{
    SeatInterface *seat = waylandServer()->seat();
    if (auto *t3 = seat->textInputV3(); t3 && t3->isEnabled()) {
        t3->sendPreEditString(QString(), 0, 0);
        t3->commitString(text);
        t3->done();
    } else if (auto *t2 = seat->textInputV2(); t2 && t2->isEnabled()) {
        t2->commitString(text);
        t2->setPreEditCursor(0);
        t2->preEdit({}, {});
    }
}

// The xdg_surface of a client surface (xdg toplevels and popups), for xdg_wm_base.ping.
static XdgSurfaceInterface *xdgSurfaceFor(SurfaceInterface *surface)
{
    if (!surface || !surface->client()) {
        return nullptr;
    }
    struct Ctx
    {
        SurfaceInterface *surface;
        XdgSurfaceInterface *found;
    } ctx{surface, nullptr};
    wl_client_for_each_resource(
        surface->client()->client(),
        [](wl_resource *res, void *user) -> wl_iterator_result {
            auto *c = static_cast<Ctx *>(user);
            if (std::strcmp(wl_resource_get_class(res), "xdg_surface") == 0) {
                if (XdgSurfaceInterface *x = XdgSurfaceInterface::get(res); x && x->surface() == c->surface) {
                    c->found = x;
                    return WL_ITERATOR_STOP;
                }
            }
            return WL_ITERATOR_CONTINUE;
        },
        &ctx);
    return ctx.found;
}

static bool isTerminal(const Window *w)
{
    static const QSet<QString> terminals = {
        QStringLiteral("org.kde.konsole"), QStringLiteral("konsole"), QStringLiteral("foot"), QStringLiteral("footclient"),
        QStringLiteral("org.gnome.Console"), QStringLiteral("org.gnome.Terminal"), QStringLiteral("gnome-terminal-server"),
        QStringLiteral("kitty"), QStringLiteral("Alacritty"), QStringLiteral("alacritty"), QStringLiteral("org.wezfurlong.wezterm"),
        QStringLiteral("com.mitchellh.ghostty"), QStringLiteral("app.devsuite.Ptyxis"), QStringLiteral("org.gnome.Ptyxis"),
        QStringLiteral("xterm"), QStringLiteral("XTerm"), QStringLiteral("org.kde.yakuake"), QStringLiteral("tilix"), QStringLiteral("com.gexperts.Tilix")};
    QString id = w->desktopFileName();
    if (id.endsWith(QLatin1String(".desktop"))) {
        id.chop(8);
    }
    return terminals.contains(id) || terminals.contains(w->resourceClass()) || terminals.contains(w->resourceName());
}

// ------------------------------------------------------------------------------------ focus

static bool isXwaylandWindow(const Window *w)
{
    const SurfaceInterface *s = w->surface();
    return s && waylandServer()->xWaylandConnection() && s->client() == waylandServer()->xWaylandConnection();
}

// Gives the target keyboard focus. Returns false if it cannot take focus.
static bool acquireFocus(TextJob &job)
{
    Window *w = job.target.data();
    SeatInterface *seat = waylandServer()->seat();
    if (!w || !w->surface()) {
        return false;
    }
    job.surface = w->surface();
    job.prevActive = workspace()->activeWindow();
    job.prevSurface = seat->focusedKeyboardSurface();
    job.xwayland = isXwaylandWindow(w);
    job.holdsFocus = true;
    if (seat->focusedKeyboardSurface() == w->surface()) {
        return true;
    }
    if (job.xwayland || !job.restoreFocus) {
        // X11 input focus is set by the window manager on activation
        workspace()->activateWindow(w, true);
        job.activated = true;
        if (seat->focusedKeyboardSurface() != w->surface()) {
            seat->setFocusedKeyboardSurface(w->surface(), {});
        }
    } else {
        seat->setFocusedKeyboardSurface(w->surface(), {});
    }
    return seat->focusedKeyboardSurface() == w->surface();
}

static void releaseFocus(TextJob &job)
{
    if (!job.holdsFocus) {
        return;
    }
    job.holdsFocus = false;
    if (!job.restoreFocus) {
        if (job.target && !job.activated && job.target->wantsInput()) {
            workspace()->activateWindow(job.target, true);
        }
        return;
    }
    if (job.activated && job.prevActive && job.prevActive != job.target && !job.prevActive->isDeleted()) {
        workspace()->activateWindow(job.prevActive, true);
    }
    // back to whatever KWin's own focus logic says (active window, open popups, lock screen)
    input()->keyboard()->update();
}

// One X round trip after flushing the Wayland events (see kXFocusWaitMs). `then(focus)` gets the X
// input focus window, or XCB_WINDOW_NONE on timeout or without an X11 connection. The reply is
// collected on a 1 ms timer that exists only while the round trip lasts.
static void xBarrier(QObject *owner, std::function<void(xcb_window_t)> then, int timeoutMs = kXFocusWaitMs)
{
    xcb_connection_t *c = kwinApp()->x11Connection();
    if (!c) {
        then(XCB_WINDOW_NONE);
        return;
    }
    waylandServer()->display()->flush();
    const xcb_get_input_focus_cookie_t cookie = xcb_get_input_focus(c);
    xcb_flush(c);
    auto *timer = new QTimer(owner);
    auto elapsed = std::make_shared<QElapsedTimer>();
    elapsed->start();
    QObject::connect(timer, &QTimer::timeout, timer, [timer, c, cookie, elapsed, timeoutMs, then]() {
        void *reply = nullptr;
        xcb_generic_error_t *error = nullptr;
        if (xcb_poll_for_reply(c, cookie.sequence, &reply, &error)) {
            const xcb_window_t focus = reply ? static_cast<xcb_get_input_focus_reply_t *>(reply)->focus : XCB_WINDOW_NONE;
            free(reply);
            free(error);
            timer->deleteLater();
            then(focus);
            return;
        }
        if (elapsed->elapsed() > timeoutMs) {
            xcb_discard_reply(c, cookie.sequence);
            timer->deleteLater();
            then(XCB_WINDOW_NONE);
        }
    });
    timer->start(1);
}

// Runs `then` once an XWayland target the bridge just activated really has X input focus
// (an X round trip says so), or after kXFocusWaitMs. Immediately for everything else.
static void whenXFocused(QObject *owner, const TextJob &job, std::function<void()> then)
{
    auto *x11 = qobject_cast<X11Window *>(job.target.data());
    if (!job.xwayland || !job.activated || !x11) {
        then();
        return;
    }
    const xcb_window_t want = x11->window();
    auto deadline = std::make_shared<QElapsedTimer>();
    deadline->start();
    auto ask = std::make_shared<std::function<void()>>();
    *ask = [owner, want, deadline, ask, then]() {
        xBarrier(owner, [owner, want, deadline, ask, then](xcb_window_t focus) {
            if (focus == want || deadline->elapsed() > kXFocusWaitMs) {
                *ask = nullptr; // break the cycle
                then();
            } else {
                QTimer::singleShot(2, owner, [ask]() {
                    if (*ask) {
                        (*ask)();
                    }
                });
            }
        });
    };
    (*ask)();
}

// Runs `then` when Xwayland has routed every key sent so far (XWayland targets), right away otherwise.
static void whenXDelivered(QObject *owner, const TextJob &job, std::function<void()> then)
{
    if (!job.xwayland) {
        then();
        return;
    }
    xBarrier(owner, [then](xcb_window_t) {
        then();
    });
}

// ------------------------------------------------------------------------------------ AgentKeyboard

AgentKeyboard::AgentKeyboard(Agent *agent, Server *server, WindowModel *windows, HelperClient *helper)
    : QObject(agent)
    , m_agent(agent)
    , m_server(server)
    , m_windows(windows)
    , m_helper(helper)
{
}

AgentKeyboard::~AgentKeyboard()
{
    abortAll(QStringLiteral("bridge unloading"));
}

void AgentKeyboard::registerMethods()
{
    m_server->registerMethod(QStringLiteral("agent.key"), MethodSpec{true, QStringLiteral("agentInput"), [this](Params &p, const ReplyPtr &r) {
                                                              key(p, r);
                                                          }});
    m_server->registerMethod(QStringLiteral("agent.text"), MethodSpec{true, QStringLiteral("agentText"), [this](Params &p, const ReplyPtr &r) {
                                                               text(p, r);
                                                           }});
}

// The owner pressed a key while the agent holds keyboard focus. KWin has already counted the key
// as pressed; if it simply re-picked the focus now, the key would only appear in the enter
// event's key array and toolkits would not type it. So focus goes back here, before KWin
// forwards the key, with that key left out, and the agent's text entry stops (owner priority).
void AgentKeyboard::ownerKey(quint32 scanCode)
{
    auto job = m_focusHolder;
    if (!job || !job->holdsFocus) {
        return;
    }
    SeatInterface *seat = waylandServer()->seat();
    QList<quint32> keys = input()->keyboard()->unfilteredKeys();
    keys.removeAll(scanCode);
    if (job->activated && job->restoreFocus && job->prevActive && job->prevActive != job->target && !job->prevActive->isDeleted()) {
        workspace()->activateWindow(job->prevActive, true);
        job->activated = false;
    }
    SurfaceInterface *back = job->prevSurface.data();
    if (Window *active = workspace()->activeWindow(); active && active->surface() && (!back || job->activated)) {
        back = active->surface();
    }
    if (back && back != job->surface) {
        seat->setFocusedKeyboardSurface(nullptr);
        seat->setFocusedKeyboardSurface(back, keys);
    }
    job->holdsFocus = false;
    if (job->reply && !job->reply->done() && !job->done) {
        finishJob(job, Err::Busy, QStringLiteral("the owner started typing"));
    }
    m_focusHolder.reset();
}

void AgentKeyboard::abortAll(const QString &why)
{
    if (m_job && !m_job->done) {
        finishJob(m_job, Err::Busy, QStringLiteral("aborted: %1").arg(why));
    }
}

static Window *resolveTarget(WindowModel *windows, const QString &id, const ReplyPtr &reply)
{
    Window *w = nullptr;
    if (id.isEmpty()) {
        w = workspace()->activeWindow();
        if (!w) {
            reply->fail(Err::NotFound, QStringLiteral("no active window; pass windowId"));
            return nullptr;
        }
    } else {
        w = windows->find(id);
        if (!w) {
            reply->fail(Err::NotFound, QStringLiteral("no window with id '%1'").arg(id));
            return nullptr;
        }
    }
    if (!w->surface() || w->isInternal()) {
        reply->fail(Err::Unsupported, QStringLiteral("this window cannot receive agent keyboard input"));
        return nullptr;
    }
    return w;
}

// "ctrl+shift+t", "return", "ctrl+plus", "ctrl++"
static bool parseChord(const QString &chord, QStringList *mods, xkb_keysym_t *sym, QString *error)
{
    QString s = chord.trimmed().toLower();
    if (s.isEmpty()) {
        *error = QStringLiteral("empty key chord");
        return false;
    }
    QStringList parts;
    if (s.endsWith(QLatin1String("++"))) {
        parts = s.left(s.size() - 2).split(QLatin1Char('+'), Qt::SkipEmptyParts);
        parts << QStringLiteral("plus");
    } else if (s == QLatin1String("+")) {
        parts << QStringLiteral("plus");
    } else {
        parts = s.split(QLatin1Char('+'));
    }
    static const QHash<QString, QString> modAlias = {
        {QStringLiteral("ctrl"), QStringLiteral("ctrl")},   {QStringLiteral("control"), QStringLiteral("ctrl")}, {QStringLiteral("shift"), QStringLiteral("shift")},
        {QStringLiteral("alt"), QStringLiteral("alt")},     {QStringLiteral("option"), QStringLiteral("alt")},   {QStringLiteral("meta"), QStringLiteral("meta")},
        {QStringLiteral("super"), QStringLiteral("meta")},  {QStringLiteral("cmd"), QStringLiteral("meta")},     {QStringLiteral("win"), QStringLiteral("meta")},
    };
    static const QHash<QString, xkb_keysym_t> keyAlias = {
        {QStringLiteral("enter"), XKB_KEY_Return},     {QStringLiteral("esc"), XKB_KEY_Escape},     {QStringLiteral("del"), XKB_KEY_Delete},
        {QStringLiteral("pageup"), XKB_KEY_Prior},     {QStringLiteral("pgup"), XKB_KEY_Prior},     {QStringLiteral("pagedown"), XKB_KEY_Next},
        {QStringLiteral("pgdn"), XKB_KEY_Next},        {QStringLiteral("ins"), XKB_KEY_Insert},     {QStringLiteral("space"), XKB_KEY_space},
        {QStringLiteral("backspace"), XKB_KEY_BackSpace}, {QStringLiteral("capslock"), XKB_KEY_Caps_Lock}, {QStringLiteral("printscreen"), XKB_KEY_Print},
    };
    static const QHash<QString, xkb_keysym_t> modKeys = {
        {QStringLiteral("ctrl"), XKB_KEY_Control_L}, {QStringLiteral("shift"), XKB_KEY_Shift_L}, {QStringLiteral("alt"), XKB_KEY_Alt_L}, {QStringLiteral("meta"), XKB_KEY_Super_L}};
    if (parts.size() > 6) {
        *error = QStringLiteral("too many keys in chord");
        return false;
    }
    for (int i = 0; i < parts.size(); ++i) {
        const QString part = parts.at(i).trimmed();
        if (part.isEmpty()) {
            *error = QStringLiteral("malformed chord '%1'").arg(chord.left(64));
            return false;
        }
        const bool last = i == parts.size() - 1;
        if (!last) {
            if (!modAlias.contains(part)) {
                *error = QStringLiteral("'%1' is not a modifier (ctrl, shift, alt, meta)").arg(part.left(32));
                return false;
            }
            mods->append(modAlias.value(part));
            continue;
        }
        if (modAlias.contains(part) && parts.size() == 1) {
            *sym = modKeys.value(modAlias.value(part));
            return true;
        }
        if (keyAlias.contains(part)) {
            *sym = keyAlias.value(part);
            return true;
        }
        const QList<uint> ucs = part.toUcs4();
        if (ucs.size() == 1) {
            *sym = xkb_utf32_to_keysym(ucs.first());
        } else {
            *sym = xkb_keysym_from_name(part.toUtf8().constData(), XKB_KEYSYM_CASE_INSENSITIVE);
        }
        if (*sym == XKB_KEY_NoSymbol) {
            *error = QStringLiteral("unknown key '%1'").arg(part.left(32));
            return false;
        }
        return true;
    }
    *error = QStringLiteral("malformed chord");
    return false;
}

void AgentKeyboard::key(Params &p, const ReplyPtr &reply)
{
    if (!m_agent->checkSession(p, reply)) {
        return;
    }
    const auto keys = p.string(QStringLiteral("keys"), true, 128);
    const auto windowId = p.string(QStringLiteral("windowId"), false, 64);
    const auto restore = p.boolean(QStringLiteral("restoreFocus"), false, true);
    if (!keys || !windowId || !restore) {
        return;
    }
    QStringList mods;
    xkb_keysym_t sym = XKB_KEY_NoSymbol;
    QString error;
    if (!parseChord(*keys, &mods, &sym, &error)) {
        reply->fail(Err::Invalid, error);
        return;
    }
    if (m_job && !m_job->done && !m_job->reply->done()) {
        reply->fail(Err::Busy, QStringLiteral("text entry is in progress"));
        return;
    }
    const QString wid = *windowId;
    const bool restoreFocus = *restore;
    m_agent->whenOwnerIdle(true, reply, [this, reply, wid, restoreFocus, mods, sym]() {
        if (!reply->alive() || !m_agent->sessionActive() || waylandServer()->isScreenLocked()) {
            reply->fail(Err::Denied, QStringLiteral("the agent session ended or the screen is locked"));
            return;
        }
        if (m_job && !m_job->done && !m_job->reply->done()) {
            reply->fail(Err::Busy, QStringLiteral("text entry is in progress"));
            return;
        }
        Window *w = resolveTarget(m_windows, wid, reply);
        if (!w) {
            return;
        }
        // the key itself: prefer its unshifted position, and add what its level needs
        xkb_keysym_t base = sym;
        std::optional<KeyStroke> stroke = strokeFor(base);
        if (!stroke) {
            base = xkb_keysym_to_lower(sym);
            stroke = strokeFor(base);
        }
        if (!stroke) {
            reply->fail(Err::Unsupported, QStringLiteral("the key is not on the active keyboard layout"));
            return;
        }
        TextJob job;
        job.target = w;
        job.restoreFocus = restoreFocus;
        m_agent->m_inCall++;
        if (!acquireFocus(job)) {
            m_agent->m_inCall--;
            releaseFocus(job);
            reply->fail(Err::Busy, QStringLiteral("the window did not accept keyboard focus"));
            return;
        }
        auto jobp = std::make_shared<TextJob>(job);
        m_focusHolder = jobp;
        const KeyStroke key = *stroke;
        whenXFocused(this, *jobp, [this, jobp, reply, mods, key]() {
            sendKey(jobp, reply, mods, key);
        });
    });
}

void AgentKeyboard::sendKey(const std::shared_ptr<TextJob> &jobp, const ReplyPtr &reply, const QStringList &mods, const KeyStroke &keyStroke)
{
    const KeyStroke *stroke = &keyStroke;
    Window *w = jobp->target.data();
    SeatInterface *seat = waylandServer()->seat();
    if (m_focusHolder != jobp || !jobp->holdsFocus || !w || !reply->alive() || !m_agent->sessionActive() || waylandServer()->isScreenLocked()
        || seat->focusedKeyboardSurface() != jobp->surface) {
        // the owner typed meanwhile (ownerKey already answered), the window went away, or the session ended
        if (m_focusHolder == jobp) {
            releaseFocus(*jobp);
            m_focusHolder.reset();
        }
        m_agent->m_inCall = std::max(0, m_agent->m_inCall - 1);
        if (!reply->done()) {
            reply->fail(w ? Err::Busy : Err::NotFound, w ? QStringLiteral("keyboard focus moved away before the key was sent") : QStringLiteral("the window went away"));
        }
        return;
    }
    {
        KWin::Display *display = waylandServer()->display();
        const xkb_mod_mask_t mask = modifierMask(mods) | stroke->mods;
        // press the modifier keys too: some clients look at key events, not only the modifier state
        static const QHash<QString, quint32> modCodes = {
            {QStringLiteral("ctrl"), KEY_LEFTCTRL}, {QStringLiteral("shift"), KEY_LEFTSHIFT}, {QStringLiteral("alt"), KEY_LEFTALT}, {QStringLiteral("meta"), KEY_LEFTMETA}};
        const quint32 layout = input()->keyboard()->xkb()->currentLayout();
        seat->setTimestamp(monotonicNow());
        xkb_mod_mask_t held = 0;
        for (const QString &m : mods) {
            seat->notifyKeyboardKey(modCodes.value(m), KeyboardKeyState::Pressed, display->nextSerial());
            held |= modifierMask({m});
            seat->notifyKeyboardModifiers(held, 0, 0, layout);
        }
        seat->notifyKeyboardModifiers(mask, 0, 0, layout);
        seat->notifyKeyboardKey(stroke->evdev, KeyboardKeyState::Pressed, display->nextSerial());
        seat->notifyKeyboardKey(stroke->evdev, KeyboardKeyState::Released, display->nextSerial());
        seat->notifyKeyboardModifiers(held, 0, 0, layout);
        for (auto it = mods.crbegin(); it != mods.crend(); ++it) {
            seat->notifyKeyboardKey(modCodes.value(*it), KeyboardKeyState::Released, display->nextSerial());
        }
        restoreRealModifiers();
        const QJsonObject target{{QStringLiteral("windowId"), m_windows->tracked(w) ? QJsonValue(WindowModel::idOf(w)) : QJsonValue()},
                                 {QStringLiteral("appId"), m_windows->tracked(w) ? m_windows->serialize(w).value(QStringLiteral("appId")) : QJsonValue()}};
        // let the client process the key while it still has focus, then restore
        whenXDelivered(this, *jobp, [this, jobp, reply, target]() {
            if (m_focusHolder == jobp) {
                releaseFocus(*jobp);
                m_focusHolder.reset();
            }
            m_agent->m_inCall = std::max(0, m_agent->m_inCall - 1);
            if (!reply->done()) {
                reply->ok(QJsonObject{{QStringLiteral("target"), target}});
            }
        });
    }
}

void AgentKeyboard::text(Params &p, const ReplyPtr &reply)
{
    if (!m_agent->checkSession(p, reply)) {
        return;
    }
    const auto text = p.string(QStringLiteral("text"), true, kMaxTextLength * 2);
    const auto windowId = p.string(QStringLiteral("windowId"), false, 64);
    const auto restore = p.boolean(QStringLiteral("restoreFocus"), false, true);
    const auto allowed = p.stringList(QStringLiteral("paths"), false, 4, 32); // addition: restrict the paths (tests, special targets)
    if (!text || !windowId || !restore || !allowed) {
        return;
    }
    const QList<uint> ucs = text->toUcs4();
    if (ucs.size() > kMaxTextLength) {
        reply->fail(Err::Invalid, QStringLiteral("text longer than %1 characters").arg(kMaxTextLength));
        return;
    }
    if (m_job && !m_job->done && !m_job->reply->done()) {
        reply->fail(Err::Busy, QStringLiteral("text entry is in progress"));
        return;
    }
    auto job = std::make_shared<TextJob>();
    job->reply = reply;
    job->restoreFocus = *restore;
    for (uint c : ucs) {
        if (c == '\r') {
            continue;
        }
        job->text.append(char32_t(c));
    }
    const QStringList allowedPaths = *allowed;
    for (const QString &a : allowedPaths) {
        static const QSet<QString> known = {QStringLiteral("textInput"), QStringLiteral("keymap"), QStringLiteral("temporaryKeymap"), QStringLiteral("clipboard")};
        if (!known.contains(a)) {
            reply->fail(Err::Invalid, QStringLiteral("unknown text path '%1'").arg(a));
            return;
        }
    }
    job->paths = allowedPaths; // reused below as the allow-list, replaced by the used paths later
    const QString wid = *windowId;
    m_job = job;
    m_agent->whenOwnerIdle(true, reply, [this, job, wid]() {
        if (job->done) {
            return;
        }
        if (!job->reply->alive() || !m_agent->sessionActive() || waylandServer()->isScreenLocked()) {
            finishJob(job, Err::Denied, QStringLiteral("the agent session ended or the screen is locked"));
            return;
        }
        Window *w = resolveTarget(m_windows, wid, job->reply);
        if (!w) {
            job->done = true;
            return;
        }
        job->target = w;
        job->targetJson = QJsonObject{{QStringLiteral("windowId"), m_windows->tracked(w) ? QJsonValue(WindowModel::idOf(w)) : QJsonValue()},
                                      {QStringLiteral("appId"), m_windows->tracked(w) ? m_windows->serialize(w).value(QStringLiteral("appId")) : QJsonValue()}};
        job->pasteChord = isTerminal(w) ? QStringLiteral("ctrl+shift+v") : QStringLiteral("ctrl+v");
        m_agent->m_inCall++;
        const bool hadFocus = waylandServer()->seat()->focusedKeyboardSurface() == w->surface();
        m_focusHolder = job;
        if (!acquireFocus(*job)) {
            finishJob(job, Err::Busy, QStringLiteral("the window did not accept keyboard focus"));
            return;
        }
        job->waiting = true;
        whenXFocused(this, *job, [this, job, hadFocus]() {
            job->waiting = false;
            if (!job->done) {
                startJob(job, hadFocus);
            }
        });
    });
}

void AgentKeyboard::startJob(const std::shared_ptr<TextJob> &job, bool hadFocus)
{
    {
        const QStringList allow = job->paths;
        const bool textInputAllowed = allow.isEmpty() || allow.contains(QStringLiteral("textInput"));
        if (textInputAllowed && !hadFocus && !textInputActiveFor(job->surface) && clientSupportsTextInput(job->surface)) {
            // the client answers keyboard/text-input enter with "enable" once its focused widget is
            // a text field; give it a moment
            job->waiting = true;
            auto *t3 = waylandServer()->seat()->textInputV3();
            auto *t2 = waylandServer()->seat()->textInputV2();
            auto ctx = new QObject(this);
            auto go = [this, job, ctx]() {
                if (!job->waiting) {
                    return;
                }
                job->waiting = false;
                ctx->deleteLater();
                runJob(job);
            };
            connect(t3, &TextInputV3Interface::enabledChanged, ctx, [job, go]() {
                if (textInputActiveFor(job->surface)) {
                    go();
                }
            });
            connect(t2, &TextInputV2Interface::enabledChanged, ctx, [job, go]() {
                if (textInputActiveFor(job->surface)) {
                    go();
                }
            });
            QTimer::singleShot(kTextInputWaitMs, ctx, go);
            return;
        }
        runJob(job);
    }
}

void AgentKeyboard::runJob(const std::shared_ptr<TextJob> &job)
{
    if (job->done) {
        return;
    }
    const QStringList allow = job->paths;
    auto allowed = [&](Path p) {
        return allow.isEmpty() || allow.contains(pathName(p));
    };
    job->paths.clear();
    // plan
    const bool textInput = allowed(Path::TextInput) && textInputActiveFor(job->surface);
    auto add = [&](Path p, char32_t c) {
        if (job->segments.isEmpty() || job->segments.last().path != p) {
            job->segments.append(Segment{p, {}});
        }
        job->segments.last().chars.append(c);
    };
    for (char32_t c : std::as_const(job->text)) {
        const bool control = c == U'\n' || c == U'\t' || c == U'\b';
        if (textInput && !control) {
            add(Path::TextInput, c);
            continue;
        }
        const xkb_keysym_t sym = keysymForChar(c);
        if (sym != XKB_KEY_NoSymbol && allowed(Path::Keymap) && strokeFor(sym)) {
            add(Path::Keymap, c);
        } else if (sym != XKB_KEY_NoSymbol && allowed(Path::TemporaryKeymap) && (!job->xwayland || !allowed(Path::Clipboard) || !m_helper->clipboardReady())) {
            add(Path::TemporaryKeymap, c);
        } else if (allowed(Path::Clipboard) && m_helper && m_helper->clipboardReady()) {
            add(Path::Clipboard, c);
        } else {
            finishJob(job, Err::Unsupported, QStringLiteral("character U+%1 cannot be typed with the allowed paths").arg(uint(c), 4, 16, QLatin1Char('0')));
            return;
        }
    }
    step(job);
}

void AgentKeyboard::step(const std::shared_ptr<TextJob> &job)
{
    if (job->done) {
        return;
    }
    if (!m_agent->sessionActive()) {
        finishJob(job, Err::Busy, QStringLiteral("the agent session ended"));
        return;
    }
    if (waylandServer()->isScreenLocked()) {
        finishJob(job, Err::Denied, QStringLiteral("the screen is locked"));
        return;
    }
    if (!job->target || !job->surface) {
        finishJob(job, Err::NotFound, QStringLiteral("the window went away"));
        return;
    }
    if (waylandServer()->seat()->focusedKeyboardSurface() != job->surface) {
        finishJob(job, Err::Busy, QStringLiteral("keyboard focus moved away (the owner typed or clicked elsewhere)"));
        return;
    }
    if (job->segment >= job->segments.size()) {
        finishJob(job);
        return;
    }
    Segment &seg = job->segments[job->segment];
    const int kind = isKeyPath(seg.path) ? 1 : 0;
    if (job->offset == 0 && job->lastKind >= 0 && job->lastKind != kind && !job->barrierPassed) {
        barrier(job);
        return;
    }
    const QString name = pathName(seg.path);
    if (!job->paths.contains(name)) {
        job->paths << name;
    }
    auto nextSegment = [this, job, name, &seg]() {
        job->report.append(QJsonObject{{QStringLiteral("path"), name}, {QStringLiteral("length"), int(seg.chars.size())}});
        job->lastKind = isKeyPath(seg.path) ? 1 : 0;
        job->barrierPassed = false;
        job->segment++;
        job->offset = 0;
        QTimer::singleShot(0, this, [this, job]() {
            step(job);
        });
    };

    switch (seg.path) {
    case Path::TextInput: {
        if (!textInputActiveFor(job->surface)) {
            // the field lost its text-input state; type the rest through the keymap
            seg.path = Path::Keymap;
            step(job);
            return;
        }
        commitText(QString::fromUcs4(seg.chars.constData(), seg.chars.size()));
        nextSegment();
        return;
    }
    case Path::Keymap: {
        const int end = std::min<int>(seg.chars.size(), job->offset + kKeysPerTurn);
        for (; job->offset < end; ++job->offset) {
            const auto stroke = strokeFor(keysymForChar(seg.chars.at(job->offset)));
            if (stroke) {
                tap(*stroke);
            }
        }
        restoreRealModifiers();
        if (job->offset >= seg.chars.size()) {
            nextSegment();
        } else {
            QTimer::singleShot(kTurnIntervalMs, this, [this, job]() {
                step(job);
            });
        }
        return;
    }
    case Path::TemporaryKeymap: {
        Xkb *xkb = input()->keyboard()->xkb();
        ClientConnection *client = job->surface->client();
        const QByteArray original = xkb->keymapContents();
        const int end = std::min<int>(seg.chars.size(), job->offset + 16);
        for (; job->offset < end; ++job->offset) {
            const xkb_keysym_t sym = keysymForChar(seg.chars.at(job->offset));
            const QByteArray temp = xkb->keymapContentsForKeysym(Xkb::scratchKeycode, sym);
            if (temp.isEmpty() || sendKeymapToClient(client, temp) == 0) {
                sendKeymapToClient(client, original);
                finishJob(job, Err::Unsupported, QStringLiteral("could not build a keymap for U+%1").arg(uint(seg.chars.at(job->offset)), 4, 16, QLatin1Char('0')));
                return;
            }
            tap(KeyStroke{Xkb::scratchKeycode, 0});
        }
        sendKeymapToClient(client, original);
        restoreRealModifiers();
        if (job->offset >= seg.chars.size()) {
            nextSegment();
        } else {
            QTimer::singleShot(kTurnIntervalMs, this, [this, job]() {
                step(job);
            });
        }
        return;
    }
    case Path::Clipboard: {
        if (!m_helper || !m_helper->clipboardReady()) {
            finishJob(job, Err::Unsupported, QStringLiteral("the clipboard is not available"));
            return;
        }
        job->waiting = true;
        const QString text = QString::fromUcs4(seg.chars.constData(), seg.chars.size());
        auto paste = [this, job, text, nextSegment]() {
            if (job->done) {
                return;
            }
            const QByteArray utf8 = text.toUtf8();
            const ClipboardData ours = {{QStringLiteral("text/plain;charset=utf-8"), utf8},
                                        {QStringLiteral("text/plain"), utf8},
                                        {QStringLiteral("UTF8_STRING"), utf8},
                                        {QStringLiteral("STRING"), utf8},
                                        {QStringLiteral("TEXT"), utf8}};
            auto served = std::make_shared<bool>(false);
            auto restoreAndContinue = std::make_shared<std::function<void()>>();
            *restoreAndContinue = [this, job, nextSegment]() {
                if (job->done) {
                    return;
                }
                if (!job->saved.isEmpty()) {
                    m_helper->setClipboard(job->saved);
                } else {
                    m_helper->clearClipboard();
                }
                job->haveSaved = false;
                job->waiting = false;
                nextSegment();
            };
            m_helper->setClipboard(ours, [this, served, restoreAndContinue]() {
                *served = true;
                QTimer::singleShot(kPasteGraceMs, this, [restoreAndContinue]() {
                    (*restoreAndContinue)();
                });
            });
            // the selection change reaches the compositor before the key does (same connection order)
            QTimer::singleShot(30, this, [this, job, served, restoreAndContinue]() {
                if (job->done) {
                    return;
                }
                QStringList mods;
                xkb_keysym_t sym = XKB_KEY_NoSymbol;
                QString error;
                parseChord(job->pasteChord, &mods, &sym, &error);
                const auto stroke = strokeFor(sym);
                if (stroke) {
                    tap(KeyStroke{stroke->evdev, stroke->mods | modifierMask(mods)});
                    restoreRealModifiers();
                }
                QTimer::singleShot(kPasteServeWaitMs, this, [served, restoreAndContinue]() {
                    if (!*served) {
                        (*restoreAndContinue)();
                    }
                });
            });
        };
        if (job->haveSaved) {
            paste();
        } else {
            m_helper->snapshotClipboard([job, paste](ClipboardData data) {
                job->saved = std::move(data);
                job->haveSaved = true;
                paste();
            });
        }
        return;
    }
    }
}

// Waits until the target client has dispatched every event sent so far, then continues the job.
void AgentKeyboard::barrier(const std::shared_ptr<TextJob> &job)
{
    job->waiting = true;
    auto *ctx = new QObject(this);
    auto fired = std::make_shared<bool>(false);
    auto go = [this, job, ctx, fired](int settleMs) {
        if (*fired) {
            return;
        }
        *fired = true;
        ctx->deleteLater();
        QTimer::singleShot(settleMs, this, [this, job]() {
            if (job->done) {
                return;
            }
            job->waiting = false;
            job->barrierPassed = true;
            step(job);
        });
    };
    XdgSurfaceInterface *xdg = xdgSurfaceFor(job->surface);
    if (!xdg || !xdg->shell()) {
        go(kBarrierFallbackMs);
        return;
    }
    XdgShellInterface *shell = xdg->shell();
    const quint32 serial = shell->ping(xdg);
    connect(shell, &XdgShellInterface::pongReceived, ctx, [serial, go](quint32 s) {
        if (s == serial) {
            go(kBarrierSettleMs);
        }
    });
    connect(xdg, &QObject::destroyed, ctx, [go]() {
        go(0); // step() then notices that the window went away
    });
    QTimer::singleShot(kBarrierTimeoutMs, ctx, [go]() {
        go(0);
    });
}

void AgentKeyboard::finishJob(const std::shared_ptr<TextJob> &job, const QString &errorCode, const QString &error)
{
    if (job->done) {
        return;
    }
    job->done = true;
    job->waiting = false;
    if (job->haveSaved && m_helper) {
        // a paste was in flight: put the owner's clipboard back
        if (!job->saved.isEmpty()) {
            m_helper->setClipboard(job->saved);
        } else {
            m_helper->clearClipboard();
        }
    }
    auto finish = [this, job, errorCode, error]() {
        if (job->target || job->prevActive) {
            releaseFocus(*job);
        }
        m_agent->m_inCall = std::max(0, m_agent->m_inCall - 1);
        if (!errorCode.isEmpty()) {
            job->reply->fail(errorCode, error);
        } else {
            QJsonObject result{{QStringLiteral("target"), job->targetJson},
                               {QStringLiteral("paths"), QJsonArray::fromStringList(job->paths)},
                               {QStringLiteral("segments"), job->report}};
            if (job->paths.size() == 1) {
                result.insert(QStringLiteral("path"), job->paths.first());
            }
            job->reply->ok(result);
        }
        if (m_job == job) {
            m_job.reset();
        }
        if (m_focusHolder == job) {
            m_focusHolder.reset();
        }
    };
    if (errorCode.isEmpty()) {
        // let the client consume the last events while it still has focus
        if (job->xwayland) {
            whenXDelivered(this, *job, finish);
        } else {
            QTimer::singleShot(0, this, finish);
        }
    } else {
        finish();
    }
}

} // namespace Kristall
