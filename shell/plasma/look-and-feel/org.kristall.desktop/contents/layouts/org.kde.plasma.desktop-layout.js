// SPDX-License-Identifier: GPL-3.0-or-later
// Kristall OS default Plasma layout (used for every new user, and when a user's layout is reset):
// only the desktop containment of each screen, with the image wallpaper. No panels — the menu bar,
// Dock, notifications and launcher are the Kristall shell (kristall-shell.service).
var all = desktops();
for (var i = 0; i < all.length; ++i) {
    all[i].wallpaperPlugin = "org.kde.image";
}
