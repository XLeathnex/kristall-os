// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall OS: Firefox's chrome sits in the desktop with supported preferences only (no userChrome).
// System theme (follows light/dark through the desktop portal), tabs in the title bar with the
// window buttons on the left (order from the GTK decoration layout), compact density,
// overlay scrollbars, the KDE file dialog through the portal.
pref("browser.tabs.inTitlebar", 1);
pref("browser.compactmode.show", true);
pref("browser.uidensity", 1);
pref("widget.gtk.overlay-scrollbars.enabled", true);
pref("widget.use-xdg-desktop-portal.file-picker", 1);
pref("widget.use-xdg-desktop-portal.mime-handler", 1);
pref("layout.css.prefers-color-scheme.content-override", 2);
pref("browser.theme.toolbar-theme", 2);
pref("browser.theme.content-theme", 2);
