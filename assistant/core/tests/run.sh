#!/usr/bin/env bash
# SPDX-License-Identifier: GPL-3.0-or-later
# assistant-core test suite.
#
# Needs Python >= 3.11 with the pinned runtime dependencies (claude-agent-sdk, sherpa-onnx, numpy)
# and pytest. By default a private virtualenv is created once under ~/.cache (needs network the
# first time); set KRISTALL_TEST_PYTHON to use an existing interpreter instead.
# Voice tests need the speech models: KRISTALL_TEST_MODELS=<dir laid out like
# /usr/share/kristall/assistant/models> (the installed directory is used when present).
# No real `claude` is ever called: tests/fake_claude.py replays recorded sessions.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(dirname "$HERE")"

PY="${KRISTALL_TEST_PYTHON:-}"
if [ -z "$PY" ]; then
  VENV="${KRISTALL_TEST_VENV:-${XDG_CACHE_HOME:-$HOME/.cache}/kristall/assistant-test-venv}"
  if ! "$VENV/bin/python" -c 'import claude_agent_sdk, sherpa_onnx, numpy, pytest' 2>/dev/null; then
    echo "== preparing test environment in $VENV"
    # the interpreter the image uses for the daemon (install.sh): python3.14 where available
    "${KRISTALL_TEST_BASE_PYTHON:-$(command -v python3.14 || command -v python3)}" -m venv "$VENV"
    "$VENV/bin/pip" install -q --require-hashes -r "$ROOT/image/build-requirements.txt"
    "$VENV/bin/pip" install -q --require-hashes --no-build-isolation --no-binary claude-agent-sdk \
      -r "$ROOT/image/requirements.txt"
    "$VENV/bin/pip" install -q pytest
  fi
  PY="$VENV/bin/python"
fi

if [ -z "${KRISTALL_TEST_MODELS:-}" ] && [ -d /usr/share/kristall/assistant/models/asr ]; then
  export KRISTALL_TEST_MODELS=/usr/share/kristall/assistant/models
fi

echo "== assistant-core tests"
echo "   policy        permission decisions for shell, file, web and MCP tools; grants"
echo "   brain         Claude Code driving via the Agent SDK against recorded streams: invocation"
echo "                 flags, follow-ups, warm spare, permissions, memory, interrupt, every error state"
echo "   protocol      socket conformance with docs/contracts/assistant-ipc.md, ordering, fan-out,"
echo "                 cancel/barge-in, timeouts, agent cursor relay, level subscription"
echo "   voice         German/English round trip (synthesise -> recognise, WER), end of speech,"
echo "                 partial transcripts, cut-in, model unloading, full spoken turn"
echo "                 (${KRISTALL_TEST_MODELS:-skipped: no models})"
echo "   demo/account  scripted demo session, sign-in commands, settings, mcp.d drop-ins"
cd "$ROOT"
"$PY" -m pytest -q -rs -p no:cacheprovider tests "$@"

if command -v shellcheck >/dev/null 2>&1; then
  echo "== shellcheck"
  shellcheck "$ROOT/image/install.sh" "$HERE/run.sh"
  echo "   ok"
else
  echo "== shellcheck not installed; skipped"
fi
