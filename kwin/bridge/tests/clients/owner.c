// SPDX-License-Identifier: GPL-3.0-or-later
// owner: plays the laptop's owner in tests. It drives KWin's real input pipeline through the
// org_kde_kwin_fake_input protocol (exactly like a physical device: the cursor moves, focus and
// hover follow, global shortcuts and Escape are seen). Commands on stdin, one per line:
//   move X Y | rel DX DY | button CODE 1|0 | key CODE 1|0 | axis 0|1 VALUE | sync
// Every command is acknowledged with "ok" after a roundtrip.
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>
#include "fake-input-client-protocol.h"

static struct org_kde_kwin_fake_input *fi;

static void reg_global(void *d, struct wl_registry *r, uint32_t name, const char *iface, uint32_t version)
{
    if (!strcmp(iface, org_kde_kwin_fake_input_interface.name))
        fi = wl_registry_bind(r, name, &org_kde_kwin_fake_input_interface, version < 4 ? version : 4);
}
static void reg_remove(void *d, struct wl_registry *r, uint32_t name)
{
}
static const struct wl_registry_listener listener = {reg_global, reg_remove};

int main(void)
{
    struct wl_display *dpy = wl_display_connect(NULL);
    if (!dpy) {
        fprintf(stderr, "owner: cannot connect\n");
        return 1;
    }
    struct wl_registry *reg = wl_display_get_registry(dpy);
    wl_registry_add_listener(reg, &listener, NULL);
    wl_display_roundtrip(dpy);
    if (!fi) {
        fprintf(stderr, "owner: no fake input\n");
        return 1;
    }
    org_kde_kwin_fake_input_authenticate(fi, "kristall-bridge tests", "plays the owner");
    wl_display_roundtrip(dpy);
    setvbuf(stdout, NULL, _IOLBF, 0);
    printf("ready\n");
    char line[256];
    while (fgets(line, sizeof line, stdin)) {
        double a, b;
        unsigned u, v;
        if (sscanf(line, "move %lf %lf", &a, &b) == 2)
            org_kde_kwin_fake_input_pointer_motion_absolute(fi, wl_fixed_from_double(a), wl_fixed_from_double(b));
        else if (sscanf(line, "rel %lf %lf", &a, &b) == 2)
            org_kde_kwin_fake_input_pointer_motion(fi, wl_fixed_from_double(a), wl_fixed_from_double(b));
        else if (sscanf(line, "button %u %u", &u, &v) == 2)
            org_kde_kwin_fake_input_button(fi, u, v);
        else if (sscanf(line, "key %u %u", &u, &v) == 2)
            org_kde_kwin_fake_input_keyboard_key(fi, u, v);
        else if (sscanf(line, "axis %u %lf", &u, &a) == 2)
            org_kde_kwin_fake_input_axis(fi, u, wl_fixed_from_double(a));
        wl_display_roundtrip(dpy);
        printf("ok\n");
    }
    return 0;
}
