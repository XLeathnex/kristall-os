// SPDX-License-Identifier: GPL-3.0-or-later
// xkeylog: an X11 (XWayland) window that logs every key it receives as one JSON line:
//   {"ev":"key","state":1,"keycode":N,"sym":"c","utf8":"c","mods":4}
// mods is the X11 modifier state at the event (Shift 1, Lock 2, Control 4, Mod1/Alt 8,
// Mod4/Super 64, Mod5/AltGr 128). Usage: xkeylog TITLE WM_CLASS
#include <X11/Xlib.h>
#include <X11/Xutil.h>
#include <X11/XKBlib.h>
#include <xkbcommon/xkbcommon.h>
#include <stdio.h>
#include <string.h>

static void json_escape(const char *in, char *out, size_t n)
{
    size_t o = 0;
    for (; *in && o + 7 < n; ++in) {
        unsigned char c = (unsigned char)*in;
        if (c == '"' || c == '\\') {
            out[o++] = '\\';
            out[o++] = (char)c;
        } else if (c < 0x20) {
            o += (size_t)snprintf(out + o, n - o, "\\u%04x", c);
        } else {
            out[o++] = (char)c;
        }
    }
    out[o] = 0;
}

int main(int argc, char **argv)
{
    const char *title = argc > 1 ? argv[1] : "xkeylog";
    const char *klass = argc > 2 ? argv[2] : "xkeylog";
    Display *d = XOpenDisplay(NULL);
    if (!d) {
        fprintf(stderr, "xkeylog: no display\n");
        return 1;
    }
    setvbuf(stdout, NULL, _IOLBF, 0);
    Window w = XCreateSimpleWindow(d, DefaultRootWindow(d), 0, 0, 420, 200, 0, 0, 0xdddddd);
    XStoreName(d, w, title);
    XClassHint ch = {(char *)klass, (char *)klass};
    XSetClassHint(d, w, &ch);
    XSelectInput(d, w, KeyPressMask | KeyReleaseMask | FocusChangeMask | ExposureMask);
    Atom wmDelete = XInternAtom(d, "WM_DELETE_WINDOW", False);
    XSetWMProtocols(d, w, &wmDelete, 1);
    XMapWindow(d, w);
    XFlush(d);
    printf("{\"ev\":\"started\"}\n");
    for (;;) {
        XEvent e;
        XNextEvent(d, &e);
        if (e.type == KeyPress || e.type == KeyRelease) {
            KeySym sym = NoSymbol;
            char buf[32] = {0};
            XLookupString(&e.xkey, buf, sizeof buf - 1, &sym, NULL);
            char utf8[16] = {0};
            if (sym != NoSymbol)
                xkb_keysym_to_utf8((xkb_keysym_t)sym, utf8, sizeof utf8);
            char esc[64];
            json_escape(utf8, esc, sizeof esc);
            const char *name = sym != NoSymbol ? XKeysymToString(sym) : "";
            printf("{\"ev\":\"key\",\"state\":%d,\"keycode\":%u,\"sym\":\"%s\",\"utf8\":\"%s\",\"mods\":%u}\n", e.type == KeyPress ? 1 : 0,
                   e.xkey.keycode, name ? name : "", esc, e.xkey.state);
        } else if (e.type == FocusIn) {
            printf("{\"ev\":\"focus\",\"in\":true}\n");
        } else if (e.type == FocusOut) {
            printf("{\"ev\":\"focus\",\"in\":false}\n");
        } else if (e.type == ClientMessage && (Atom)e.xclient.data.l[0] == wmDelete) {
            break;
        }
    }
    return 0;
}
