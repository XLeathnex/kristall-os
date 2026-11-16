#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant-core: install the assistant daemon into the OS image.
#
# Runs as root at image build time with the repository at /ctx (read-only) and network.
# Installs: a private Python environment (pinned, hash-checked) under $PREFIX/lib/kristall/assistant,
# the commands kristall-assistant{,-ctl,-account}, a systemd user service (preset-enabled),
# default settings for the "assistant" key (settings.d drop-in), and the verified speech models.
# The Claude Code CLI is NOT installed here: the owner installs it with Anthropic's installer.
#
# Environment:
#   KRISTALL_PREFIX                default /usr
#   KRISTALL_SRC                   default $KRISTALL_CTX/assistant/core (KRISTALL_CTX default /ctx)
#   KRISTALL_MODEL_CACHE           optional directory with already-downloaded model files, named by
#                                  the first column of models.tsv (still checksum-verified)
#   KRISTALL_SKIP_MODELS=1         do not install speech models (development only)
#   KRISTALL_SKIP_SYSTEM_PACKAGES=1  do not call dnf5 (development only)
set -euo pipefail

PREFIX="${KRISTALL_PREFIX:-/usr}"
SRC="${KRISTALL_SRC:-${KRISTALL_CTX:-/ctx}/assistant/core}"
LIB="$PREFIX/lib/kristall/assistant"
SHARE="$PREFIX/share/kristall/assistant"
DEFAULTS="$PREFIX/share/kristall/defaults"
BIN="$PREFIX/bin"
UNITDIR="$PREFIX/lib/systemd/user"
PRESETDIR="$PREFIX/lib/systemd/user-preset"

log() { printf 'assistant-core: %s\n' "$*"; }

case "$PREFIX" in
  /usr/local|/usr/local/*|/opt|/opt/*) echo "KRISTALL_PREFIX must not be under /usr/local or /opt" >&2; exit 1 ;;
esac
[ -f "$SRC/kristall_assistant/daemon.py" ] || { echo "cannot find sources in $SRC" >&2; exit 1; }

# --- system packages (runtime only: Python, PipeWire command-line tools, pactl for ducking)
if [ "${KRISTALL_SKIP_SYSTEM_PACKAGES:-0}" != 1 ]; then
  need=()
  for p in python3 pipewire-utils pulseaudio-utils bzip2; do
    rpm -q "$p" >/dev/null 2>&1 || need+=("$p")
  done
  if [ "${#need[@]}" -gt 0 ]; then
    log "installing ${need[*]}"
    dnf5 install -y --setopt=install_weak_deps=False "${need[@]}"
    dnf5 clean all >/dev/null 2>&1 || true
  fi
fi
PYTHON="$(command -v python3)"

# --- private Python environment (rebuilt from scratch: idempotent)
log "creating Python environment in $LIB/venv"
rm -rf "$LIB/venv" "$LIB/kristall_assistant"
mkdir -p "$LIB"
"$PYTHON" -m venv "$LIB/venv"
VPY="$LIB/venv/bin/python"
export PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_CACHE_DIR=1 PIP_NO_INPUT=1
# Build backend for the Agent SDK's pure-Python source distribution (hash-pinned), then the
# runtime. --no-binary for claude-agent-sdk: its wheels bundle the proprietary Claude Code
# binary, which we must not ship; the sdist does not.
"$VPY" -m pip install --quiet --require-hashes -r "$SRC/image/build-requirements.txt"
"$VPY" -m pip install --quiet --require-hashes --no-build-isolation \
  --no-binary claude-agent-sdk -r "$SRC/image/requirements.txt"
"$VPY" -m pip uninstall --quiet -y hatchling pathspec pluggy trove-classifiers tomlkit >/dev/null
if find "$LIB/venv" -path '*claude_agent_sdk/_bundled/claude' -type f | grep -q .; then
  echo "refusing to ship a bundled Claude Code binary" >&2
  exit 1
fi

# --- our code
cp -r "$SRC/kristall_assistant" "$LIB/kristall_assistant"
find "$LIB/kristall_assistant" -name '__pycache__' -prune -exec rm -rf {} +
SITE="$("$VPY" -c 'import sysconfig; print(sysconfig.get_paths()["purelib"])')"
printf '%s\n' "$LIB" > "$SITE/kristall-assistant.pth"
"$VPY" -m compileall -q "$LIB/kristall_assistant" "$SITE" >/dev/null
"$VPY" -c 'import kristall_assistant.daemon, claude_agent_sdk, sherpa_onnx'   # smoke test

# --- commands
mkdir -p "$BIN"
for cmd in "kristall-assistant:daemon" "kristall-assistant-ctl:ctl" "kristall-assistant-account:account"; do
  name="${cmd%%:*}"
  mod="${cmd##*:}"
  cat > "$BIN/$name" <<EOF
#!/bin/sh
# SPDX-License-Identifier: GPL-3.0-or-later
exec "$VPY" -I -m kristall_assistant.$mod "\$@"
EOF
  chmod 0755 "$BIN/$name"
done

# --- systemd user service, enabled by preset
mkdir -p "$UNITDIR" "$PRESETDIR"
sed "s|@BIN@|$BIN|g" "$SRC/systemd/kristall-assistant.service" > "$UNITDIR/kristall-assistant.service"
install -m 0644 "$SRC/systemd/50-kristall-assistant-core.preset" "$PRESETDIR/50-kristall-assistant-core.preset"

# --- data: tool-server drop-in directory, licence notices
mkdir -p "$SHARE/mcp.d" "$SHARE/models"
install -m 0644 "$SRC/ASSETS.md" "$SHARE/ASSETS.md"

# --- defaults under the shared settings key "assistant" (docs/contracts/settings.md)
install -D -m 0644 "$SRC/data/settings-assistant.json" "$DEFAULTS/settings.d/50-assistant-core.json"

# --- speech models (verified downloads)
if [ "${KRISTALL_SKIP_MODELS:-0}" != 1 ]; then
  MODELS="$SHARE/models"
  work="$(mktemp -d)"
  trap 'rm -rf "$work"' EXIT
  while IFS=$'\t' read -r name kind sum dest url; do
    case "$name" in ''|'#'*) continue ;; esac
    file="$work/$name"
    if [ -n "${KRISTALL_MODEL_CACHE:-}" ] && [ -f "$KRISTALL_MODEL_CACHE/$name" ]; then
      cp -L "$KRISTALL_MODEL_CACHE/$name" "$file"
    else
      log "downloading $name"
      curl -fsSL --retry 4 --retry-delay 5 -o "$file" "$url"
    fi
    echo "$sum  $file" | sha256sum -c --quiet - || { echo "checksum mismatch for $name" >&2; exit 1; }
    case "$kind" in
      file)
        install -D -m 0644 "$file" "$MODELS/$dest" ;;
      tar.bz2)
        rm -rf "${MODELS:?}/$dest"
        mkdir -p "$MODELS/$dest"
        tar -xjf "$file" -C "$MODELS/$dest" --strip-components=1 --no-same-owner
        find "$MODELS/$dest" -type d -exec chmod 0755 {} +
        find "$MODELS/$dest" -type f -exec chmod 0644 {} + ;;
      *) echo "unknown kind $kind" >&2; exit 1 ;;
    esac
    rm -f "$file"
  done < "$SRC/image/models.tsv"
fi

log "installed into $PREFIX"
