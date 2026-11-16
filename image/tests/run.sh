#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Test suite of the `image` component. Runs in the dev container, in CI, or on any machine with
# Python >= 3.11 and bash (shellcheck/actionlint/yamllint are used when installed).
# Needs no network and no root. Exit code != 0 if anything fails.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
REPO=$(cd "$HERE/../.." && pwd)
PY="${PYTHON:-python3} -B"
failed=()
section() { printf '\n=== %s\n' "$*"; }
record() { # name, status
  if (($2 == 0)); then printf -- '--- PASS %s\n' "$1"; else
    printf -- '--- FAIL %s\n' "$1"
    failed+=("$1")
  fi
}

section "shellcheck: image component scripts"
mapfile -t SCRIPTS < <(
  find "$REPO/image" -type f \( -name '*.sh' -o -path '*/libexec/kristall/*' \) | sort
)
if command -v shellcheck >/dev/null; then
  shellcheck -x "${SCRIPTS[@]}"
  record "shellcheck (${#SCRIPTS[@]} scripts)" $?
else
  echo "SKIPPED: shellcheck is not installed"
fi

section "Python syntax of the tools (python $($PY -c 'import sys; print(sys.version.split()[0])'))"
for t in kristall-settings kristall-update kristall-apps; do
  $PY -I -m py_compile "$REPO/image/rootfs/usr/bin/$t" && rm -rf "$REPO/image/rootfs/usr/bin/__pycache__"
  record "compile $t" $?
done

section "kristall-settings (merge, atomic writes, locking, watch without polling)"
(cd "$HERE" && $PY -m unittest -v test_settings 2>&1)
record "kristall-settings" $?

section "kristall-update (mocked bootc / flatpak / NetworkManager / systemd)"
(cd "$HERE" && $PY -m unittest -v test_update 2>&1)
record "kristall-update" $?

section "kristall-apps + app manifest"
(cd "$HERE" && $PY -m unittest -v test_apps 2>&1)
record "kristall-apps" $?

section "image/build.sh orchestrator"
bash "$HERE/test_build.sh"
record "orchestrator" $?

section "plasma-setup guard"
g=$(mktemp -d)
printf 'root:x:0:0::/root:/bin/bash\nplasma-setup:x:978:978::/:/sbin/nologin\n' >"$g/passwd"
printf 'UID_MIN 1000\n' >"$g/login.defs"
KRISTALL_PLASMA_SETUP_FLAG=$g/done KRISTALL_PASSWD=$g/passwd KRISTALL_LOGIN_DEFS=$g/login.defs \
  bash "$REPO/image/rootfs/usr/libexec/kristall/plasma-setup-guard" >/dev/null
r1=$([[ ! -e $g/done ]] && echo 0 || echo 1)
echo 'anna:x:1000:1000::/var/home/anna:/bin/bash' >>"$g/passwd"
KRISTALL_PLASMA_SETUP_FLAG=$g/done KRISTALL_PASSWD=$g/passwd KRISTALL_LOGIN_DEFS=$g/login.defs \
  bash "$REPO/image/rootfs/usr/libexec/kristall/plasma-setup-guard" >/dev/null
r2=$([[ -e $g/done ]] && echo 0 || echo 1)
rm -rf "$g"
echo "no users -> wizard stays enabled: $([[ $r1 == 0 ]] && echo yes || echo NO)"
echo "existing user -> wizard skipped: $([[ $r2 == 0 ]] && echo yes || echo NO)"
record "plasma-setup guard" $((r1 + r2))

section "JSON / YAML / desktop files"
rc=0
for j in "$REPO/image/apps/apps.json" "$REPO/image/rootfs/etc/skel/.var/app/com.visualstudio.code/config/Code/User/settings.json"; do
  $PY -c 'import json,sys; json.load(open(sys.argv[1]))' "$j" || rc=1
done
if $PY -c 'import yaml' 2>/dev/null; then
  for y in "$REPO/image/iso/iso.yaml" "$REPO/image/rootfs/etc/bazaar/bazaar.yaml" "$REPO"/.github/workflows/*.yml; do
    [[ -f $y ]] || continue
    $PY -c 'import yaml,sys; yaml.safe_load(open(sys.argv[1]))' "$y" || rc=1
  done
fi
if command -v desktop-file-validate >/dev/null; then
  desktop-file-validate "$REPO/image/iso/live/kristall-installer.desktop" || rc=1
fi
if command -v systemd-analyze >/dev/null; then
  # --man=no: the units only reference our own docs.
  out=$(cd "$REPO/image/rootfs/usr/lib/systemd/system" && systemd-analyze verify --man=no ./*.service ./*.timer 2>&1 |
    grep -v -e 'not found' -e 'Command .* is not executable' -e 'kristall-.*: Unit .* not found' || true)
  [[ -z $out ]] || {
    echo "$out"
    rc=1
  }
fi
record "data files" $rc

section "bootc kernel arguments (kargs.d files of every component)"
$PY - "$REPO" <<'PYEOF'
# bootc reads /usr/lib/bootc/kargs.d/*.toml: a table with "kargs" (array of strings) and optionally
# "match-architectures"; unknown keys are rejected (bootc container lint). Across components the
# same argument must not get two different values, and none of the arguments the power contract
# rejects (docs/contracts/power.md §5.3) may appear.
import glob, os, re, sys, tomllib
repo = sys.argv[1]
files = sorted(set(glob.glob(os.path.join(repo, "*", "**", "*kargs*.toml"), recursive=True)
                   + glob.glob(os.path.join(repo, "*", "**", "bootc", "kargs.d", "*.toml"), recursive=True)))
errors, seen = [], {}
rejected = re.compile(r"^(nosmt|pcie_aspm=|i915\.enable_(psr|fbc|dc)=|xe\.enable_(psr|fbc|dc)=|mem_sleep_default=|"
                      r"nomodeset$|intel_pstate=disable|processor\.max_cstate=|intel_idle\.max_cstate=)")
for f in files:
    rel = os.path.relpath(f, repo)
    try:
        d = tomllib.load(open(f, "rb"))
    except tomllib.TOMLDecodeError as e:
        errors.append("%s: %s" % (rel, e)); continue
    if set(d) - {"kargs", "match-architectures"} or not isinstance(d.get("kargs"), list) \
            or not all(isinstance(k, str) and k and " " not in k for k in d["kargs"]):
        errors.append("%s: needs exactly a \"kargs\" array of single arguments (+ optional match-architectures)" % rel)
        continue
    for k in d["kargs"]:
        if rejected.match(k):
            errors.append("%s: %s is rejected by the power contract (§5.3)" % (rel, k))
        key, _, val = k.partition("=")
        if key in seen and seen[key][1] != val:
            errors.append("%s: %s conflicts with %s=%s in %s" % (rel, k, key, seen[key][1], seen[key][0]))
        seen.setdefault(key, (rel, val))
    print("ok   %s: %s" % (rel, " ".join(d["kargs"])))
for e in errors:
    print("ERROR " + e)
print("%d kargs file(s), %s" % (len(files), "no conflicts" if not errors else "%d problem(s)" % len(errors)))
sys.exit(1 if errors else 0)
PYEOF
record "bootc kargs.d" $?

section "Installer (ISO) configuration"
$PY - "$REPO/image/iso" <<'PYEOF'
import configparser, os, re, sys
iso = sys.argv[1]
errors = []
try:
    import yaml
    doc = yaml.safe_load(open(os.path.join(iso, "iso.yaml")))
    label = doc["label"]
    for e in doc["grub2"]["entries"]:
        if "CDLABEL=%s " % label not in e["linux"] + " " or "rd.live.image" not in e["linux"]:
            errors.append("boot entry %r does not boot the ISO labelled %s" % (e["name"], label))
    if len(label) > 32 or " " in label:
        errors.append("ISO label must be <= 32 characters without spaces")
except ImportError:
    print("pyyaml missing: iso.yaml checked only for syntax elsewhere")
cp = configparser.ConfigParser()
cp.read(os.path.join(iso, "anaconda", "90-kristall.conf"))
if "anaconda-screen-accounts" not in cp.get("User Interface", "hidden_webui_pages", fallback=""):
    errors.append("the installer must not ask for an account (Plasma Setup does that)")
ks = open(os.path.join(iso, "anaconda", "kristall.ks.in")).read()
ks = ks.replace("@IMAGE_REF@", "ghcr.io/o/kristall-os").replace("@IMAGE_TAG@", "latest").replace("@PAYLOAD@", "/var/lib/kristall-installer/payload:kristall")
if re.search(r"@[A-Z_]+@", ks):
    errors.append("unreplaced placeholder in kristall.ks.in")
for need in ("ostreecontainer --url=/var/lib/kristall-installer/payload:kristall --transport=oci",
             "bootc switch --mutate-in-place --transport registry ghcr.io/o/kristall-os:latest"):
    if need not in ks:
        errors.append("kickstart lacks: " + need)
if ks.count("%post") != ks.count("%end"):
    errors.append("kickstart %post/%end blocks unbalanced")
for e in errors:
    print("ERROR " + e)
print("installer configuration: %s" % ("ok" if not errors else "%d problem(s)" % len(errors)))
sys.exit(1 if errors else 0)
PYEOF
record "installer configuration" $?

section "GitHub workflows"
if command -v actionlint >/dev/null; then
  (cd "$REPO" && actionlint -shellcheck "$(command -v shellcheck || true)" .github/workflows/*.yml)
  record "actionlint" $?
else
  echo "SKIPPED: actionlint is not installed"
fi
if command -v yamllint >/dev/null; then
  yamllint -d '{extends: relaxed, rules: {line-length: {max: 160}}}' "$REPO/.github/workflows" "$REPO/image/iso/iso.yaml"
  record "yamllint" $?
fi

echo
if ((${#failed[@]})); then
  echo "image tests FAILED: ${failed[*]}"
  exit 1
fi
echo "image tests: all passed"
