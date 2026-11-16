#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# Builds the kristall-devenv image (tag kristall-devenv:latest). Works in the cloud sandbox (HTTPS
# proxy on loopback + its CA) and on a machine without a proxy (GitHub's runners):
#   - ca-bundle.crt: the CA bundle added to the image's trust store. Kept if present (the sandbox
#     puts its proxy CA there); otherwise copied from $SSL_CERT_FILE or the system bundle, which is
#     harmless where no proxy intercepts TLS.
#   - HTTPS_PROXY is passed through when set (as Docker's predefined proxy build arguments, which
#     do not invalidate the layer cache); unset means a direct connection.
#   - the assistant daemon's pinned requirements are copied into the build context.
# Extra arguments go to `docker build` (CI: --cache-from/--cache-to, --load with buildx).
set -euo pipefail
here="$(cd "$(dirname "$0")" && pwd)"
repo="$(dirname "$(dirname "$here")")"
cd "$here"
if [ ! -s ca-bundle.crt ]; then
  for f in "${SSL_CERT_FILE:-}" /etc/ssl/certs/ca-certificates.crt /etc/pki/tls/certs/ca-bundle.crt; do
    [ -n "$f" ] && [ -s "$f" ] && { cp "$f" ca-bundle.crt; break; }
  done
fi
[ -s ca-bundle.crt ] || { echo "build.sh: no CA bundle found (set SSL_CERT_FILE)" >&2; exit 1; }
cp "$repo/assistant/core/image/requirements.txt" assistant-requirements.txt
cp "$repo/assistant/core/image/build-requirements.txt" assistant-build-requirements.txt
proxy=()
if [ -n "${HTTPS_PROXY:-${https_proxy:-}}" ]; then
  p="${HTTPS_PROXY:-${https_proxy:-}}"
  proxy=(--build-arg "HTTPS_PROXY=$p" --build-arg "https_proxy=$p")
fi
docker build --network host "${proxy[@]}" -t kristall-devenv:latest "$@" .
