#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Tests the image build orchestrator (image/build.sh): order, skip, strict, failures, presets.
# shellcheck disable=SC2015,SC2016  # A && pass || fail is intended; single quotes build scripts.
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
BUILD=$HERE/../build.sh
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
fails=0
pass() { printf 'ok    %s\n' "$*"; }
fail() {
  printf 'FAIL  %s\n' "$*"
  fails=$((fails + 1))
}

new_ctx() { # name, components...
  local ctx=$TMP/$1
  shift
  mkdir -p "$ctx/image" "$ctx/root"
  printf '# test list\n\n' >"$ctx/image/components.list"
  local c
  for c in "$@"; do printf '%s   # comment\n' "$c" >>"$ctx/image/components.list"; done
  echo "$ctx"
}

add_component() { # ctx, name, [script body]
  mkdir -p "$1/$2/image"
  printf '#!/usr/bin/bash\nset -euo pipefail\necho "$KRISTALL_COMPONENT $KRISTALL_PREFIX $PWD" >>"%s/order.log"\n%s\n' \
    "$1" "${3:-}" >"$1/$2/image/install.sh"
}

run_build() { # ctx, phases, extra env...
  local ctx=$1 phases=$2
  shift 2
  env KRISTALL_CTX="$ctx" KRISTALL_BUILD_PHASES="$phases" KRISTALL_ROOT="$ctx/root" \
    KRISTALL_SYSTEMCTL="$ctx/fake-systemctl" "$@" bash "$BUILD" >"$ctx/out.log" 2>&1
}

# 1. order, prefix, working directory, missing component skipped with a warning
ctx=$(new_ctx order image power kwin/glass shell)
add_component "$ctx" image
add_component "$ctx" kwin/glass
add_component "$ctx" shell
if run_build "$ctx" components; then pass "non-strict build succeeds with a missing component"; else fail "non-strict build failed: $(cat "$ctx/out.log")"; fi
got=$(cut -d' ' -f1 "$ctx/order.log" | tr '\n' ' ')
[[ $got == "image kwin/glass shell " ]] && pass "components run in list order ($got)" || fail "wrong order: $got"
grep -q "^image /usr $ctx/image$" "$ctx/order.log" && pass "KRISTALL_PREFIX=/usr and cwd = component dir" || fail "env/cwd wrong: $(head -1 "$ctx/order.log")"
grep -q "::warning.*SKIPPING component 'power'" "$ctx/out.log" && pass "missing component produces a loud warning" || fail "no skip warning"

# 2. strict mode fails on the missing component, before running later ones
rm -f "$ctx/order.log"
if run_build "$ctx" components KRISTALL_STRICT=1; then fail "strict build succeeded although 'power' is missing"; else pass "strict build fails on a missing component"; fi
grep -q "::error.*'power'" "$ctx/out.log" && pass "strict failure names the component" || fail "strict error message unclear: $(cat "$ctx/out.log")"
[[ $(cut -d' ' -f1 "$ctx/order.log" | tr '\n' ' ') == "image " ]] && pass "strict stops at the missing component" || fail "strict ran too much"

# 3. directory present but no installer counts as missing
ctx=$(new_ctx noinst image theme)
add_component "$ctx" image
mkdir -p "$ctx/theme"
run_build "$ctx" components && grep -q "theme/image/install.sh does not exist" "$ctx/out.log" &&
  pass "directory without image/install.sh is skipped with a reason" || fail "no-installer case: $(cat "$ctx/out.log")"

# 4. a failing component stops the build with its name and status
ctx=$(new_ctx failing image power setup)
add_component "$ctx" image
add_component "$ctx" power "exit 7"
add_component "$ctx" setup
if run_build "$ctx" components; then fail "failing component did not fail the build"; else pass "failing component fails the build"; fi
grep -q "::error.*'power' failed.*status 7" "$ctx/out.log" && pass "failure message names component and status" || fail "unclear failure: $(cat "$ctx/out.log")"
grep -q '^setup' "$ctx/order.log" && fail "components after a failure still ran" || pass "later components do not run after a failure"

# 5. bad lists
ctx=$(new_ctx dup image image)
add_component "$ctx" image
run_build "$ctx" components && fail "duplicate entry accepted" || pass "duplicate entry rejected"
ctx=$(new_ctx escape image ../outside)
run_build "$ctx" components && fail "'../outside' accepted" || pass "path escaping the repository rejected"

# 6. writing to /usr/local: warning normally, error in strict mode
ctx=$(new_ctx local image power)
add_component "$ctx" image
add_component "$ctx" power "mkdir -p \"$ctx/root/usr/local/bin\"; touch \"$ctx/root/usr/local/bin/x\""
run_build "$ctx" prepare,components && grep -q "::warning.*'power' wrote into /usr/local" "$ctx/out.log" &&
  pass "/usr/local write is reported" || fail "/usr/local write not reported: $(cat "$ctx/out.log")"
rm -rf "$ctx/root/usr/local"
run_build "$ctx" prepare,components KRISTALL_STRICT=1 && fail "strict build allowed /usr/local" || pass "strict build rejects /usr/local writes"

# 7. presets added by components are applied (system + --global), base presets are not touched
ctx=$(new_ctx presets image shell)
mkdir -p "$ctx/root/usr/lib/systemd/user-preset" "$ctx/root/usr/lib/systemd/system-preset" "$ctx/root/usr/lib/systemd/user"
echo "enable base-thing.service" >"$ctx/root/usr/lib/systemd/user-preset/90-base.preset"
printf '#!/usr/bin/bash\necho "$*" >>"%s/systemctl.log"\n' "$ctx" >"$ctx/fake-systemctl"
chmod +x "$ctx/fake-systemctl"
add_component "$ctx" image
add_component "$ctx" shell "touch \"$ctx/root/usr/lib/systemd/user/kristall-shell.service\" \"$ctx/root/usr/lib/systemd/user/kristall-dock.service\"
printf 'enable kristall-shell.service\nenable kristall-dock*.service\n# note\n' >\"$ctx/root/usr/lib/systemd/user-preset/50-kristall-shell.preset\"
mkdir -p \"$ctx/root/usr/lib/systemd/system\"; touch \"$ctx/root/usr/lib/systemd/system/kristall-power.service\"
echo 'enable base-other.service' >>\"$ctx/root/usr/lib/systemd/user-preset/90-base.preset\"
printf 'enable kristall-power.service\nenable not-installed.service\n' >\"$ctx/root/usr/lib/systemd/system-preset/50-kristall-power.preset\""
if run_build "$ctx" prepare,components,presets; then pass "presets phase succeeds"; else fail "presets phase failed: $(cat "$ctx/out.log")"; fi
grep -q -- "--root=$ctx/root --global preset kristall-shell.service" "$ctx/systemctl.log" && pass "new user preset applied with --global" || fail "user preset not applied: $(cat "$ctx/systemctl.log" 2>/dev/null)"
grep -q -- "--global preset kristall-dock.service" "$ctx/systemctl.log" && pass "preset globs expanded" || fail "glob not expanded"
grep -q -- "--root=$ctx/root preset kristall-power.service" "$ctx/systemctl.log" && pass "new system preset applied" || fail "system preset not applied"
grep -q "base-thing" "$ctx/systemctl.log" && fail "base preset was re-applied" || pass "base presets (even if a package update changed them) are left alone"
grep -q "not-installed" "$ctx/systemctl.log" && fail "preset applied to a unit that does not exist" || pass "presets for absent units are skipped quietly"

# 8. the real component list parses and has the documented order
ctx=$(new_ctx real)
cp "$HERE/../components.list" "$ctx/image/components.list"
run_build "$ctx" components
order=$(grep -o "Components, in order: .*" "$ctx/out.log")
[[ $order == "Components, in order: image power kwin/glass kwin/bridge shell shell/modules/panels shell/modules/dock shell/modules/search shell/modules/apps shell/modules/switcher shell/modules/assistant assistant/core assistant/hands theme setup" ]] &&
  pass "repository components.list has the documented order" || fail "components.list order: $order"

# 9. the real list against the real tree: every installer is listed, ordering needs hold,
#    GameMode is installed in exactly one place (power)
REPO=$(cd "$HERE/../.." && pwd)
mapfile -t listed < <(sed -e 's/#.*//' -e 's/[[:space:]]*$//' "$REPO/image/components.list" | grep -v '^$')
idx() { local i; for i in "${!listed[@]}"; do [[ ${listed[$i]} == "$1" ]] && { echo "$i"; return; }; done; echo -1; }
missing_from_list=()
while IFS= read -r inst; do
  c=${inst#"$REPO/"}
  c=${c%/image/install.sh}
  [[ $(idx "$c") -ge 0 ]] || missing_from_list+=("$c")
done < <(find "$REPO" -path "$REPO/.git" -prune -o -path '*/tests' -prune -o -path '*/image/install.sh' -print | sort)
((${#missing_from_list[@]} == 0)) && pass "every component installer in the tree is listed" ||
  fail "installers not in components.list: ${missing_from_list[*]}"
ok=1
for c in "${listed[@]}"; do
  [[ $c == shell/modules/* && $(idx "$c") -lt $(idx shell) ]] && ok=0
  f=$REPO/$c/image/install.sh
  if [[ -f $f ]] && grep -q 'modules/dock/common' "$f" && [[ $c != shell/modules/dock ]]; then
    [[ $(idx shell/modules/dock) -ge 0 && $(idx shell/modules/dock) -lt $(idx "$c") ]] || ok=0
  fi
done
[[ $(idx theme) -gt $(idx shell) && $(idx setup) -eq $((${#listed[@]} - 1)) ]] || ok=0
((ok)) && pass "ordering needs hold (modules after shell, Dock before search/apps, theme after shell, setup last)" ||
  fail "components.list violates an ordering need"
mapfile -t installers < <(find "$REPO" -path "$REPO/.git" -prune -o -path '*/image/install.sh' -print)
mapfile -t gm < <(grep -lE '^[^#]*dnf5?[^#]*install[^#]*\bgamemode\b|^[^#]*[[:space:]]gamemode([[:space:]]|$)' \
  "${installers[@]}" 2>/dev/null)
[[ ${#gm[@]} -eq 1 && ${gm[0]} == "$REPO/power/image/install.sh" ]] && pass "GameMode is installed by power only" ||
  fail "GameMode installed by: ${gm[*]:-nobody}"

echo
if ((fails)); then
  echo "$fails orchestrator check(s) failed"
  exit 1
fi
echo "all orchestrator checks passed"
