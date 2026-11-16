#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Kristall boot splash: select the "kristall" Plymouth theme and rebuild the image's initramfs the
# way Universal Blue images do (Bazzite/Bluefin/Aurora build_files: dracut --no-hostonly --kver K
# --reproducible --add ostree -f /usr/lib/modules/K/initramfs.img). An unbootable image is the worst
# outcome, so the new initramfs is built to a temporary file and only replaces the original after
# it passes every check below; otherwise the original initramfs and the stock theme stay and this
# script exits 1 (the caller logs it and the build continues: stock splash, never a broken boot).
#
# Checks: exactly one kernel in /usr/lib/modules; the original initramfs exists; the new one
# lists our theme and the two-step plugin, keeps every dracut module the original had (ostree,
# systemd, …), keeps ≥ 98 % of the original's kernel modules, and is a valid, non-trivial cpio.
set -euo pipefail
log() { echo "[kristall-theme] plymouth: $*"; }
fail() { echo "[kristall-theme] plymouth: $*" >&2; exit 1; }

theme=kristall
conf=/etc/plymouth/plymouthd.conf
command -v plymouth-set-default-theme >/dev/null || fail "plymouth-set-default-theme missing"
command -v dracut >/dev/null || fail "dracut missing"
command -v lsinitrd >/dev/null || fail "lsinitrd missing"
[[ -f /usr/share/plymouth/themes/$theme/$theme.plymouth ]] || fail "theme not installed"

mapfile -t kernels < <(find /usr/lib/modules -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
((${#kernels[@]} == 1)) || fail "expected exactly one kernel, found ${#kernels[@]} (${kernels[*]:-none})"
kver="${kernels[0]}"
img="/usr/lib/modules/$kver/initramfs.img"
[[ -s $img ]] || fail "no initramfs at $img"
[[ -f /usr/lib/modules/$kver/vmlinuz ]] || fail "no kernel image for $kver"

old_theme="$(plymouth-set-default-theme 2>/dev/null || true)"
old_conf=""
[[ -f $conf ]] && old_conf="$(cat "$conf")"
restore() {
    if [[ -n $old_conf ]]; then printf '%s\n' "$old_conf" >"$conf"; else rm -f "$conf"; fi
    log "restored theme '${old_theme:-default}'"
}

# from here on any unexpected error restores the previous theme before exiting
trap 'echo "[kristall-theme] plymouth: unexpected error" >&2; restore; exit 1' ERR
plymouth-set-default-theme "$theme"   # writes /etc/plymouth/plymouthd.conf (no -R: we run dracut ourselves)
[[ "$(plymouth-set-default-theme)" == "$theme" ]] || { restore; fail "theme selection did not take"; }

tmp="$(mktemp /var/tmp/kristall-initramfs.XXXXXX)"
trap 'rm -f "$tmp"' EXIT
log "rebuilding initramfs for $kver"
if ! DRACUT_NO_XATTR=1 dracut --no-hostonly --kver "$kver" --reproducible --add ostree --zstd -f "$tmp" >/var/tmp/kristall-dracut.log 2>&1; then
    tail -20 /var/tmp/kristall-dracut.log >&2
    restore
    fail "dracut failed"
fi

# dracut module names only (lsinitrd --mod also prints an "Image: … size" header)
mods() { { lsinitrd --mod "$1" 2>/dev/null || true; } | grep -E '^[A-Za-z0-9_.-]+$' | sort -u || true; }
old_mods="$(mods "$img")"
new_mods="$(mods "$tmp")"
new_list="$({ lsinitrd "$tmp" 2>/dev/null || true; })"
old_ko=$({ lsinitrd "$img" 2>/dev/null || true; } | grep -c '\.ko' || true)
new_ko=$(printf '%s\n' "$new_list" | grep -c '\.ko' || true)
problems=()
grep -q "plymouth/themes/$theme/$theme.plymouth" <<<"$new_list" || problems+=("theme file missing")
grep -q "plymouth/themes/$theme/watermark.png" <<<"$new_list" || problems+=("theme images missing")
grep -q "plymouth/two-step.so" <<<"$new_list" || problems+=("two-step plugin missing")
grep -qx "ostree" <<<"$new_mods" || problems+=("dracut module ostree missing")
missing_mods="$(comm -23 <(printf '%s\n' "$old_mods") <(printf '%s\n' "$new_mods") | grep -v '^$' || true)"
[[ -z $missing_mods ]] || problems+=("dracut modules lost: $(echo $missing_mods)")
if ((old_ko > 0)) && ((new_ko * 100 < old_ko * 98)); then problems+=("kernel modules: $new_ko vs $old_ko before"); fi
(($(stat -c %s "$tmp") > 10 * 1024 * 1024)) || problems+=("suspiciously small ($(stat -c %s "$tmp") bytes)")
[[ -n $new_mods ]] || problems+=("no dracut modules listed (not an initramfs?)")
if ((${#problems[@]})); then
    printf '  - %s\n' "${problems[@]}" >&2
    restore
    fail "new initramfs rejected; keeping the original"
fi

trap - ERR
install -m 0600 "$tmp" "$img"
log "initramfs updated ($(stat -c %s "$img") bytes, $new_ko kernel modules, theme $theme)"
