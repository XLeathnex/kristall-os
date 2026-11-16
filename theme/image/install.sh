#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall OS image build step for the theme component (component contract, ARCHITECTURE.md §3).
# Runs as root with the repository at /ctx (read-only), cwd = theme/. Installs under
# $KRISTALL_PREFIX (default /usr) and system defaults under /etc; every config file other
# components also write is merged key by key, never replaced. Idempotent.
#
# Test/staging knobs (used by theme/tests, never by the image build):
#   KRISTALL_SYSCONFDIR=DIR         write "/etc" files below DIR instead of /etc
#   KRISTALL_THEME_SKIP_PACKAGES=1  no dnf (packages are already there or not needed)
#   KRISTALL_THEME_DECORATION_SO=F  use this prebuilt decoration plugin instead of building it
#   KRISTALL_THEME_SKIP_INITRAMFS=1 leave the initramfs alone (default when not running as root
#                                   in a container with a kernel)
#   KRISTALL_THEME_PLYMOUTH=0       keep the stock boot splash
set -euo pipefail

prefix="${KRISTALL_PREFIX:-/usr}"
etc="${KRISTALL_SYSCONFDIR:-/etc}"
here="$(cd "$(dirname "$0")/.." && pwd)"           # theme/
ctx="${KRISTALL_CTX:-$(cd "$here/.." && pwd)}"
lib="$prefix/lib/kristall/theme"
share="$prefix/share"
work="$(mktemp -d /tmp/kristall-theme.XXXXXX)"
trap 'rm -rf "$work"' EXIT
log() { echo "[kristall-theme] $*"; }
warn() { echo "[kristall-theme] WARNING: $*" >&2; }

# ------------------------------------------------------------------ packages
# runtime: fonts, GTK theme base, GTK app-menu module, Python GObject for the service, tools
runtime=(rsms-inter-fonts jetbrains-mono-fonts-all google-noto-color-emoji-fonts adw-gtk3-theme
         python3-gobject-base glib2 kde-gtk-config plymouth-plugin-two-step plymouth-scripts
         unity-gtk3-module xdg-desktop-portal-gtk)
build=(gcc-c++ cmake ninja-build extra-cmake-modules kdecoration-devel qt6-qtbase-devel
       kf6-kcoreaddons-devel python3-numpy python3-pillow gtk3-devel)
added=()
if [[ ${KRISTALL_THEME_SKIP_PACKAGES:-0} != 1 ]]; then
    want=()
    for p in "${runtime[@]}"; do rpm -q "$p" >/dev/null 2>&1 || want+=("$p"); done
    if ((${#want[@]})); then
        # install one by one so a renamed package never fails the image; report what is missing
        for p in "${want[@]}"; do
            dnf5 install -y --setopt=install_weak_deps=False "$p" >/dev/null 2>&1 || warn "runtime package not available: $p"
        done
    fi
    for p in "${build[@]}"; do rpm -q "$p" >/dev/null 2>&1 || added+=("$p"); done
    if ((${#added[@]})); then
        log "build dependencies: ${added[*]}"
        dnf5 install -y --setopt=install_weak_deps=False "${added[@]}"
    fi
fi

# ------------------------------------------------------------------ generated files
log "generating colour schemes, wallpapers, pointer, boot splash images, sounds"
python3 "$here/tools/gen-theme.py" "$work/gen" --assets
gen="$work/gen"

# ------------------------------------------------------------------ window decoration
plugdir="$prefix/lib64/qt6/plugins"
[[ -d $prefix/lib64 ]] || plugdir="$prefix/lib/qt6/plugins"
install -d "$plugdir/org.kde.kdecoration3"
if [[ -n ${KRISTALL_THEME_DECORATION_SO:-} ]]; then
    install -m 0755 "$KRISTALL_THEME_DECORATION_SO" "$plugdir/org.kde.kdecoration3/org.kristall.decoration.so"
else
    log "building the window decoration against KDecoration $(rpm -q --qf '%{VERSION}' kdecoration 2>/dev/null || echo '?')"
    if cmake -S "$here/decoration" -B "$work/deco" -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX="$prefix" >"$work/deco.log" 2>&1 \
        && ninja -C "$work/deco" >>"$work/deco.log" 2>&1; then
        install -m 0755 "$work/deco/bin/org.kristall.decoration.so" "$plugdir/org.kde.kdecoration3/org.kristall.decoration.so"
    else
        # KWin falls back to Breeze when the configured decoration does not exist
        tail -30 "$work/deco.log" >&2
        warn "decoration did not build; windows keep the Breeze decoration"
        [[ ${KRISTALL_STRICT:-0} == 1 ]] && exit 1
    fi
fi

# ------------------------------------------------------------------ GTK 3 live reload module
gtkmods="$prefix/lib64/gtk-3.0/modules"
[[ -d $prefix/lib64 ]] || gtkmods="$prefix/lib/gtk-3.0/modules"
install -d "$gtkmods"
# shellcheck disable=SC2046
if gcc -shared -fPIC -O2 -Wall -o "$work/libkristall-reload-gtk-module.so" "$here/gtk-module/kristall-reload.c" \
        $(pkg-config --cflags --libs gtk+-3.0) 2>"$work/gtkmod.log"; then
    install -m 0755 "$work/libkristall-reload-gtk-module.so" "$gtkmods/"
else
    cat "$work/gtkmod.log" >&2
    warn "GTK 3 reload module did not build; running GTK 3 apps switch light/dark at their next start"
fi

# ------------------------------------------------------------------ data
install -d "$lib" "$share/kristall/theme" "$share/color-schemes" "$share/konsole" "$share/wallpapers" "$share/icons" \
    "$share/sounds" "$share/plymouth/themes/kristall"
cp -a "$gen/share/color-schemes/." "$share/color-schemes/"
cp -a "$gen/share/konsole/." "$share/konsole/"
cp -a "$gen/share/kristall/theme/." "$share/kristall/theme/"
for d in "$gen"/share/wallpapers/*; do rm -rf "$share/wallpapers/$(basename "$d")"; cp -a "$d" "$share/wallpapers/"; done
rm -rf "$share/icons/Kristall" "$share/sounds/kristall"
cp -a "$gen/share/icons/Kristall" "$share/icons/"
cp -a "$gen/share/sounds/kristall" "$share/sounds/"
cp -a "$gen/share/plymouth/themes/kristall/." "$share/plymouth/themes/kristall/"
install -m 0644 "$here/plymouth/kristall.plymouth" "$share/plymouth/themes/kristall/kristall.plymouth"

# the appearance service and the libraries it shares with the build
install -m 0755 "$here/service/kristall-appearance" "$lib/kristall-appearance"
install -m 0644 "$here/tools/kristall_colors.py" "$here/tools/kini.py" "$lib/"
install -d "$prefix/bin"
ln -sfn "$lib/kristall-appearance" "$prefix/bin/kristall-appearance"
install -d "$prefix/lib/systemd/user" "$prefix/lib/systemd/system" "$prefix/lib/systemd/user-preset" "$prefix/lib/systemd/system-preset"
install -m 0644 "$here/config/systemd/kristall-appearance.service" "$prefix/lib/systemd/user/"
install -m 0644 "$here/config/systemd/kristall-theme-flatpak.service" "$prefix/lib/systemd/system/"
install -m 0644 "$here/config/systemd/50-kristall-theme.user.preset" "$prefix/lib/systemd/user-preset/50-kristall-theme.preset"
install -m 0644 "$here/config/systemd/50-kristall-theme.system.preset" "$prefix/lib/systemd/system-preset/50-kristall-theme.preset"

# ------------------------------------------------------------------ Plasma look-and-feel
# shell-core's package org.kristall.desktop: we add defaults and the splash, never its layouts
lnf="$share/plasma/look-and-feel"
install -d "$lnf/org.kristall.desktop/contents/splash/images"
install -m 0644 "$here/plasma/look-and-feel/org.kristall.desktop/contents/defaults" "$lnf/org.kristall.desktop/contents/defaults"
install -m 0644 "$here/plasma/look-and-feel/org.kristall.desktop/contents/splash/Splash.qml" "$lnf/org.kristall.desktop/contents/splash/"
cp -a "$gen/share/plasma/look-and-feel/org.kristall.desktop/contents/splash/images/." "$lnf/org.kristall.desktop/contents/splash/images/"
# the dark twin used by Plasma's automatic light/dark switching; it carries the same layout file
# as shell-core's package (copied, so the panel-less layout stays identical) and the same splash
rm -rf "$lnf/org.kristall.desktop.dark"
install -d "$lnf/org.kristall.desktop.dark/contents"
install -m 0644 "$here/plasma/look-and-feel/org.kristall.desktop.dark/metadata.json" "$lnf/org.kristall.desktop.dark/"
install -m 0644 "$here/plasma/look-and-feel/org.kristall.desktop.dark/contents/defaults" "$lnf/org.kristall.desktop.dark/contents/"
if [[ -d $lnf/org.kristall.desktop/contents/layouts ]]; then
    cp -a "$lnf/org.kristall.desktop/contents/layouts" "$lnf/org.kristall.desktop.dark/contents/"
else
    warn "shell-core's look-and-feel package has no layouts (shell not installed yet?)"
fi
ln -sfn ../../org.kristall.desktop/contents/splash "$lnf/org.kristall.desktop.dark/contents/splash"

# ------------------------------------------------------------------ lock screen and log-out dialog
overlay="$share/kristall/theme/overlay/plasma/shells/org.kde.plasma.desktop"
stockshell="$share/plasma/shells/org.kde.plasma.desktop"
[[ -d $stockshell ]] || stockshell=/usr/share/plasma/shells/org.kde.plasma.desktop
if [[ -d $stockshell ]]; then
    python3 "$here/plasma/shell-overlay/build-overlay.py" "$stockshell" "$overlay" "$here/plasma/shell-overlay" \
        "$gen/share/kristall/theme/marks" | sed 's/^/[kristall-theme] overlay: /'
    install -d "$prefix/lib/environment.d"
    install -m 0644 "$here/config/environment.d.conf" "$prefix/lib/environment.d/50-kristall-theme.conf"
else
    warn "plasma-desktop's shell package not found; lock screen and log-out dialog stay stock"
fi

# ------------------------------------------------------------------ login screen
install -d "$prefix/lib/plasmalogin/plasmalogin.conf.d"
install -m 0644 "$here/plasma/plasmalogin/50-kristall.conf" "$prefix/lib/plasmalogin/plasmalogin.conf.d/50-kristall.conf"

# ------------------------------------------------------------------ system-wide defaults (merged)
install -d "$etc/xdg"
for f in "$here"/config/xdg/*; do
    name="$(basename "$f")"
    frags=("$f")
    [[ -f $gen/xdg-generated/$name ]] && frags+=("$gen/xdg-generated/$name")
    python3 "$here/tools/kini.py" merge "$etc/xdg/$name" "${frags[@]}"
done
install -d "$etc/gtk-3.0" "$etc/gtk-4.0"
for v in 3.0 4.0; do
    python3 "$here/tools/kini.py" merge "$etc/gtk-$v/settings.ini" "$here/config/gtk/settings.ini"
done
# GNOME settings defaults (GTK on Wayland and the GTK portal read these)
install -d "$share/glib-2.0/schemas"
install -m 0644 "$here/config/gtk/90-kristall.gschema.override" "$share/glib-2.0/schemas/90-kristall.gschema.override"
if command -v glib-compile-schemas >/dev/null && [[ -f $share/glib-2.0/schemas/org.gnome.desktop.interface.gschema.xml ]]; then
    glib-compile-schemas "$share/glib-2.0/schemas" || warn "glib-compile-schemas failed; GNOME setting defaults not applied"
fi
# fonts: our rules as a conf.avail file, enabled by the usual conf.d symlink
install -d "$share/fontconfig/conf.avail" "$etc/fonts/conf.d"
install -m 0644 "$here/config/fontconfig/56-kristall.conf" "$share/fontconfig/conf.avail/56-kristall.conf"
ln -sfn "$share/fontconfig/conf.avail/56-kristall.conf" "$etc/fonts/conf.d/56-kristall.conf"
# Firefox: supported default preferences next to the image component's own file
for d in "$prefix/lib64/firefox/browser/defaults/preferences" "$prefix/lib/firefox/browser/defaults/preferences"; do
    if [[ -d $d ]]; then install -m 0644 "$here/config/firefox/kristall-theme-prefs.js" "$d/"; fi
done
# kernel arguments for a text-free boot (bootc applies kargs.d on install and on update)
install -d "$prefix/lib/bootc/kargs.d"
install -m 0644 "$here/config/kargs.toml" "$prefix/lib/bootc/kargs.d/50-kristall-theme.toml"

# ------------------------------------------------------------------ documentation
install -d "$share/doc/kristall/contracts"
[[ -f $ctx/docs/contracts/theme.md ]] && install -m 0644 "$ctx/docs/contracts/theme.md" "$share/doc/kristall/contracts/"
install -m 0644 "$here/ASSETS.md" "$share/kristall/theme/ASSETS.md"

# ------------------------------------------------------------------ boot splash (initramfs)
if [[ ${KRISTALL_THEME_PLYMOUTH:-1} == 1 && ${KRISTALL_THEME_SKIP_INITRAMFS:-0} != 1 && $etc == /etc ]]; then
    bash "$here/image/plymouth.sh" || warn "boot splash left stock (see messages above)"
else
    log "boot splash: initramfs not touched (staging or disabled)"
fi

# ------------------------------------------------------------------ checks
python3 "$here/tools/kini.py" check "$etc/xdg/kdeglobals" "$etc/xdg/kwinrc" "$share/color-schemes/KristallLight.colors" \
    "$share/color-schemes/KristallDark.colors"
test -f "$share/wallpapers/Kristall/contents/images/3840x2400.jpg"
test -f "$share/icons/Kristall/cursors/default"
python3 -c "import ast,sys; ast.parse(open(sys.argv[1]).read())" "$lib/kristall-appearance"

if ((${#added[@]})); then
    log "removing build dependencies"
    dnf5 remove -y "${added[@]}" >/dev/null || warn "could not remove build dependencies"
fi
log "installed"
