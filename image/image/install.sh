#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Installer of the `image` component (component contract: docs/ARCHITECTURE.md §3).
# Runs as root during the OS image build, repository at $KRISTALL_CTX (read-only).
# Adds the base system pieces: identity, session, update tooling, app set, shared settings tool.
set -euo pipefail

CTX=${KRISTALL_CTX:-/ctx}
PREFIX=${KRISTALL_PREFIX:-/usr}
SRC=$CTX/image
ROOTFS=$SRC/rootfs

note() { printf '  [image] %s\n' "$*"; }
warn() { printf '::warning title=image component::%s\n' "$*"; }

list_entries() { # strip comments/blank lines from a list file
  sed -e 's/#.*//' -e 's/[[:space:]]*$//' -e '/^[[:space:]]*$/d' "$1"
}

# ----------------------------------------------------------------------------- packages
mapfile -t ADD < <(list_entries "$SRC/packages.list")
note "installing ${#ADD[@]} packages"
# The kernel is never touched: Kristall OS ships the base's Fedora-signed kernel.
dnf5 -y install --setopt=install_weak_deps=False \
  --exclude='kernel,kernel-core,kernel-modules,kernel-modules-core,kernel-modules-extra' \
  "${ADD[@]}"

mapfile -t REMOVE < <(list_entries "$SRC/packages-remove.list")
present=()
for p in "${REMOVE[@]}"; do
  rpm -q "$p" >/dev/null 2>&1 && present+=("$p")
done
if ((${#present[@]})); then
  note "removing: ${present[*]}"
  dnf5 -y remove --setopt=clean_requirements_on_remove=False "${present[@]}"
fi

# ----------------------------------------------------------------------------- files
# rootfs/usr/* goes to $KRISTALL_PREFIX, rootfs/etc/* to /etc.
note "installing files"
if [[ -d $ROOTFS/usr ]]; then
  mkdir -p "$PREFIX"
  cp -a --no-preserve=ownership "$ROOTFS/usr/." "$PREFIX/"
fi
if [[ -d $ROOTFS/etc ]]; then
  cp -a --no-preserve=ownership "$ROOTFS/etc/." /etc/
fi
chmod 0755 "$PREFIX"/bin/kristall-settings "$PREFIX"/bin/kristall-update "$PREFIX"/bin/kristall-apps \
  "$PREFIX"/libexec/kristall/plasma-setup-guard

install -Dm0644 "$SRC/apps/apps.json" "$PREFIX/share/kristall/apps/apps.json"
for doc in settings update apps; do
  if [[ -f $CTX/docs/contracts/$doc.md ]]; then
    install -Dm0644 "$CTX/docs/contracts/$doc.md" "$PREFIX/share/doc/kristall/contracts/$doc.md"
  fi
done

# Shared settings: the base defaults file (empty object) and the drop-in directory that every
# component contributes to (settings.d/NN-<component>.json).
mkdir -p "$PREFIX/share/kristall/defaults/settings.d" /etc/kristall/settings.d
[[ -f $PREFIX/share/kristall/defaults/settings.json ]] ||
  printf '{}\n' >"$PREFIX/share/kristall/defaults/settings.json"

# ----------------------------------------------------------------------------- identity
# Only display fields change. ID=fedora, VERSION_ID, VARIANT_ID=kinoite, PLATFORM_ID and CPE_NAME
# stay, because dnf, flatpak, toolbox/distrobox, Anaconda, rpm-ostree and bootc key off them.
OSR=/usr/lib/os-release
VERSION_ID=$(sed -n 's/^VERSION_ID=//p' "$OSR" | tr -d '"')
VERSION_ID=${VERSION_ID:-45}
IMAGE_VERSION=${KRISTALL_IMAGE_VERSION:-$VERSION_ID.$(date -u +%Y%m%d)}
REPO_URL=${KRISTALL_REPO_URL:-}
set_osr() { # key value
  local k=$1 v=$2
  if grep -q "^$k=" "$OSR"; then
    sed -i "s|^$k=.*|$k=\"$v\"|" "$OSR"
  else
    printf '%s="%s"\n' "$k" "$v" >>"$OSR"
  fi
}
set_osr NAME "Kristall OS"
set_osr PRETTY_NAME "Kristall OS $VERSION_ID"
set_osr VARIANT "Kristall OS"
set_osr IMAGE_ID "kristall-os"
set_osr IMAGE_VERSION "$IMAGE_VERSION"
# systemd-hostnamed uses this when the owner has not named the computer.
set_osr DEFAULT_HOSTNAME "kristall"
if [[ -n $REPO_URL ]]; then
  set_osr HOME_URL "$REPO_URL"
  set_osr DOCUMENTATION_URL "$REPO_URL/blob/main/docs/INSTALL.md"
  set_osr SUPPORT_URL "$REPO_URL/issues"
  set_osr BUG_REPORT_URL "$REPO_URL/issues"
fi
note "os-release: $(grep -E '^(PRETTY_NAME|IMAGE_VERSION)=' "$OSR" | tr '\n' ' ')"

install -d "$PREFIX/share/kristall/image"
cat >"$PREFIX/share/kristall/image/build-info.json" <<EOF
{
  "name": "Kristall OS",
  "version": "$IMAGE_VERSION",
  "fedora": "$VERSION_ID",
  "image_ref": "${KRISTALL_IMAGE_REF:-}",
  "git_sha": "${KRISTALL_GIT_SHA:-}",
  "built": "$(date -u +%Y-%m-%dT%H:%M:%SZ)"
}
EOF

# ----------------------------------------------------------------------------- session
# Plasma (Wayland) is the only session; plasma-login-manager stays the display manager.
shopt -s nullglob
for s in /usr/share/xsessions/*.desktop /usr/share/wayland-sessions/*.desktop; do
  [[ $s == /usr/share/wayland-sessions/plasma.desktop ]] && continue
  note "removing extra session $s"
  rm -f "$s"
done
shopt -u nullglob
[[ -f /usr/share/wayland-sessions/plasma.desktop ]] || {
  echo "::error::Plasma Wayland session file is missing from the base image" >&2
  exit 1
}
if [[ ! -f /usr/lib/systemd/system/plasmalogin.service ]]; then
  warn "plasmalogin.service not found; the base's display manager changed (check the theme component)"
fi

# First boot: KDE's Plasma Setup creates the owner's account (language, keyboard, Wi-Fi, account)
# and logs them straight in; the Setup Assistant (setup component) takes over from there.
if [[ -f /usr/lib/systemd/system/plasma-setup.service ]]; then
  systemctl enable plasma-setup.service
else
  echo "::error::plasma-setup is missing from the base; the owner would have no way to create an account" >&2
  exit 1
fi
systemctl enable kristall-plasma-setup-guard.service

# ----------------------------------------------------------------------------- updates
systemctl enable kristall-update.timer kristall-update-refresh.service kristall-apps-provision.timer
for t in rpm-ostreed-automatic.timer flatpak-system-update.timer uupd.timer; do
  systemctl disable "$t" 2>/dev/null || true
done
# bootc's upstream timer reboots without asking: make sure it can never be switched on.
systemctl mask bootc-fetch-apply-updates.timer bootc-fetch-apply-updates.service 2>/dev/null || true
systemctl --global enable kristall-update-notify.path kristall-update-notify.service

# ----------------------------------------------------------------------------- apps
# Hide (not remove) desktop entries that would confuse the owner.
mapfile -t HIDE < <(list_entries "$SRC/hidden-apps.list")
hidden=0
for id in "${HIDE[@]}"; do
  f=/usr/share/applications/$id
  [[ -f $f ]] || continue
  if grep -q '^NoDisplay=' "$f"; then
    sed -i '0,/^NoDisplay=.*/s//NoDisplay=true/' "$f"
  else
    sed -i '0,/^\[Desktop Entry\]/s//[Desktop Entry]\nNoDisplay=true/' "$f"
  fi
  hidden=$((hidden + 1))
done
note "hid $hidden desktop entries"
command -v update-desktop-database >/dev/null && update-desktop-database -q /usr/share/applications || true

# Firefox: make sure hardware video decoding (VA-API on Intel) is used.
for d in /usr/lib64/firefox/browser/defaults/preferences /usr/lib/firefox/browser/defaults/preferences; do
  if [[ -d $d ]]; then
    cat >"$d/kristall-default-prefs.js" <<'EOF'
// Kristall OS: hardware video decoding (VA-API) on Intel graphics.
pref("media.hardware-video-decoding.enabled", true);
pref("media.ffmpeg.vaapi.enabled", true);
// Firefox in the system language from the first start (firefox-langpacks), without its
// "Firefox speaks your language — switch?" question (integration walkthrough).
pref("intl.locale.requested", "");
EOF
  fi
done

# Sanity: the tools must run with the image's Python.
"$PREFIX/bin/kristall-settings" --version >/dev/null
"$PREFIX/bin/kristall-apps" validate "$PREFIX/share/kristall/apps/apps.json"
"$PREFIX/bin/kristall-update" --help >/dev/null

note "done"
