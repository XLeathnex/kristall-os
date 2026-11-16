#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Turns the Kristall OS image into the installer's live system (see image/iso/Containerfile).
# Runs as root inside `podman build --cap-add sys_admin`, image/iso mounted at /ctx-iso.
#   KRISTALL_IMAGE_REF       registry reference installed systems update from (no tag), required
#   KRISTALL_IMAGE_TAG       tag they follow (default: latest)
#   KRISTALL_PAYLOAD_DIGEST  exact digest to install (default: what the tag points to now)
set -euo pipefail

ISO=${KRISTALL_ISO_CTX:-/ctx-iso}
REF=${KRISTALL_IMAGE_REF:?KRISTALL_IMAGE_REF must name the published image, e.g. ghcr.io/owner/kristall-os}
TAG=${KRISTALL_IMAGE_TAG:-latest}
DIGEST=${KRISTALL_PAYLOAD_DIGEST:-}
PAYLOAD_DIR=/var/lib/kristall-installer/payload
PAYLOAD=$PAYLOAD_DIR:kristall
LABEL=$(sed -n 's/^label:[[:space:]]*//p' "$ISO/iso.yaml")

step() { printf '\n==> %s\n' "$*"; }
fail() {
  printf '::error title=Kristall installer ISO::%s\n' "$*" >&2
  exit 1
}

[[ $LABEL == KRISTALL-OS ]] || fail "iso.yaml label ($LABEL) and the boot entries must agree on KRISTALL-OS"
mkdir -p "$(realpath /root)"

step "Installer packages"
mapfile -t PKGS < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$ISO/packages.list")
dnf5 -y install --setopt=install_weak_deps=False \
  --exclude='kernel,kernel-core,kernel-modules,kernel-modules-core,kernel-modules-extra' "${PKGS[@]}"

step "Default apps that travel on the USB stick (free software only)"
# bubblewrap (used by flatpak's triggers) needs to write /proc/sys/user/max_user_namespaces.
mount -o remount,rw /proc/sys 2>/dev/null || true
flatpak remote-add --system --if-not-exists flathub /etc/flatpak/remotes.d/flathub.flatpakrepo
mapfile -t EMBED < <(kristall-apps list --embed --flatpak-ids)
((${#EMBED[@]})) || fail "the app manifest lists no Flatpaks to embed"
flatpak install --system -y --noninteractive flathub "${EMBED[@]}"
# Same per-app overrides the first-boot provisioning would apply.
kristall-apps list --embed | python3 -c '
import json, subprocess, sys
for a in json.load(sys.stdin)["apps"]:
    ov = a["flatpak"].get("overrides") or []
    if ov:
        subprocess.run(["flatpak", "override", "--system"] + ov + [a["flatpak"]["id"]], check=True)
'
flatpak list --system --app --columns=application,version

step "Offline copy of the OS image to install"
src="docker://$REF:$TAG"
[[ -n $DIGEST ]] && src="docker://$REF@$DIGEST"
rm -rf "$PAYLOAD_DIR"
mkdir -p "$(dirname "$PAYLOAD_DIR")"
skopeo copy --retry-times 3 "$src" "oci:$PAYLOAD" ||
  fail "could not download $src. Is the package public? (GitHub → your profile → Packages → kristall-os → Package settings → Change visibility → Public)"
du -sh "$PAYLOAD_DIR"

step "Live boot initramfs"
mapfile -t KVERS < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n')
((${#KVERS[@]} == 1)) || fail "expected one kernel, found: ${KVERS[*]}"
kver=${KVERS[0]}
DRACUT_NO_XATTR=1 dracut --force --zstd --reproducible --no-hostonly \
  --add "dmsquash-live dmsquash-live-autooverlay" \
  "/usr/lib/modules/$kver/initramfs.img" "$kver"

step "UEFI boot files (Fedora-signed shim and GRUB; Secure Boot keeps working)"
mkdir -p /boot/efi
for d in /usr/lib/efi/*/*/EFI; do
  [[ -d $d ]] && cp -a "$d" /boot/efi/
done
vendor_dir=/boot/efi/EFI/fedora
for f in shimx64.efi mmx64.efi gcdx64.efi; do
  if [[ ! -f $vendor_dir/$f ]]; then
    found=$(find /usr/lib/efi /boot -name "$f" -print -quit 2>/dev/null || true)
    [[ -n $found ]] || fail "$f is missing; the ISO could not start with Secure Boot"
    install -Dm0644 "$found" "$vendor_dir/$f"
  fi
done
ls -la "$vendor_dir"

step "Live session"
sed -i 's/^livesys_session=.*/livesys_session=kde/' /etc/sysconfig/livesys
systemctl enable livesys.service livesys-late.service
# Updates, app provisioning and first-run wizards never run from the USB stick.
for u in kristall-update.timer kristall-apps-provision.timer rpm-ostree-countme.timer \
  flatpak-system-update.timer plasma-setup.service kristall-plasma-setup-guard.service; do
  systemctl disable "$u" 2>/dev/null || true
done
systemctl --global disable kristall-update-notify.path kristall-update-notify.service 2>/dev/null || true
mkdir -p /etc/kristall
printf 'This is the Kristall OS installer live system.\n' >/etc/kristall/live
# The installer opens by itself after the live desktop starts.
install -Dm0644 "$ISO/live/kristall-installer.desktop" /etc/xdg/autostart/kristall-installer.desktop
install -Dm0644 "$ISO/live/kristall-installer.desktop" /usr/share/applications/kristall-installer.desktop
# ostree needs room in /var/tmp; on a live system / is an overlay on a small tmpfs.
rm -rf /var/tmp && mkdir -p /var/tmp
cat >/etc/systemd/system/var-tmp.mount <<'EOF'
[Unit]
Description=Larger /var/tmp for installing from the live system

[Mount]
What=tmpfs
Where=/var/tmp
Type=tmpfs
Options=size=50%%,nr_inodes=1m

[Install]
WantedBy=local-fs.target
EOF
systemctl enable var-tmp.mount
# No sleeping while the installer runs.
mkdir -p /etc/xdg
cat >/etc/xdg/powerdevilrc <<'EOF'
[AC][SuspendAndShutdown]
AutoSuspendAction=0
[Battery][SuspendAndShutdown]
AutoSuspendAction=0
[LowBattery][SuspendAndShutdown]
AutoSuspendAction=0
EOF

step "Anaconda"
install -Dm0644 "$ISO/anaconda/90-kristall.conf" /etc/anaconda/conf.d/90-kristall.conf
ks=/usr/share/anaconda/interactive-defaults.ks
[[ -f $ks ]] || fail "$ks not found (anaconda-live missing?)"
sed -e "s|@IMAGE_REF@|$REF|g" -e "s|@IMAGE_TAG@|$TAG|g" -e "s|@PAYLOAD@|$PAYLOAD|g" \
  "$ISO/anaconda/kristall.ks.in" >>"$ks"
grep -n 'ostreecontainer\|bootc switch' "$ks"

step "ISO description for Titanoboa"
install -Dm0644 "$ISO/iso.yaml" /usr/lib/bootc-image-builder/iso.yaml

dnf5 clean all >/dev/null 2>&1 || true
step "Live system ready"
