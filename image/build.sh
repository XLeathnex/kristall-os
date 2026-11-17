#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Kristall OS image build orchestrator. Runs as root inside the Containerfile's single RUN step,
# with the repository mounted read-only at /ctx:
#
#   prepare    -> record facts about the base (kernel, presets) for the later checks
#   components -> run <component>/image/install.sh for every entry of image/components.list
#   presets    -> apply the systemd presets that components added (system and --global)
#   finalize   -> verify kernel/Secure Boot, manifests, sessions; clean /var, /tmp; check /usr/local
#
# Environment:
#   KRISTALL_STRICT=1          a missing component fails the build (release builds in CI set it)
#   KRISTALL_PREFIX            passed through to installers (default /usr)
#   KRISTALL_CTX               repository root (default /ctx)
#   KRISTALL_COMPONENTS_LIST   default $KRISTALL_CTX/image/components.list
#   KRISTALL_BUILD_PHASES      comma list, default prepare,components,presets,finalize (tests use a subset)
#   KRISTALL_ROOT              prefix for filesystem checks (tests only; default empty = /)
#   KRISTALL_SYSTEMCTL         systemctl binary (tests only)
set -euo pipefail

CTX=${KRISTALL_CTX:-/ctx}
STRICT=${KRISTALL_STRICT:-0}
LIST=${KRISTALL_COMPONENTS_LIST:-$CTX/image/components.list}
PHASES=${KRISTALL_BUILD_PHASES:-prepare,components,presets,finalize}
ROOT=${KRISTALL_ROOT:-}
SYSTEMCTL=${KRISTALL_SYSTEMCTL:-systemctl}
export KRISTALL_PREFIX=${KRISTALL_PREFIX:-/usr}
export KRISTALL_CTX=$CTX KRISTALL_STRICT=$STRICT

# GitHub Actions turns these lines into annotations; elsewhere they are just readable text.
note() { printf '==> %s\n' "$*"; }
warn() { printf '::warning title=Kristall image build::%s\n' "$*"; }
fail() {
  printf '::error title=Kristall image build::%s\n' "$*" >&2
  exit 1
}
group() { printf '::group::%s\n' "$*"; }
endgroup() { printf '::endgroup::\n'; }

has_phase() { [[ ",$PHASES," == *",$1,"* ]]; }

# --------------------------------------------------------------------------- component list

read_components() {
  [[ -f $LIST ]] || fail "component list not found: $LIST"
  local line seen=" "
  COMPONENTS=()
  while IFS= read -r line || [[ -n $line ]]; do
    line=${line%%#*}
    line=${line//[[:space:]]/}
    [[ -z $line ]] && continue
    if [[ $line == /* || $line == *..* || ! $line =~ ^[A-Za-z0-9_./-]+$ ]]; then
      fail "invalid entry '$line' in $LIST (must be a repository-relative directory)"
    fi
    line=${line%/}
    [[ $seen == *" $line "* ]] && fail "component '$line' is listed twice in $LIST"
    seen+="$line "
    COMPONENTS+=("$line")
  done <"$LIST"
  ((${#COMPONENTS[@]} > 0)) || fail "$LIST lists no components"
}

# --------------------------------------------------------------------------- snapshots

count_entries() { # files below a directory (following a top-level symlink), 0 if absent
  local d=$1
  [[ -e $d ]] || {
    echo 0
    return
  }
  find -L "$d" -mindepth 1 2>/dev/null | wc -l
}

forbidden_count() {
  echo "$(($(count_entries "$ROOT/usr/local") + $(count_entries "$ROOT/opt")))"
}

declare -A PRESET_SUM=()
snapshot_presets() {
  local f
  for f in "$ROOT"/usr/lib/systemd/system-preset/*.preset "$ROOT"/usr/lib/systemd/user-preset/*.preset; do
    [[ -f $f ]] || continue
    PRESET_SUM[$f]=$(sha256sum "$f" | cut -d' ' -f1)
  done
}

# --------------------------------------------------------------------------- phases

phase_prepare() {
  group "Base image"
  if [[ -r $ROOT/usr/lib/os-release ]]; then
    grep -E '^(NAME|VERSION|ID|VARIANT_ID|VERSION_ID)=' "$ROOT/usr/lib/os-release" || true
  fi
  if command -v rpm >/dev/null && [[ -z $ROOT ]]; then
    rpm -q kernel-core kwin plasma-workspace plasma-login-manager bootc flatpak 2>/dev/null || true
  fi
  endgroup
  BASE_KERNELS=$({ find "$ROOT/usr/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' 2>/dev/null || true; } | sort | tr '\n' ' ')
  BASE_FORBIDDEN=$(forbidden_count)
  snapshot_presets
  mkdir -p "$ROOT/usr/share/kristall"
}

phase_components() {
  local c dir script start rc before after
  local -a skipped=() ran=()
  read_components
  note "Components, in order: ${COMPONENTS[*]}"
  for c in "${COMPONENTS[@]}"; do
    dir=$CTX/$c
    script=$dir/image/install.sh
    if [[ ! -d $dir || ! -f $script ]]; then
      local why="directory $c/ does not exist"
      [[ -d $dir ]] && why="$c/image/install.sh does not exist"
      if [[ $STRICT == 1 ]]; then
        fail "component '$c' is listed in image/components.list but $why. Release builds (KRISTALL_STRICT=1) need every component."
      fi
      warn "SKIPPING component '$c': $why. The image is built without it."
      skipped+=("$c")
      continue
    fi
    group "Component $c"
    before=$(forbidden_count)
    start=$SECONDS
    set +e
    (cd "$dir" && KRISTALL_COMPONENT=$c bash "$script")
    rc=$?
    set -e
    endgroup
    if ((rc != 0)); then
      fail "component '$c' failed: $c/image/install.sh exited with status $rc (see the log group above)"
    fi
    after=$(forbidden_count)
    if ((after != before)); then
      local msg="component '$c' wrote into /usr/local or /opt; those are not part of the image (use /usr)"
      [[ $STRICT == 1 ]] && fail "$msg"
      warn "$msg"
    fi
    note "component $c finished in $((SECONDS - start))s"
    ran+=("$c")
  done
  note "Built components: ${ran[*]:-none}"
  if ((${#skipped[@]})); then
    warn "Skipped components (not in the repository yet): ${skipped[*]}"
  fi
}

# Apply presets for every unit named in a preset file that appeared since `prepare`.
# (systemctl preset-all would also re-decide every base unit, which we must not do.)
preset_units() { # file -> unit names/globs from enable/disable lines
  awk '$1 == "enable" || $1 == "disable" { print $2 }' "$1"
}

expand_units() { # dir glob... -> existing unit file names
  local dir=$1 g f
  shift
  for g in "$@"; do
    if [[ $g == *[*?[]* ]]; then
      for f in "$dir"/$g; do [[ -e $f ]] && basename "$f"; done
    else
      echo "$g"
    fi
  done
}

phase_presets() {
  local scope f dir unitdir
  local -a units
  for scope in system user; do
    dir=$ROOT/usr/lib/systemd/$scope-preset
    unitdir=$ROOT/usr/lib/systemd/$scope
    units=()
    for f in "$dir"/*.preset; do
      [[ -f $f ]] || continue
      # Only preset files that components added. Base files changed by a package update
      # (e.g. systemd's) are left alone: re-applying them could undo the base's choices.
      [[ -n ${PRESET_SUM[$f]:-} ]] && continue
      # Files installed by an RPM had their presets applied by the package's scriptlets already.
      if [[ -z $ROOT ]] && command -v rpm >/dev/null && rpm -qf "$f" >/dev/null 2>&1; then
        continue
      fi
      local -a names=()
      mapfile -t names < <(preset_units "$f")
      ((${#names[@]})) || continue
      mapfile -t -O "${#units[@]}" units < <(expand_units "$unitdir" "${names[@]}")
    done
    ((${#units[@]})) || continue
    mapfile -t units < <(printf '%s\n' "${units[@]}" | sort -u)
    note "Applying $scope presets for: ${units[*]}"
    local -a args=(preset)
    [[ $scope == user ]] && args=(--global preset)
    [[ -n $ROOT ]] && args=(--root="$ROOT" "${args[@]}")
    local u
    for u in "${units[@]}"; do
      if [[ ! -e $unitdir/$u && ! -e $ROOT/etc/systemd/$scope/$u ]]; then
        note "preset for $u: no such $scope unit in the image, nothing to do"
        continue
      fi
      if ! "$SYSTEMCTL" "${args[@]}" "$u"; then
        warn "could not apply the $scope preset for $u (does the unit have an [Install] section?)"
      fi
    done
  done
}

check_kernel() {
  local -a kernels
  mapfile -t kernels < <(find "$ROOT/usr/lib/modules" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort)
  ((${#kernels[@]} == 1)) || fail "expected exactly one kernel in /usr/lib/modules, found: ${kernels[*]:-none}"
  [[ "${kernels[*]} " == "$BASE_KERNELS" ]] ||
    fail "the kernel changed during the build (base: $BASE_KERNELS, now: ${kernels[*]}). Kristall OS ships the base's Fedora kernel unchanged."
  local kver=${kernels[0]} vmlinuz=$ROOT/usr/lib/modules/${kernels[0]}/vmlinuz
  [[ -f $vmlinuz ]] || fail "no vmlinuz for kernel $kver"
  # Secure Boot: shim trusts Fedora's signature on vmlinuz. Make sure it is there.
  python3 - "$vmlinuz" <<'PY' || fail "vmlinuz for $kver carries no Fedora Secure Boot signature; Secure Boot would refuse to start it"
import struct, sys
data = open(sys.argv[1], "rb").read()
pe = struct.unpack_from("<I", data, 0x3C)[0]
assert data[pe:pe + 4] == b"PE\0\0"
opt = pe + 24
magic = struct.unpack_from("<H", data, opt)[0]
dirs = opt + (96 if magic == 0x10B else 112)
off, size = struct.unpack_from("<II", data, dirs + 4 * 8)  # IMAGE_DIRECTORY_ENTRY_SECURITY
blob = data[off:off + size]
sys.exit(0 if size and b"Fedora Secure Boot" in blob else 1)
PY
  note "kernel $kver: Fedora Secure Boot signature present"
  if [[ -z $ROOT ]] && command -v rpm >/dev/null; then
    local extra
    # kmod-libs / kmod-devel are the module *tools* every Fedora base has, not modules; files of
    # unpackaged modules are caught by the "unowned" check below.
    extra=$(rpm -qa 'kmod-*' 'akmod-*' '*-kmod' 2>/dev/null | grep -v -E '^kmod-(libs|devel)-[0-9]' || true)
    [[ -z $extra ]] || fail "out-of-tree kernel modules are installed ($extra); they would break Secure Boot for the owner"
    local unowned
    local -a kpkgs
    mapfile -t kpkgs < <(rpm -qa --queryformat '%{NAME}\n' kernel-core 'kernel-modules*' 2>/dev/null | sort -u)
    ((${#kpkgs[@]})) || fail "no Fedora kernel packages (kernel-core, kernel-modules*) are installed"
    # rpm records the kernel's files under /lib/modules (via the /lib -> usr/lib symlink): compare
    # on /usr/lib. awk, not head: head would close the pipe early and SIGPIPE fails the build.
    unowned=$(comm -23 \
      <(find "/usr/lib/modules/$kver" -name '*.ko*' | sort) \
      <(rpm -ql "${kpkgs[@]}" 2>/dev/null | grep '\.ko' | sed 's#^/lib/#/usr/lib/#' | sort -u) | awk 'NR <= 5')
    [[ -z $unowned ]] || fail "kernel modules not from the Fedora kernel packages were found: $unowned"
  fi
}

check_sessions() {
  local s
  for s in "$ROOT"/usr/share/xsessions/*.desktop "$ROOT"/usr/share/wayland-sessions/*.desktop; do
    [[ -e $s ]] || continue
    [[ $s == */wayland-sessions/plasma.desktop ]] && continue
    local msg="extra login session offered: $s (Plasma Wayland must be the only session)"
    [[ $STRICT == 1 ]] && fail "$msg"
    warn "$msg"
  done
  [[ -f $ROOT/usr/share/wayland-sessions/plasma.desktop ]] || fail "the Plasma Wayland session is missing"
}

check_manifests() {
  if [[ -x $ROOT/usr/bin/kristall-apps ]]; then
    python3 "$ROOT/usr/bin/kristall-apps" validate "$ROOT/usr/share/kristall/apps/apps.json" ||
      fail "the app manifest (image/apps/apps.json) is invalid"
  fi
  if [[ -x $ROOT/usr/bin/kristall-settings ]]; then
    local out
    if ! out=$(KRISTALL_SETTINGS_DEFAULTS=$ROOT/usr/share/kristall/defaults/settings.json \
      KRISTALL_SETTINGS_DROPIN_DIRS=$ROOT/usr/share/kristall/defaults/settings.d:$ROOT/etc/kristall/settings.d \
      python3 "$ROOT/usr/bin/kristall-settings" check-defaults); then
      printf '%s\n' "$out"
      fail "a settings default file (settings.d/*.json) is not valid JSON or sets a key its component does not own (docs/contracts/settings.md, Ownership)"
    fi
    printf '%s\n' "$out"
  fi
}

clean_mutable() {
  # /var and /tmp are not part of a bootc image: only tmpfiles.d may populate them at boot.
  # /var/cache and /var/log are build-time cache mounts; leave the mount points alone.
  # Symlinks such as /var/run -> ../run come from the base and stay (the base already emptied /var).
  find "$ROOT/tmp" -mindepth 1 -maxdepth 1 -exec rm -rf {} + 2>/dev/null || true
  local d
  for d in "$ROOT"/var/*; do
    [[ -L $d ]] && continue
    [[ -e $d ]] || continue
    case ${d##*/} in
    cache | log) ;; # build-time cache mounts: never part of the image
    tmp) find "$d" -mindepth 1 -maxdepth 1 -exec rm -rf {} + ;;
    *) rm -rf "$d" ;;
    esac
  done
  mkdir -p "$ROOT/var/tmp"
  chmod 1777 "$ROOT/var/tmp"
}

phase_finalize() {
  group "Final checks"
  check_kernel
  check_sessions
  check_manifests
  local now
  now=$(forbidden_count)
  if ((now != BASE_FORBIDDEN)); then
    fail "files were written to /usr/local or /opt during the build; they would be lost (those paths live in /var on the installed system)"
  fi
  if command -v dnf5 >/dev/null && [[ -z $ROOT ]]; then
    dnf5 clean all >/dev/null 2>&1 || true
  fi
  clean_mutable
  endgroup
  note "Kristall OS image content is complete."
}

# --------------------------------------------------------------------------- main

BASE_KERNELS=""
BASE_FORBIDDEN=0
COMPONENTS=()
has_phase prepare && phase_prepare
has_phase components && phase_components
has_phase presets && phase_presets
has_phase finalize && phase_finalize
exit 0
