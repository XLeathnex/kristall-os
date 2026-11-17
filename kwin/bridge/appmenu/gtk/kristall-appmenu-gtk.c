// SPDX-License-Identifier: GPL-3.0-or-later
// kristall-appmenu-gtk-module: GTK 3 apps on Wayland show their menus in the Kristall menu bar.
//
// GTK 3 exports menus only on X11 (unity-gtk-module + Plasma's gmenudbusmenuproxy read X window
// properties); on Wayland a GtkMenuBar stays in the window and the menu bar has nothing to show.
// This module, loaded into every GTK 3 app through GTK_MODULES (kwin/bridge/appmenu), does on
// Wayland what Qt does there:
//   * every GtkMenuBar in a top-level window is published as a DBusMenu (com.canonical.dbusmenu)
//     on the session bus, mirrored live from the widgets (labels, mnemonics, enabled, visible,
//     check/radio state, submenus, accelerators as shortcuts); "clicked" activates the item;
//   * KWin is told where it is through its app-menu protocol (org_kde_kwin_appmenu_manager on the
//     window's wl_surface), so the bridge reports it as the window's `menu`;
//   * while a Kristall menu bar shows app menus (the bridge owns org.kristall.AppMenuView), the
//     in-window menu bar takes no space and is not drawn (its "visible" property, which apps bind
//     to their own settings, is never touched); when that name is gone (the shell crashed or is
//     not running) for a moment, the in-window menu bar comes back.
//   * GtkApplicationWindow menu bars are created in the window as well (gtk-shell-shows-menubar is
//     kept off in the process), so they take the same path; GTK's own setting is meant for
//     shells that read GTK's X11 properties.
// On X11, without the session bus or without KWin's app-menu protocol the module does nothing.
#include <gdk/gdkwayland.h>
#include <gtk/gtk.h>
#include <stdlib.h>
#include <string.h>
#include <wayland-client.h>

#include "appmenu-client-protocol.h"

#define VIEW_NAME "org.kristall.AppMenuView"
#define DBUSMENU_IFACE "com.canonical.dbusmenu"

typedef struct {
    GtkWidget *menubar;           // weak (bar_free on "destroy")
    GtkWidget *toplevel;          // the window the menu bar lives in (strong ref while tracked)
    char *path;
    guint reg_id;
    GHashTable *items;            // id -> GtkWidget* (weakly referenced)
    int next_id;
    guint revision;
    guint update_idle;
    struct wl_surface *surface;   // surface the address was announced for
    struct org_kde_kwin_appmenu *appmenu;
    gulong map_id, unmap_id;
    guint collapse_idle;
} Bar;

static GDBusConnection *bus;
static GDBusNodeInfo *node_info;
static struct wl_display *wl_dpy;
static struct wl_event_queue *wl_queue;
static struct org_kde_kwin_appmenu_manager *manager;
static GQuark q_bar, q_id, q_watched;
static GSList *bars;
static guint bar_serial;
static gboolean view_present, view_seen, collapsed;
static guint grace_id;

static const char introspection_xml[] =
    "<node>"
    " <interface name='com.canonical.dbusmenu'>"
    "  <property name='Version' type='u' access='read'/>"
    "  <property name='TextDirection' type='s' access='read'/>"
    "  <property name='Status' type='s' access='read'/>"
    "  <property name='IconThemePath' type='as' access='read'/>"
    "  <method name='GetLayout'><arg type='i' direction='in'/><arg type='i' direction='in'/><arg type='as' direction='in'/>"
    "   <arg type='u' direction='out'/><arg type='(ia{sv}av)' direction='out'/></method>"
    "  <method name='GetGroupProperties'><arg type='ai' direction='in'/><arg type='as' direction='in'/>"
    "   <arg type='a(ia{sv})' direction='out'/></method>"
    "  <method name='GetProperty'><arg type='i' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='out'/></method>"
    "  <method name='Event'><arg type='i' direction='in'/><arg type='s' direction='in'/><arg type='v' direction='in'/>"
    "   <arg type='u' direction='in'/></method>"
    "  <method name='EventGroup'><arg type='a(isvu)' direction='in'/><arg type='ai' direction='out'/></method>"
    "  <method name='AboutToShow'><arg type='i' direction='in'/><arg type='b' direction='out'/></method>"
    "  <method name='AboutToShowGroup'><arg type='ai' direction='in'/><arg type='ai' direction='out'/><arg type='ai' direction='out'/></method>"
    "  <signal name='ItemsPropertiesUpdated'><arg type='a(ia{sv})'/><arg type='a(ias)'/></signal>"
    "  <signal name='LayoutUpdated'><arg type='u'/><arg type='i'/></signal>"
    "  <signal name='ItemActivationRequested'><arg type='i'/><arg type='u'/></signal>"
    " </interface>"
    "</node>";

// ------------------------------------------------------------------------------------------------
// in-window menu bar: no space and not drawn while the Kristall menu bar shows its menus

static void (*orig_preferred_width)(GtkWidget *, gint *, gint *);
static void (*orig_preferred_height)(GtkWidget *, gint *, gint *);
static void (*orig_preferred_width_for_height)(GtkWidget *, gint, gint *, gint *);
static void (*orig_preferred_height_for_width)(GtkWidget *, gint, gint *, gint *);

static gboolean is_collapsed(GtkWidget *w)
{
    return collapsed && g_object_get_qdata(G_OBJECT(w), q_bar) != NULL;
}

static void pw(GtkWidget *w, gint *min, gint *nat)
{
    orig_preferred_width(w, min, nat);
    if (is_collapsed(w))
        *min = *nat = 0;
}

static void ph(GtkWidget *w, gint *min, gint *nat)
{
    orig_preferred_height(w, min, nat);
    if (is_collapsed(w))
        *min = *nat = 0;
}

static void pwh(GtkWidget *w, gint h, gint *min, gint *nat)
{
    orig_preferred_width_for_height(w, h, min, nat);
    if (is_collapsed(w))
        *min = *nat = 0;
}

static void phw(GtkWidget *w, gint wd, gint *min, gint *nat)
{
    orig_preferred_height_for_width(w, wd, min, nat);
    if (is_collapsed(w))
        *min = *nat = 0;
}

static void apply_collapse(Bar *b)
{
    // not mapped while collapsed: no drawing, no pointer input, no mnemonics on an invisible bar
    gtk_widget_set_child_visible(b->menubar, !collapsed);
    if (collapsed && gtk_widget_get_mapped(b->menubar))
        gtk_widget_unmap(b->menubar);
    gtk_widget_queue_resize(b->menubar);
}

static gboolean collapse_later(gpointer data)
{
    Bar *b = data;
    b->collapse_idle = 0;
    apply_collapse(b);
    return G_SOURCE_REMOVE;
}

static void on_menubar_map(GtkWidget *w, gpointer data)
{
    (void)w;
    Bar *b = data;
    // realised as part of being mapped (the parent maps it after we said child-visible = FALSE)
    if (collapsed && !b->collapse_idle)
        b->collapse_idle = g_idle_add(collapse_later, b);
}

static void set_collapsed(gboolean on)
{
    if (collapsed == on)
        return;
    collapsed = on;
    for (GSList *l = bars; l; l = l->next)
        apply_collapse(l->data);
}

static int grace_ms(void)
{
    const char *forced = g_getenv("KRISTALL_APPMENU_FALLBACK_MS"); // tests
    if (forced && *forced)
        return atoi(forced);
    return view_seen ? 3000 : 8000;
}

static gboolean grace_over(gpointer data)
{
    (void)data;
    grace_id = 0;
    set_collapsed(FALSE);
    return G_SOURCE_REMOVE;
}

static void view_changed(gboolean present)
{
    view_present = present;
    if (present) {
        view_seen = TRUE;
        if (grace_id) {
            g_source_remove(grace_id);
            grace_id = 0;
        }
        set_collapsed(TRUE);
    } else if (collapsed && !grace_id) {
        grace_id = g_timeout_add(grace_ms(), grace_over, NULL);
    }
}

static void name_appeared(GDBusConnection *c, const gchar *name, const gchar *owner, gpointer data)
{
    (void)c; (void)name; (void)owner; (void)data;
    view_changed(TRUE);
}

static void name_vanished(GDBusConnection *c, const gchar *name, gpointer data)
{
    (void)c; (void)name; (void)data;
    view_changed(FALSE);
}

// ------------------------------------------------------------------------------------------------
// DBusMenu from the widgets

static void schedule_update(Bar *b);

static void item_gone(gpointer data, GObject *where)
{
    Bar *b = data;
    GHashTableIter it;
    gpointer k, v;
    g_hash_table_iter_init(&it, b->items);
    while (g_hash_table_iter_next(&it, &k, &v)) {
        if (v == (gpointer)where) {
            g_hash_table_iter_remove(&it);
            break;
        }
    }
    schedule_update(b);
}

static void on_notify(GObject *o, GParamSpec *p, gpointer data)
{
    (void)o;
    static const char *const relevant[] = {"label", "sensitive", "visible", "active", "inconsistent", "submenu", "draw-as-radio",
                                           "use-underline", "action-role", NULL};
    for (int i = 0; relevant[i]; ++i) {
        if (strcmp(p->name, relevant[i]) == 0) {
            schedule_update(data);
            return;
        }
    }
}

static void on_children_changed(GtkContainer *c, GtkWidget *w, gpointer data)
{
    (void)c; (void)w;
    schedule_update(data);
}

static void on_insert(GtkMenuShell *s, GtkWidget *w, gint pos, gpointer data)
{
    (void)s; (void)w; (void)pos;
    schedule_update(data);
}

static int item_id(Bar *b, GtkWidget *item)
{
    int id = GPOINTER_TO_INT(g_object_get_qdata(G_OBJECT(item), q_id));
    if (id > 0 && g_hash_table_lookup(b->items, GINT_TO_POINTER(id)) == item)
        return id;
    id = b->next_id++;
    g_object_set_qdata(G_OBJECT(item), q_id, GINT_TO_POINTER(id));
    g_hash_table_insert(b->items, GINT_TO_POINTER(id), item);
    g_object_weak_ref(G_OBJECT(item), item_gone, b);
    g_signal_connect(item, "notify", G_CALLBACK(on_notify), b);
    return id;
}

static GtkWidget *find_label(GtkWidget *w)
{
    if (GTK_IS_LABEL(w))
        return w;
    if (GTK_IS_CONTAINER(w)) {
        GList *kids = gtk_container_get_children(GTK_CONTAINER(w));
        GtkWidget *found = NULL;
        for (GList *l = kids; l && !found; l = l->next)
            found = find_label(l->data);
        g_list_free(kids);
        return found;
    }
    return NULL;
}

static GtkWidget *find_accel_label(GtkWidget *w)
{
    if (GTK_IS_ACCEL_LABEL(w))
        return w;
    if (GTK_IS_CONTAINER(w)) {
        GList *kids = gtk_container_get_children(GTK_CONTAINER(w));
        GtkWidget *found = NULL;
        for (GList *l = kids; l && !found; l = l->next)
            found = find_accel_label(l->data);
        g_list_free(kids);
        return found;
    }
    return NULL;
}

static gboolean find_closure(GtkAccelKey *key, GClosure *closure, gpointer data)
{
    (void)key;
    return closure == data;
}

static gboolean item_accel(GtkWidget *item, guint *key, GdkModifierType *mods)
{
    *key = 0;
    *mods = 0;
    GtkWidget *child = gtk_bin_get_child(GTK_BIN(item));
    GtkWidget *al = child ? find_accel_label(child) : NULL;
    if (al) {
        gtk_accel_label_get_accel(GTK_ACCEL_LABEL(al), key, mods); // set_accel (GMenuModel items)
        if (*key == 0) {
            GClosure *closure = NULL;
            g_object_get(al, "accel-closure", &closure, NULL);
            if (closure) {
                GtkAccelGroup *group = gtk_accel_group_from_accel_closure(closure);
                GtkAccelKey *k = group ? gtk_accel_group_find(group, find_closure, closure) : NULL;
                if (k) {
                    *key = k->accel_key;
                    *mods = k->accel_mods;
                }
                g_closure_unref(closure);
            }
        }
    }
    if (*key == 0) {
        const char *path = gtk_menu_item_get_accel_path(GTK_MENU_ITEM(item));
        GtkAccelKey k;
        if (path && gtk_accel_map_lookup_entry(path, &k)) {
            *key = k.accel_key;
            *mods = k.accel_mods;
        }
    }
    return *key != 0;
}

static int item_role(GtkWidget *item) // 0 normal, 1 check, 2 radio
{
    if (!GTK_IS_CHECK_MENU_ITEM(item))
        return 0;
    if (g_object_class_find_property(G_OBJECT_GET_CLASS(item), "action-role")) { // GtkModelMenuItem
        int role = 0;
        g_object_get(item, "action-role", &role, NULL);
        return role;
    }
    return GTK_IS_RADIO_MENU_ITEM(item) || gtk_check_menu_item_get_draw_as_radio(GTK_CHECK_MENU_ITEM(item)) ? 2 : 1;
}

static GVariant *item_props(GtkWidget *item)
{
    GVariantBuilder props;
    g_variant_builder_init(&props, G_VARIANT_TYPE("a{sv}"));
    if (!gtk_widget_get_visible(item))
        g_variant_builder_add(&props, "{sv}", "visible", g_variant_new_boolean(FALSE));
    if (GTK_IS_SEPARATOR_MENU_ITEM(item)) {
        g_variant_builder_add(&props, "{sv}", "type", g_variant_new_string("separator"));
        return g_variant_builder_end(&props);
    }
    const char *label = gtk_menu_item_get_label(GTK_MENU_ITEM(item));
    gboolean underline = gtk_menu_item_get_use_underline(GTK_MENU_ITEM(item));
    if (!label || !*label) {
        GtkWidget *child = gtk_bin_get_child(GTK_BIN(item));
        GtkWidget *l = child ? find_label(child) : NULL;
        if (l) {
            label = gtk_label_get_label(GTK_LABEL(l));
            underline = gtk_label_get_use_underline(GTK_LABEL(l));
        }
    }
    if (label) {
        if (underline) {
            g_variant_builder_add(&props, "{sv}", "label", g_variant_new_string(label));
        } else { // DBusMenu treats '_' as the mnemonic marker: double it
            GString *s = g_string_new(NULL);
            for (const char *c = label; *c; ++c) {
                if (*c == '_')
                    g_string_append_c(s, '_');
                g_string_append_c(s, *c);
            }
            g_variant_builder_add(&props, "{sv}", "label", g_variant_new_string(s->str));
            g_string_free(s, TRUE);
        }
    }
    if (!gtk_widget_get_sensitive(item))
        g_variant_builder_add(&props, "{sv}", "enabled", g_variant_new_boolean(FALSE));
    const int role = item_role(item);
    if (role) {
        g_variant_builder_add(&props, "{sv}", "toggle-type", g_variant_new_string(role == 2 ? "radio" : "checkmark"));
        g_variant_builder_add(&props, "{sv}", "toggle-state",
                              g_variant_new_int32(gtk_check_menu_item_get_active(GTK_CHECK_MENU_ITEM(item)) ? 1 : 0));
    }
    if (gtk_menu_item_get_submenu(GTK_MENU_ITEM(item)))
        g_variant_builder_add(&props, "{sv}", "children-display", g_variant_new_string("submenu"));
    guint key;
    GdkModifierType mods;
    if (item_accel(item, &key, &mods)) {
        GVariantBuilder chord;
        g_variant_builder_init(&chord, G_VARIANT_TYPE("as"));
        if (mods & GDK_CONTROL_MASK)
            g_variant_builder_add(&chord, "s", "Control");
        if (mods & GDK_MOD1_MASK)
            g_variant_builder_add(&chord, "s", "Alt");
        if (mods & GDK_SHIFT_MASK)
            g_variant_builder_add(&chord, "s", "Shift");
        if (mods & (GDK_SUPER_MASK | GDK_META_MASK))
            g_variant_builder_add(&chord, "s", "Super");
        const char *name = gdk_keyval_name(gdk_keyval_to_lower(key));
        if (name) {
            char *k = strlen(name) == 1 ? g_ascii_strup(name, -1) : g_strdup(name);
            g_variant_builder_add(&chord, "s", k);
            g_free(k);
            GVariantBuilder chords;
            g_variant_builder_init(&chords, G_VARIANT_TYPE("aas"));
            g_variant_builder_add_value(&chords, g_variant_builder_end(&chord));
            g_variant_builder_add(&props, "{sv}", "shortcut", g_variant_builder_end(&chords));
        } else {
            g_variant_builder_clear(&chord);
        }
    }
    return g_variant_builder_end(&props);
}

static void connect_shell(Bar *b, GtkWidget *shell)
{
    if (g_object_get_qdata(G_OBJECT(shell), q_watched) == b)
        return;
    g_object_set_qdata(G_OBJECT(shell), q_watched, b);
    g_signal_connect(shell, "add", G_CALLBACK(on_children_changed), b);
    g_signal_connect(shell, "remove", G_CALLBACK(on_children_changed), b);
    g_signal_connect(shell, "insert", G_CALLBACK(on_insert), b);
}

static GVariant *node(Bar *b, GtkWidget *item, int depth);

static GVariant *children_of(Bar *b, GtkWidget *shell, int depth)
{
    GVariantBuilder kids;
    g_variant_builder_init(&kids, G_VARIANT_TYPE("av"));
    if (shell && depth != 0) {
        connect_shell(b, shell);
        GList *list = gtk_container_get_children(GTK_CONTAINER(shell));
        for (GList *l = list; l; l = l->next) {
            G_GNUC_BEGIN_IGNORE_DEPRECATIONS
            const gboolean tearoff = GTK_IS_TEAROFF_MENU_ITEM(l->data);
            G_GNUC_END_IGNORE_DEPRECATIONS
            if (GTK_IS_MENU_ITEM(l->data) && !tearoff)
                g_variant_builder_add(&kids, "v", node(b, l->data, depth < 0 ? -1 : depth - 1));
        }
        g_list_free(list);
    }
    return g_variant_builder_end(&kids);
}

static GVariant *node(Bar *b, GtkWidget *item, int depth)
{
    const int id = item_id(b, item);
    GtkWidget *sub = gtk_menu_item_get_submenu(GTK_MENU_ITEM(item));
    return g_variant_new("(i@a{sv}@av)", id, item_props(item), children_of(b, sub, depth));
}

static GVariant *root_node(Bar *b, int depth)
{
    GVariantBuilder props;
    g_variant_builder_init(&props, G_VARIANT_TYPE("a{sv}"));
    g_variant_builder_add(&props, "{sv}", "children-display", g_variant_new_string("submenu"));
    return g_variant_new("(i@a{sv}@av)", 0, g_variant_builder_end(&props), children_of(b, b->menubar, depth));
}

static gboolean emit_update(gpointer data)
{
    Bar *b = data;
    b->update_idle = 0;
    ++b->revision;
    g_dbus_connection_emit_signal(bus, NULL, b->path, DBUSMENU_IFACE, "LayoutUpdated", g_variant_new("(ui)", b->revision, 0), NULL);
    return G_SOURCE_REMOVE;
}

static void schedule_update(Bar *b)
{
    if (!b->update_idle)
        b->update_idle = g_timeout_add(30, emit_update, b); // coalesce: menus change in bursts
}

static gboolean activate_later(gpointer data)
{
    GtkWidget *item = data;
    if (gtk_widget_is_sensitive(item))
        gtk_menu_item_activate(GTK_MENU_ITEM(item));
    g_object_unref(item);
    return G_SOURCE_REMOVE;
}

static gboolean handle_event(Bar *b, int id, const char *event)
{
    GtkWidget *item = g_hash_table_lookup(b->items, GINT_TO_POINTER(id));
    if (!item)
        return FALSE;
    if (strcmp(event, "clicked") == 0 && gtk_widget_is_sensitive(item) && !gtk_menu_item_get_submenu(GTK_MENU_ITEM(item))) {
        // after the D-Bus reply: an action may open a dialog with its own main loop
        g_idle_add(activate_later, g_object_ref(item));
    }
    return TRUE;
}

static void method_call(GDBusConnection *c, const gchar *sender, const gchar *path, const gchar *iface, const gchar *method,
                        GVariant *params, GDBusMethodInvocation *inv, gpointer data)
{
    (void)c; (void)sender; (void)path; (void)iface;
    Bar *b = data;
    if (strcmp(method, "GetLayout") == 0) {
        gint parent, depth;
        g_variant_get(params, "(ii^a&s)", &parent, &depth, NULL);
        GVariant *layout;
        if (parent == 0) {
            layout = root_node(b, depth);
        } else {
            GtkWidget *item = g_hash_table_lookup(b->items, GINT_TO_POINTER(parent));
            if (!item) {
                g_dbus_method_invocation_return_dbus_error(inv, "org.freedesktop.DBus.Error.InvalidArgs", "unknown item");
                return;
            }
            layout = node(b, item, depth);
        }
        g_dbus_method_invocation_return_value(inv, g_variant_new("(u@(ia{sv}av))", b->revision, layout));
    } else if (strcmp(method, "GetGroupProperties") == 0) {
        GVariantIter *ids;
        g_variant_get(params, "(ai^a&s)", &ids, NULL);
        GVariantBuilder out;
        g_variant_builder_init(&out, G_VARIANT_TYPE("a(ia{sv})"));
        gint id;
        while (g_variant_iter_next(ids, "i", &id)) {
            GtkWidget *item = g_hash_table_lookup(b->items, GINT_TO_POINTER(id));
            if (item)
                g_variant_builder_add(&out, "(i@a{sv})", id, item_props(item));
        }
        g_variant_iter_free(ids);
        g_dbus_method_invocation_return_value(inv, g_variant_new("(@a(ia{sv}))", g_variant_builder_end(&out)));
    } else if (strcmp(method, "GetProperty") == 0) {
        gint id;
        const char *name;
        g_variant_get(params, "(i&s)", &id, &name);
        GtkWidget *item = g_hash_table_lookup(b->items, GINT_TO_POINTER(id));
        GVariant *props = item ? item_props(item) : NULL;
        GVariant *v = props ? g_variant_lookup_value(props, name, NULL) : NULL;
        if (props)
            g_variant_unref(g_variant_ref_sink(props));
        if (!v) {
            g_dbus_method_invocation_return_dbus_error(inv, "org.freedesktop.DBus.Error.InvalidArgs", "unknown item or property");
            return;
        }
        g_dbus_method_invocation_return_value(inv, g_variant_new("(v)", v));
        g_variant_unref(v);
    } else if (strcmp(method, "Event") == 0) {
        gint id;
        const char *event;
        g_variant_get(params, "(i&svu)", &id, &event, NULL, NULL);
        handle_event(b, id, event);
        g_dbus_method_invocation_return_value(inv, NULL);
    } else if (strcmp(method, "EventGroup") == 0) {
        GVariantIter *events;
        g_variant_get(params, "(a(isvu))", &events);
        GVariantBuilder errors;
        g_variant_builder_init(&errors, G_VARIANT_TYPE("ai"));
        gint id;
        const char *event;
        GVariant *payload;
        guint32 ts;
        while (g_variant_iter_next(events, "(i&svu)", &id, &event, &payload, &ts)) {
            if (!handle_event(b, id, event))
                g_variant_builder_add(&errors, "i", id);
            g_variant_unref(payload);
        }
        g_variant_iter_free(events);
        g_dbus_method_invocation_return_value(inv, g_variant_new("(@ai)", g_variant_builder_end(&errors)));
    } else if (strcmp(method, "AboutToShow") == 0) {
        g_dbus_method_invocation_return_value(inv, g_variant_new("(b)", FALSE)); // the layout is always current
    } else if (strcmp(method, "AboutToShowGroup") == 0) {
        g_dbus_method_invocation_return_value(inv, g_variant_new("(@ai@ai)", g_variant_new_array(G_VARIANT_TYPE_INT32, NULL, 0),
                                                                  g_variant_new_array(G_VARIANT_TYPE_INT32, NULL, 0)));
    } else {
        g_dbus_method_invocation_return_dbus_error(inv, "org.freedesktop.DBus.Error.UnknownMethod", method);
    }
}

static GVariant *get_property(GDBusConnection *c, const gchar *sender, const gchar *path, const gchar *iface, const gchar *prop,
                              GError **error, gpointer data)
{
    (void)c; (void)sender; (void)path; (void)iface; (void)error; (void)data;
    if (strcmp(prop, "Version") == 0)
        return g_variant_new_uint32(3);
    if (strcmp(prop, "TextDirection") == 0)
        return g_variant_new_string(gtk_widget_get_default_direction() == GTK_TEXT_DIR_RTL ? "rtl" : "ltr");
    if (strcmp(prop, "Status") == 0)
        return g_variant_new_string("normal");
    if (strcmp(prop, "IconThemePath") == 0)
        return g_variant_new_array(G_VARIANT_TYPE_STRING, NULL, 0);
    return NULL;
}

static const GDBusInterfaceVTable vtable = {method_call, get_property, NULL, {0}};

// ------------------------------------------------------------------------------------------------
// tell KWin where the menu is (app-menu protocol on the window's surface)

static void announce(Bar *b)
{
    GdkWindow *gw = b->toplevel ? gtk_widget_get_window(b->toplevel) : NULL;
    if (!gw || !GDK_IS_WAYLAND_WINDOW(gw))
        return;
    struct wl_surface *surface = gdk_wayland_window_get_wl_surface(gw);
    if (!surface || surface == b->surface)
        return;
    if (b->appmenu) // GTK made a new surface for the window (hidden and shown again)
        org_kde_kwin_appmenu_release(b->appmenu);
    b->surface = surface;
    b->appmenu = org_kde_kwin_appmenu_manager_create(manager, surface);
    org_kde_kwin_appmenu_set_address(b->appmenu, g_dbus_connection_get_unique_name(bus), b->path);
    wl_display_flush(wl_dpy);
}

static void on_toplevel_map(GtkWidget *w, gpointer data)
{
    (void)w;
    announce(data);
}

static void on_toplevel_unmap(GtkWidget *w, gpointer data)
{
    (void)w;
    Bar *b = data;
    b->surface = NULL; // GTK destroys the surface on unmap; a new one comes with the next map
}

static void bar_free(GtkWidget *menubar, gpointer data)
{
    Bar *b = data;
    bars = g_slist_remove(bars, b);
    g_object_set_qdata(G_OBJECT(menubar), q_bar, NULL);
    if (b->update_idle)
        g_source_remove(b->update_idle);
    if (b->collapse_idle)
        g_source_remove(b->collapse_idle);
    if (b->reg_id)
        g_dbus_connection_unregister_object(bus, b->reg_id);
    if (b->appmenu) {
        org_kde_kwin_appmenu_release(b->appmenu);
        wl_display_flush(wl_dpy);
    }
    GHashTableIter it;
    gpointer k, v;
    g_hash_table_iter_init(&it, b->items);
    while (g_hash_table_iter_next(&it, &k, &v)) {
        GtkWidget *sub = gtk_menu_item_get_submenu(GTK_MENU_ITEM(v));
        if (sub) {
            g_signal_handlers_disconnect_by_data(sub, b);
            g_object_set_qdata(G_OBJECT(sub), q_watched, NULL);
        }
        g_object_weak_unref(G_OBJECT(v), item_gone, b);
        g_signal_handlers_disconnect_by_data(v, b);
    }
    g_signal_handlers_disconnect_by_data(menubar, b);
    g_object_set_qdata(G_OBJECT(menubar), q_watched, NULL);
    g_hash_table_destroy(b->items);
    if (b->toplevel) {
        g_signal_handler_disconnect(b->toplevel, b->map_id);
        g_signal_handler_disconnect(b->toplevel, b->unmap_id);
        g_object_unref(b->toplevel);
    }
    g_free(b->path);
    g_free(b);
}

static void track(GtkWidget *menubar)
{
    GtkWidget *top = gtk_widget_get_toplevel(menubar);
    if (!GTK_IS_WINDOW(top) || !gtk_widget_is_toplevel(top) || gtk_window_get_window_type(GTK_WINDOW(top)) != GTK_WINDOW_TOPLEVEL)
        return;
    for (GSList *l = bars; l; l = l->next) { // one exported menu bar per window (the first)
        if (((Bar *)l->data)->toplevel == top)
            return;
    }
    Bar *b = g_new0(Bar, 1);
    b->menubar = menubar;
    b->toplevel = g_object_ref(top);
    b->path = g_strdup_printf("/org/kristall/AppMenu/%u", ++bar_serial);
    b->items = g_hash_table_new(g_direct_hash, g_direct_equal);
    b->next_id = 1;
    b->revision = 1;
    GError *err = NULL;
    b->reg_id = g_dbus_connection_register_object(bus, b->path, node_info->interfaces[0], &vtable, b, NULL, &err);
    if (!b->reg_id) {
        g_warning("kristall-appmenu: cannot export the menu bar: %s", err ? err->message : "?");
        g_clear_error(&err);
        g_hash_table_destroy(b->items);
        g_object_unref(b->toplevel);
        g_free(b->path);
        g_free(b);
        return;
    }
    g_object_set_qdata(G_OBJECT(menubar), q_bar, b);
    bars = g_slist_prepend(bars, b);
    g_signal_connect(menubar, "destroy", G_CALLBACK(bar_free), b);
    connect_shell(b, menubar);
    g_signal_connect_after(menubar, "map", G_CALLBACK(on_menubar_map), b);
    b->map_id = g_signal_connect_after(top, "map", G_CALLBACK(on_toplevel_map), b);
    b->unmap_id = g_signal_connect(top, "unmap", G_CALLBACK(on_toplevel_unmap), b);
    apply_collapse(b);
    if (gtk_widget_get_mapped(top))
        announce(b);
}

static gboolean on_realize(GSignalInvocationHint *hint, guint n, const GValue *params, gpointer data)
{
    (void)hint; (void)n; (void)data;
    GtkWidget *w = g_value_get_object(&params[0]);
    if (GTK_IS_MENU_BAR(w) && !g_object_get_qdata(G_OBJECT(w), q_bar))
        track(w);
    return TRUE; // stay connected
}

// GtkApplicationWindow hides its menu bar when the shell says it shows it (gtk-shell-shows-menubar,
// set in settings.ini by Plasma's gmenudbusmenuproxy for X11): keep it in the window, exported here
static void keep_menubar_setting(GtkSettings *settings)
{
    gboolean shows = FALSE;
    g_object_get(settings, "gtk-shell-shows-menubar", &shows, NULL);
    if (shows)
        g_object_set(settings, "gtk-shell-shows-menubar", FALSE, NULL);
}

static void on_settings_notify(GObject *o, GParamSpec *p, gpointer data)
{
    (void)p; (void)data;
    keep_menubar_setting(GTK_SETTINGS(o));
}

// ------------------------------------------------------------------------------------------------

static void registry_global(void *data, struct wl_registry *reg, uint32_t name, const char *iface, uint32_t version)
{
    (void)data;
    if (strcmp(iface, org_kde_kwin_appmenu_manager_interface.name) == 0 && !manager)
        manager = wl_registry_bind(reg, name, &org_kde_kwin_appmenu_manager_interface, version < 2 ? version : 2);
}

static void registry_remove(void *data, struct wl_registry *reg, uint32_t name)
{
    (void)data; (void)reg; (void)name;
}

static const struct wl_registry_listener registry_listener = {registry_global, registry_remove};

static void setup(GdkDisplay *display)
{
    if (bus || !display || !GDK_IS_WAYLAND_DISPLAY(display))
        return; // X11 apps: unity-gtk-module and gmenudbusmenuproxy
    wl_dpy = gdk_wayland_display_get_wl_display(display);
    // our own queue: GDK's dispatching never sees our registry, and we can round-trip right here
    wl_queue = wl_display_create_queue(wl_dpy);
    struct wl_display *wrapper = wl_proxy_create_wrapper(wl_dpy);
    wl_proxy_set_queue((struct wl_proxy *)wrapper, wl_queue);
    struct wl_registry *registry = wl_display_get_registry(wrapper);
    wl_proxy_wrapper_destroy(wrapper);
    wl_registry_add_listener(registry, &registry_listener, NULL);
    wl_display_roundtrip_queue(wl_dpy, wl_queue);
    wl_registry_destroy(registry);
    if (!manager)
        return; // not KWin
    GError *err = NULL;
    bus = g_bus_get_sync(G_BUS_TYPE_SESSION, NULL, &err);
    if (!bus) {
        g_clear_error(&err);
        return;
    }
    node_info = g_dbus_node_info_new_for_xml(introspection_xml, NULL);
    q_bar = g_quark_from_static_string("kristall-appmenu-bar");
    q_id = g_quark_from_static_string("kristall-appmenu-id");
    q_watched = g_quark_from_static_string("kristall-appmenu-watched");

    // the initial state before the first window maps: is a menu bar showing app menus?
    GVariant *r = g_dbus_connection_call_sync(bus, "org.freedesktop.DBus", "/org/freedesktop/DBus", "org.freedesktop.DBus", "NameHasOwner",
                                              g_variant_new("(s)", VIEW_NAME), G_VARIANT_TYPE("(b)"), G_DBUS_CALL_FLAGS_NONE, 1000, NULL, NULL);
    gboolean present = FALSE;
    if (r) {
        g_variant_get(r, "(b)", &present);
        g_variant_unref(r);
    }
    collapsed = TRUE; // like Qt: exported at first; shown in the window after the grace period
    view_changed(present);
    g_bus_watch_name_on_connection(bus, VIEW_NAME, G_BUS_NAME_WATCHER_FLAGS_NONE, name_appeared, name_vanished, NULL, NULL);

    GtkWidgetClass *klass = g_type_class_ref(GTK_TYPE_MENU_BAR);
    orig_preferred_width = klass->get_preferred_width;
    orig_preferred_height = klass->get_preferred_height;
    orig_preferred_width_for_height = klass->get_preferred_width_for_height;
    orig_preferred_height_for_width = klass->get_preferred_height_for_width;
    klass->get_preferred_width = pw;
    klass->get_preferred_height = ph;
    klass->get_preferred_width_for_height = pwh;
    klass->get_preferred_height_for_width = phw;

    GtkSettings *settings = gtk_settings_get_for_screen(gdk_display_get_default_screen(display));
    keep_menubar_setting(settings);
    g_signal_connect(settings, "notify::gtk-shell-shows-menubar", G_CALLBACK(on_settings_notify), NULL);

    g_signal_add_emission_hook(g_signal_lookup("realize", GTK_TYPE_WIDGET), 0, on_realize, NULL, NULL);
}

static void display_opened(GdkDisplayManager *m, GdkDisplay *display, gpointer data)
{
    (void)m; (void)data;
    setup(display);
}

G_MODULE_EXPORT void gtk_module_init(gint *argc, gchar ***argv)
{
    (void)argc; (void)argv;
    GdkDisplay *display = gdk_display_get_default();
    if (display)
        setup(display);
    else
        g_signal_connect(gdk_display_manager_get(), "display-opened", G_CALLBACK(display_opened), NULL);
}
