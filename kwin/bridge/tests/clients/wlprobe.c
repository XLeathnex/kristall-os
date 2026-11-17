// SPDX-License-Identifier: GPL-3.0-or-later
// wlprobe: a raw Wayland test client for kristall-bridge. It maps one xdg_toplevel and logs every
// pointer, keyboard and text-input-v3 event it receives as one JSON object per line on stdout.
// Coordinates are surface-local, exactly as received (wl_fixed converted to double).
//
// Layout (logical px):  y < 30 title band (with --csd-move: press there calls xdg_toplevel.move)
//                       x < 100 && 30 <= y < 60: menu button (with --popup: opens a grabbing popup)
//                       everything else: content
// The popup is 150x90 at (0,60) of the window with three 30 px items; a click on an item logs
// {"ev":"item","index":N} and closes the popup.
#define _GNU_SOURCE
#include <errno.h>
#include <fcntl.h>
#include <getopt.h>
#include <linux/input-event-codes.h>
#include <poll.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/mman.h>
#include <time.h>
#include <unistd.h>
#include <wayland-client.h>
#include <xkbcommon/xkbcommon.h>

#include "text-input-unstable-v3-client-protocol.h"
#include "pointer-constraints-unstable-v1-client-protocol.h"
#include "xdg-decoration-unstable-v1-client-protocol.h"
#include "xdg-shell-client-protocol.h"

static struct {
    struct wl_display *display;
    struct wl_compositor *compositor;
    struct wl_shm *shm;
    struct wl_seat *seat;
    struct xdg_wm_base *wm;
    struct zxdg_decoration_manager_v1 *deco;
    struct zwp_text_input_manager_v3 *tim;
    struct zwp_pointer_constraints_v1 *constraints;
    struct zwp_locked_pointer_v1 *lock;
    struct zwp_confined_pointer_v1 *confine;
    bool want_lock, want_confine, lock_on_key;
    struct wl_pointer *pointer;
    struct wl_keyboard *keyboard;
    struct zwp_text_input_v3 *ti;
    struct wl_surface *surface;
    struct xdg_surface *xdg_surface;
    struct xdg_toplevel *toplevel;
    struct wl_surface *popup_surface;
    struct xdg_surface *popup_xdg;
    struct xdg_popup *popup;
    struct wl_surface *pointer_focus;
    struct xkb_context *xkb;
    struct xkb_keymap *keymap;
    struct xkb_state *state;
    int width, height;
    bool configured;
    bool want_popup, want_csd_move, want_ssd, want_text_input, animate;
    int frame_no;
    const char *title, *app_id;
    uint32_t last_button_serial;
    double px, py;
    int keymaps;
    uint32_t color;
} g = {.width = 400, .height = 300, .title = "wlprobe", .app_id = "wlprobe", .color = 0xff3060c0};

static double now_ms(void)
{
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return ts.tv_sec * 1000.0 + ts.tv_nsec / 1e6;
}

static void emit(const char *fmt, ...)
{
    char buf[4096];
    va_list ap;
    va_start(ap, fmt);
    vsnprintf(buf, sizeof(buf), fmt, ap);
    va_end(ap);
    printf("{\"t\":%.3f,%s}\n", now_ms(), buf);
    fflush(stdout);
}

static const char *surface_name(struct wl_surface *s)
{
    if (s == g.surface)
        return "main";
    if (s && s == g.popup_surface)
        return "popup";
    return "other";
}

// JSON string escaping for UTF-8 text
static void json_escape(const char *in, char *out, size_t outlen)
{
    size_t o = 0;
    for (const unsigned char *p = (const unsigned char *)in; *p && o + 8 < outlen; ++p) {
        if (*p == '"' || *p == '\\') {
            out[o++] = '\\';
            out[o++] = *p;
        } else if (*p < 0x20) {
            o += snprintf(out + o, outlen - o, "\\u%04x", *p);
        } else {
            out[o++] = *p;
        }
    }
    out[o] = 0;
}

// ------------------------------------------------------------------------------- buffers
static struct wl_buffer *make_buffer(int w, int h, uint32_t color)
{
    int stride = w * 4, size = stride * h;
    int fd = memfd_create("wlprobe", MFD_CLOEXEC);
    if (fd < 0 || ftruncate(fd, size) < 0)
        exit(1);
    uint32_t *data = mmap(NULL, size, PROT_READ | PROT_WRITE, MAP_SHARED, fd, 0);
    for (int i = 0; i < w * h; ++i)
        data[i] = color;
    // a darker title band and menu button so screenshots show the layout
    for (int y = 0; y < 30 && y < h; ++y)
        for (int x = 0; x < w; ++x)
            data[y * w + x] = 0xff202020;
    munmap(data, size);
    struct wl_shm_pool *pool = wl_shm_create_pool(g.shm, fd, size);
    struct wl_buffer *b = wl_shm_pool_create_buffer(pool, 0, w, h, stride, WL_SHM_FORMAT_ARGB8888);
    wl_shm_pool_destroy(pool);
    close(fd);
    return b;
}

// ------------------------------------------------------------------------------- popup
static void popup_xdg_configure(void *d, struct xdg_surface *s, uint32_t serial)
{
    xdg_surface_ack_configure(s, serial);
    wl_surface_attach(g.popup_surface, make_buffer(150, 90, 0xffe0e0e0), 0, 0);
    wl_surface_commit(g.popup_surface);
}
static const struct xdg_surface_listener popup_xdg_listener = {popup_xdg_configure};
static void popup_configure(void *d, struct xdg_popup *p, int32_t x, int32_t y, int32_t w, int32_t h)
{
    emit("\"ev\":\"popup_configure\",\"x\":%d,\"y\":%d,\"w\":%d,\"h\":%d", x, y, w, h);
}
static void close_popup(void)
{
    if (!g.popup)
        return;
    xdg_popup_destroy(g.popup);
    xdg_surface_destroy(g.popup_xdg);
    wl_surface_destroy(g.popup_surface);
    g.popup = NULL;
    g.popup_xdg = NULL;
    g.popup_surface = NULL;
}
static void popup_done(void *d, struct xdg_popup *p)
{
    emit("\"ev\":\"popup_done\"");
    close_popup();
}
static void popup_repositioned(void *d, struct xdg_popup *p, uint32_t token)
{
}
static const struct xdg_popup_listener popup_listener = {popup_configure, popup_done, popup_repositioned};

static void open_popup(uint32_t serial)
{
    struct xdg_positioner *pos = xdg_wm_base_create_positioner(g.wm);
    xdg_positioner_set_size(pos, 150, 90);
    xdg_positioner_set_anchor_rect(pos, 0, 30, 100, 30);
    xdg_positioner_set_anchor(pos, XDG_POSITIONER_ANCHOR_BOTTOM_LEFT);
    xdg_positioner_set_gravity(pos, XDG_POSITIONER_GRAVITY_BOTTOM_RIGHT);
    g.popup_surface = wl_compositor_create_surface(g.compositor);
    g.popup_xdg = xdg_wm_base_get_xdg_surface(g.wm, g.popup_surface);
    xdg_surface_add_listener(g.popup_xdg, &popup_xdg_listener, NULL);
    g.popup = xdg_surface_get_popup(g.popup_xdg, g.xdg_surface, pos);
    xdg_popup_add_listener(g.popup, &popup_listener, NULL);
    xdg_popup_grab(g.popup, g.seat, serial);
    xdg_positioner_destroy(pos);
    wl_surface_commit(g.popup_surface);
    emit("\"ev\":\"popup_open\",\"serial\":%u", serial);
}

// ------------------------------------------------------------------------------- pointer
static void p_enter(void *d, struct wl_pointer *p, uint32_t serial, struct wl_surface *s, wl_fixed_t x, wl_fixed_t y)
{
    g.pointer_focus = s;
    g.px = wl_fixed_to_double(x);
    g.py = wl_fixed_to_double(y);
    emit("\"ev\":\"enter\",\"surface\":\"%s\",\"x\":%.3f,\"y\":%.3f,\"serial\":%u", surface_name(s), g.px, g.py, serial);
}
static void p_leave(void *d, struct wl_pointer *p, uint32_t serial, struct wl_surface *s)
{
    emit("\"ev\":\"leave\",\"surface\":\"%s\"", surface_name(s));
    g.pointer_focus = NULL;
}
static void p_motion(void *d, struct wl_pointer *p, uint32_t time, wl_fixed_t x, wl_fixed_t y)
{
    g.px = wl_fixed_to_double(x);
    g.py = wl_fixed_to_double(y);
    emit("\"ev\":\"motion\",\"surface\":\"%s\",\"x\":%.3f,\"y\":%.3f,\"time\":%u", surface_name(g.pointer_focus), g.px, g.py, time);
}
static void p_button(void *d, struct wl_pointer *p, uint32_t serial, uint32_t time, uint32_t button, uint32_t state)
{
    emit("\"ev\":\"button\",\"surface\":\"%s\",\"button\":%u,\"state\":%u,\"x\":%.3f,\"y\":%.3f,\"time\":%u,\"serial\":%u",
         surface_name(g.pointer_focus), button, state, g.px, g.py, time, serial);
    if (state != WL_POINTER_BUTTON_STATE_PRESSED) {
        if (g.pointer_focus == g.popup_surface && g.popup && button == BTN_LEFT) {
            int index = (int)(g.py / 30);
            emit("\"ev\":\"item\",\"index\":%d", index);
            close_popup();
        }
        return;
    }
    g.last_button_serial = serial;
    if (g.pointer_focus == g.surface) {
        if (g.want_popup && !g.popup && g.px < 100 && g.py >= 30 && g.py < 60 && button == BTN_LEFT)
            open_popup(serial);
        else if (g.want_popup && !g.popup && button == BTN_RIGHT && g.py >= 60) {
            open_popup(serial); // context menu
        } else if (g.want_csd_move && g.py < 30 && button == BTN_LEFT) {
            emit("\"ev\":\"move_request\",\"serial\":%u", serial);
            xdg_toplevel_move(g.toplevel, g.seat, serial);
        }
    }
}
static void p_axis(void *d, struct wl_pointer *p, uint32_t time, uint32_t axis, wl_fixed_t value)
{
    emit("\"ev\":\"axis\",\"surface\":\"%s\",\"axis\":%u,\"value\":%.3f,\"x\":%.3f,\"y\":%.3f", surface_name(g.pointer_focus), axis,
         wl_fixed_to_double(value), g.px, g.py);
}
static void p_frame(void *d, struct wl_pointer *p)
{
    emit("\"ev\":\"frame\"");
}
static void p_axis_source(void *d, struct wl_pointer *p, uint32_t source)
{
    emit("\"ev\":\"axis_source\",\"source\":%u", source);
}
static void p_axis_stop(void *d, struct wl_pointer *p, uint32_t time, uint32_t axis)
{
}
static void p_axis_discrete(void *d, struct wl_pointer *p, uint32_t axis, int32_t discrete)
{
}
static void p_axis_value120(void *d, struct wl_pointer *p, uint32_t axis, int32_t v)
{
    emit("\"ev\":\"axis_value120\",\"axis\":%u,\"value\":%d", axis, v);
}
static void p_axis_relative_direction(void *d, struct wl_pointer *p, uint32_t axis, uint32_t dir)
{
}
static const struct wl_pointer_listener pointer_listener = {p_enter, p_leave, p_motion, p_button, p_axis, p_frame,
                                                            p_axis_source, p_axis_stop, p_axis_discrete, p_axis_value120, p_axis_relative_direction};

// ------------------------------------------------------------------------------- keyboard
static void k_keymap(void *d, struct wl_keyboard *k, uint32_t format, int32_t fd, uint32_t size)
{
    char *map = mmap(NULL, size, PROT_READ, MAP_PRIVATE, fd, 0);
    close(fd);
    if (map == MAP_FAILED)
        return;
    struct xkb_keymap *km = xkb_keymap_new_from_string(g.xkb, map, XKB_KEYMAP_FORMAT_TEXT_V1, XKB_KEYMAP_COMPILE_NO_FLAGS);
    munmap(map, size);
    if (!km) {
        emit("\"ev\":\"keymap_error\"");
        return;
    }
    if (g.state)
        xkb_state_unref(g.state);
    if (g.keymap)
        xkb_keymap_unref(g.keymap);
    g.keymap = km;
    g.state = xkb_state_new(km);
    g.keymaps++;
    char layout[128] = "";
    const char *name = xkb_keymap_layout_get_name(km, 0);
    json_escape(name ? name : "", layout, sizeof(layout));
    emit("\"ev\":\"keymap\",\"count\":%d,\"size\":%u,\"layout\":\"%s\"", g.keymaps, size, layout);
}
static void k_enter(void *d, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s, struct wl_array *keys)
{
    emit("\"ev\":\"key_enter\",\"surface\":\"%s\"", surface_name(s));
}
static void k_leave(void *d, struct wl_keyboard *k, uint32_t serial, struct wl_surface *s)
{
    emit("\"ev\":\"key_leave\",\"surface\":\"%s\"", surface_name(s));
}
static void apply_constraints(void);
static void k_key(void *d, struct wl_keyboard *k, uint32_t serial, uint32_t time, uint32_t key, uint32_t state)
{
    char utf8[64] = "", esc[128] = "", symname[64] = "";
    xkb_keysym_t sym = 0;
    if (g.state) {
        sym = xkb_state_key_get_one_sym(g.state, key + 8);
        xkb_keysym_get_name(sym, symname, sizeof(symname));
        if (state == WL_KEYBOARD_KEY_STATE_PRESSED)
            xkb_state_key_get_utf8(g.state, key + 8, utf8, sizeof(utf8));
    }
    json_escape(utf8, esc, sizeof(esc));
    xkb_mod_mask_t mods = g.state ? xkb_state_serialize_mods(g.state, XKB_STATE_MODS_EFFECTIVE) : 0;
    emit("\"ev\":\"key\",\"key\":%u,\"state\":%u,\"sym\":\"%s\",\"utf8\":\"%s\",\"mods\":%u", key, state, symname, esc, mods);
    if (g.lock_on_key && state == WL_KEYBOARD_KEY_STATE_PRESSED && sym == XKB_KEY_l) {
        g.want_lock = !g.want_lock;
        apply_constraints();
    }
}
static void k_modifiers(void *d, struct wl_keyboard *k, uint32_t serial, uint32_t dep, uint32_t lat, uint32_t lock, uint32_t group)
{
    if (g.state)
        xkb_state_update_mask(g.state, dep, lat, lock, 0, 0, group);
    emit("\"ev\":\"modifiers\",\"depressed\":%u,\"latched\":%u,\"locked\":%u,\"group\":%u", dep, lat, lock, group);
}
static void k_repeat(void *d, struct wl_keyboard *k, int32_t rate, int32_t delay)
{
}
static const struct wl_keyboard_listener keyboard_listener = {k_keymap, k_enter, k_leave, k_key, k_modifiers, k_repeat};

// ------------------------------------------------------------------------------- text input
static void ti_enter(void *d, struct zwp_text_input_v3 *t, struct wl_surface *s)
{
    emit("\"ev\":\"ti_enter\"");
    if (g.want_text_input) {
        zwp_text_input_v3_enable(t);
        zwp_text_input_v3_commit(t);
    }
}
static void ti_leave(void *d, struct zwp_text_input_v3 *t, struct wl_surface *s)
{
    emit("\"ev\":\"ti_leave\"");
    zwp_text_input_v3_disable(t);
    zwp_text_input_v3_commit(t);
}
static void ti_preedit(void *d, struct zwp_text_input_v3 *t, const char *text, int32_t b, int32_t e)
{
    char esc[1024] = "";
    json_escape(text ? text : "", esc, sizeof(esc));
    emit("\"ev\":\"ti_preedit\",\"text\":\"%s\"", esc);
}
static void ti_commit(void *d, struct zwp_text_input_v3 *t, const char *text)
{
    static char esc[65536];
    json_escape(text ? text : "", esc, sizeof(esc));
    emit("\"ev\":\"ti_commit\",\"text\":\"%s\"", esc);
}
static void ti_delete(void *d, struct zwp_text_input_v3 *t, uint32_t b, uint32_t a)
{
}
static void ti_done(void *d, struct zwp_text_input_v3 *t, uint32_t serial)
{
    emit("\"ev\":\"ti_done\",\"serial\":%u", serial);
}
static const struct zwp_text_input_v3_listener ti_listener = {ti_enter, ti_leave, ti_preedit, ti_commit, ti_delete, ti_done};

// ------------------------------------------------------------------------------- seat / registry
// --lock / --confine: a persistent pointer lock or confinement on the window (like a game);
// --lock-on-key: the key "l" toggles a pointer lock (requested, then destroyed).
static void apply_constraints(void)
{
    if (!g.constraints || !g.pointer || !g.surface)
        return;
    if (g.want_lock && !g.lock) {
        g.lock = zwp_pointer_constraints_v1_lock_pointer(g.constraints, g.surface, g.pointer, NULL, ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
        wl_surface_commit(g.surface);
        emit("\"ev\":\"lock\",\"on\":true");
    } else if (!g.want_lock && g.lock) {
        zwp_locked_pointer_v1_destroy(g.lock);
        g.lock = NULL;
        wl_surface_commit(g.surface);
        emit("\"ev\":\"lock\",\"on\":false");
    }
    if (g.want_confine && !g.confine) {
        g.confine = zwp_pointer_constraints_v1_confine_pointer(g.constraints, g.surface, g.pointer, NULL, ZWP_POINTER_CONSTRAINTS_V1_LIFETIME_PERSISTENT);
        wl_surface_commit(g.surface);
        emit("\"ev\":\"confine\",\"on\":true");
    }
}

static void seat_caps(void *d, struct wl_seat *s, uint32_t caps)
{
    if ((caps & WL_SEAT_CAPABILITY_POINTER) && !g.pointer) {
        g.pointer = wl_seat_get_pointer(s);
        wl_pointer_add_listener(g.pointer, &pointer_listener, NULL);
        apply_constraints();
    }
    if ((caps & WL_SEAT_CAPABILITY_KEYBOARD) && !g.keyboard) {
        g.keyboard = wl_seat_get_keyboard(s);
        wl_keyboard_add_listener(g.keyboard, &keyboard_listener, NULL);
    }
}
static void seat_name(void *d, struct wl_seat *s, const char *n)
{
}
static const struct wl_seat_listener seat_listener = {seat_caps, seat_name};

static void wm_ping(void *d, struct xdg_wm_base *wm, uint32_t serial)
{
    xdg_wm_base_pong(wm, serial);
}
static const struct xdg_wm_base_listener wm_listener = {wm_ping};

static void reg_global(void *d, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version)
{
    if (!strcmp(iface, wl_compositor_interface.name))
        g.compositor = wl_registry_bind(r, name, &wl_compositor_interface, 4);
    else if (!strcmp(iface, wl_shm_interface.name))
        g.shm = wl_registry_bind(r, name, &wl_shm_interface, 1);
    else if (!strcmp(iface, wl_seat_interface.name) && !g.seat) {
        g.seat = wl_registry_bind(r, name, &wl_seat_interface, version < 9 ? version : 9);
        wl_seat_add_listener(g.seat, &seat_listener, NULL);
    } else if (!strcmp(iface, xdg_wm_base_interface.name)) {
        g.wm = wl_registry_bind(r, name, &xdg_wm_base_interface, 2);
        xdg_wm_base_add_listener(g.wm, &wm_listener, NULL);
    } else if (!strcmp(iface, zxdg_decoration_manager_v1_interface.name))
        g.deco = wl_registry_bind(r, name, &zxdg_decoration_manager_v1_interface, 1);
    else if (!strcmp(iface, zwp_text_input_manager_v3_interface.name))
        g.tim = wl_registry_bind(r, name, &zwp_text_input_manager_v3_interface, 1);
    else if (!strcmp(iface, zwp_pointer_constraints_v1_interface.name))
        g.constraints = wl_registry_bind(r, name, &zwp_pointer_constraints_v1_interface, 1);
}
static void reg_remove(void *d, struct wl_registry *r, uint32_t name)
{
}
static const struct wl_registry_listener reg_listener = {reg_global, reg_remove};

static void frame_done(void *d, struct wl_callback *cb, uint32_t time);
static const struct wl_callback_listener frame_listener = {frame_done};
static void next_frame(void)
{
    struct wl_callback *cb = wl_surface_frame(g.surface);
    wl_callback_add_listener(cb, &frame_listener, NULL);
    uint32_t color = 0xff000000 | ((g.frame_no * 7) & 0xff) << 16 | 0x6000c0;
    g.frame_no++;
    wl_surface_attach(g.surface, make_buffer(g.width, g.height, color), 0, 0);
    wl_surface_damage(g.surface, 0, 0, g.width, g.height);
    wl_surface_commit(g.surface);
}
static void frame_done(void *d, struct wl_callback *cb, uint32_t time)
{
    wl_callback_destroy(cb);
    next_frame();
}

static void xdg_configure(void *d, struct xdg_surface *s, uint32_t serial)
{
    xdg_surface_ack_configure(s, serial);
    if (!g.configured) {
        wl_surface_attach(g.surface, make_buffer(g.width, g.height, g.color), 0, 0);
        wl_surface_damage(g.surface, 0, 0, g.width, g.height);
        g.configured = true;
        emit("\"ev\":\"mapped\",\"w\":%d,\"h\":%d", g.width, g.height);
        if (g.animate) {
            next_frame();
            return;
        }
    }
    wl_surface_commit(g.surface);
}
static const struct xdg_surface_listener xdg_surface_listener = {xdg_configure};
static void top_configure(void *d, struct xdg_toplevel *t, int32_t w, int32_t h, struct wl_array *states)
{
    bool activated = false;
    uint32_t *st;
    wl_array_for_each(st, states)
    {
        if (*st == XDG_TOPLEVEL_STATE_ACTIVATED)
            activated = true;
    }
    emit("\"ev\":\"configure\",\"w\":%d,\"h\":%d,\"activated\":%s", w, h, activated ? "true" : "false");
}
static void top_close(void *d, struct xdg_toplevel *t)
{
    emit("\"ev\":\"close\"");
    exit(0);
}
static void top_bounds(void *d, struct xdg_toplevel *t, int32_t w, int32_t h)
{
}
static void top_caps(void *d, struct xdg_toplevel *t, struct wl_array *c)
{
}
static const struct xdg_toplevel_listener toplevel_listener = {top_configure, top_close, top_bounds, top_caps};

int main(int argc, char **argv)
{
    static struct option opts[] = {{"size", required_argument, 0, 's'},  {"title", required_argument, 0, 't'},
                                   {"app-id", required_argument, 0, 'a'}, {"popup", no_argument, 0, 'p'},
                                   {"csd-move", no_argument, 0, 'm'},     {"ssd", no_argument, 0, 'd'},
                                   {"text-input", no_argument, 0, 'i'},   {"color", required_argument, 0, 'c'},
                                   {"animate", no_argument, 0, 'n'},     {"lock", no_argument, 0, 'L'},
                                   {"confine", no_argument, 0, 'C'},     {"lock-on-key", no_argument, 0, 'K'},
                                   {0, 0, 0, 0}};
    int c;
    while ((c = getopt_long(argc, argv, "", opts, NULL)) != -1) {
        switch (c) {
        case 's':
            sscanf(optarg, "%dx%d", &g.width, &g.height);
            break;
        case 't':
            g.title = optarg;
            break;
        case 'a':
            g.app_id = optarg;
            break;
        case 'p':
            g.want_popup = true;
            break;
        case 'm':
            g.want_csd_move = true;
            break;
        case 'd':
            g.want_ssd = true;
            break;
        case 'i':
            g.want_text_input = true;
            break;
        case 'c':
            g.color = (uint32_t)strtoul(optarg, NULL, 16);
            break;
        case 'n':
            g.animate = true;
            break;
        case 'L':
            g.want_lock = true;
            break;
        case 'C':
            g.want_confine = true;
            break;
        case 'K':
            g.lock_on_key = true;
            break;
        }
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    g.xkb = xkb_context_new(XKB_CONTEXT_NO_FLAGS);
    g.display = wl_display_connect(NULL);
    if (!g.display) {
        fprintf(stderr, "cannot connect\n");
        return 1;
    }
    struct wl_registry *reg = wl_display_get_registry(g.display);
    wl_registry_add_listener(reg, &reg_listener, NULL);
    wl_display_roundtrip(g.display);
    wl_display_roundtrip(g.display);
    if (g.tim && g.seat) {
        g.ti = zwp_text_input_manager_v3_get_text_input(g.tim, g.seat);
        zwp_text_input_v3_add_listener(g.ti, &ti_listener, NULL);
    }
    g.surface = wl_compositor_create_surface(g.compositor);
    g.xdg_surface = xdg_wm_base_get_xdg_surface(g.wm, g.surface);
    xdg_surface_add_listener(g.xdg_surface, &xdg_surface_listener, NULL);
    g.toplevel = xdg_surface_get_toplevel(g.xdg_surface);
    xdg_toplevel_add_listener(g.toplevel, &toplevel_listener, NULL);
    xdg_toplevel_set_title(g.toplevel, g.title);
    xdg_toplevel_set_app_id(g.toplevel, g.app_id);
    if (g.want_ssd && g.deco) {
        struct zxdg_toplevel_decoration_v1 *td = zxdg_decoration_manager_v1_get_toplevel_decoration(g.deco, g.toplevel);
        zxdg_toplevel_decoration_v1_set_mode(td, ZXDG_TOPLEVEL_DECORATION_V1_MODE_SERVER_SIDE);
    }
    wl_surface_commit(g.surface);
    apply_constraints();
    emit("\"ev\":\"started\",\"pid\":%d", getpid());
    while (wl_display_dispatch(g.display) != -1) {
    }
    emit("\"ev\":\"disconnected\"");
    return 0;
}
