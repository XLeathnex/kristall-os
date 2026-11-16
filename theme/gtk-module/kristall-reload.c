// SPDX-License-Identifier: GPL-3.0-or-later
// kristall-reload-gtk-module: lets running GTK 3 apps follow the appearance switch.
// GTK 3 reads ~/.config/gtk-3.0/gtk.css (which imports kristall.css) only at start. This module
// watches kristall.css (rewritten by kristall-appearance on every change) and reloads it into a
// provider above the user priority, so the named colours adw-gtk3 uses (window_bg_color, …) and
// the window buttons change in open windows. Same technique as kde-gtk-config's colorreload
// module (which does this for colors.css). Loaded through GTK_MODULES; inactive if the file is
// missing. No polling: one GFileMonitor.
#include <gio/gio.h>
#include <gtk/gtk.h>

static GFile *file;
static GFileMonitor *monitor;
static GtkCssProvider *provider;

static void reload(void)
{
    GdkScreen *screen = gdk_screen_get_default();
    if (!screen)
        return;
    if (provider) {
        gtk_style_context_remove_provider_for_screen(screen, GTK_STYLE_PROVIDER(provider));
        g_clear_object(&provider);
    }
    if (!g_file_query_exists(file, NULL))
        return;
    provider = gtk_css_provider_new();
    gtk_css_provider_load_from_file(provider, file, NULL);
    gtk_style_context_add_provider_for_screen(screen, GTK_STYLE_PROVIDER(provider), GTK_STYLE_PROVIDER_PRIORITY_USER + 2);
}

static void changed(GFileMonitor *m, GFile *f, GFile *other, GFileMonitorEvent ev, gpointer data)
{
    (void)m; (void)f; (void)other; (void)data;
    if (ev == G_FILE_MONITOR_EVENT_CHANGES_DONE_HINT || ev == G_FILE_MONITOR_EVENT_CREATED || ev == G_FILE_MONITOR_EVENT_RENAMED
        || ev == G_FILE_MONITOR_EVENT_MOVED_IN || ev == G_FILE_MONITOR_EVENT_DELETED)
        reload();
}

__attribute__((visibility("default"))) void gtk_module_init(gint *argc, gchar ***argv)
{
    (void)argc; (void)argv;
    gchar *path = g_build_filename(g_get_user_config_dir(), "gtk-3.0", "kristall.css", NULL);
    file = g_file_new_for_path(path);
    g_free(path);
    monitor = g_file_monitor_file(file, G_FILE_MONITOR_WATCH_MOVES, NULL, NULL);
    if (monitor)
        g_signal_connect(monitor, "changed", G_CALLBACK(changed), NULL);
}
