#!/usr/bin/bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Verifies that every RPM the image component installs exists in the Fedora repositories the
# base image uses (Fedora $FEDORA_VERSION + updates + negativo17 fedora-multimedia).
# Run INSIDE a Fedora container with network, e.g. (CI does this on every pull request):
#   podman run --rm -v "$PWD:/src:ro" quay.io/fedora/fedora:45 bash /src/image/tests/verify-fedora-packages.sh
set -euo pipefail
src=${1:-/src}
lists=("$src/image/packages.list" "$src/image/iso/packages.list")
if ! dnf5 repolist 2>/dev/null | grep -q fedora-multimedia; then
  curl -fsSLo /etc/yum.repos.d/negativo17-fedora-multimedia.repo https://negativo17.org/repos/fedora-multimedia.repo
fi
dnf5 -q makecache >/dev/null
missing=0
for list in "${lists[@]}"; do
  [[ -f $list ]] || continue
  while read -r pkg; do
    if nevra=$(dnf5 -q repoquery --latest-limit=1 --qf '%{name}-%{version}-%{release} [%{repoid}]\n' "$pkg" 2>/dev/null) && [[ -n $nevra ]]; then
      echo "ok       $pkg -> ${nevra%%$'\n'*}"
    else
      echo "::error::package '$pkg' (${list#"$src"/}) does not exist in Fedora $(rpm -E %fedora) repositories"
      missing=1
    fi
  done < <(sed -e 's/#.*//' -e '/^[[:space:]]*$/d' "$list")
done
exit "$missing"
