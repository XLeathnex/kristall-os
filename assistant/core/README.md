# assistant-core — the assistant daemon (brain + voice)

`kristall-assistant` is a systemd user service that gives Kristall OS its assistant: it listens
(local speech recognition), thinks and acts (Claude Haiku 5.5 through the owner's own signed-in
Claude Code CLI), answers (streamed text and local speech) and talks to the interface over
`$XDG_RUNTIME_DIR/kristall/assistant.sock`. The protocol, error codes, tool-server drop-ins,
sign-in commands and settings are specified in [`docs/contracts/assistant-ipc.md`](../../docs/contracts/assistant-ipc.md).

## Layout

| path | |
|---|---|
| `kristall_assistant/daemon.py` | orchestrator: socket messages, turns, state machine, permission prompts |
| `kristall_assistant/server.py` | NDJSON Unix-socket server (same-UID only, many clients) |
| `kristall_assistant/brain/` | Claude Code via the Agent SDK (`brain.py`), system prompt (`prompt.py`), CLI discovery and isolation (`cli.py`), memory and its MCP tools (`memory.py`), `mcp.d` discovery (`mcp_config.py`) |
| `kristall_assistant/policy/` | permission policy (`policy.py`) and shell-command analysis (`shell.py`) |
| `kristall_assistant/voice/` | audio ends (`audio.py`: PipeWire / files), models (`models.py`), listening and speaking (`pipeline.py`), text→speakable text and sentence chunking (`speechtext.py`) |
| `kristall_assistant/replytext.py` | reply markup: normalises the model's Markdown into the subset the interface renders (typed) or plain text (spoken), while streaming (assistant-ipc §5.1) |
| `kristall_assistant/demo.py` | demo mode (scripted session, no Claude, no audio); the demo's agent cursor follows the primary output's real size (asked from the bridge's `outputs` topic; 1280×800 without a bridge) |
| `kristall_assistant/ctl.py`, `account.py` | `kristall-assistant-ctl`, `kristall-assistant-account` |
| `image/install.sh` | image build: venv (hash-pinned), commands, user unit + preset, defaults, verified models |
| `systemd/` | `kristall-assistant.service`, preset |
| `data/settings-assistant.json` | defaults for the shared settings key `assistant` |
| `tests/` | `run.sh`, pytest suite, `fake_claude.py` + recorded `fixtures/`, `ipc_schema.py` |
| `tools/` | `record_fixtures.py` (re-record fixtures with a real CLI), `voice_eval.py` (recogniser/voice benchmark) |
| `ASSETS.md` | models: sources, licences, checksums, and the measurements behind the choice |

## How it drives Claude

Anthropic's Python Agent SDK (`claude-agent-sdk` 0.2.182, from the sdist so no CLI binary is
shipped) starts the owner's `claude` (found in `~/.local/bin`, `$PATH`, or `KRISTALL_CLAUDE_CLI`)
as a long-lived process in streaming-JSON mode. The resulting invocation is

```
claude --output-format stream-json --verbose --system-prompt <ours> \
  --tools Read,Write,Edit,Glob,Grep,Bash,WebSearch,WebFetch --disallowedTools Agent,Task,AskUserQuestion,… \
  --model claude-haiku-5-5 --permission-prompt-tool stdio --permission-mode default \
  --mcp-config '{"mcpServers":{…mcp.d servers…,"kristall":{"type":"sdk"}}}' --include-partial-messages \
  --strict-mcp-config --setting-sources= --effort low --no-session-persistence --disable-slash-commands \
  --input-format stream-json
```

in `~/.local/share/kristall/assistant/workspace`, with env `CLAUDE_CODE_DISABLE_AUTO_MEMORY=1`,
`CLAUDE_CODE_DISABLE_CLAUDE_MDS=1`, `DISABLE_AUTOUPDATER=1` (and a few more, see `brain/cli.py`).
Not `--bare`, so the subscription login works; `--setting-sources=` + `--strict-mcp-config` +
no CLAUDE.md keep the owner's own coding setup (hooks, MCP servers, memory) out, and
`--no-session-persistence` keeps the assistant's chats out of their `claude --resume` list.
Every tool call passes a `PreToolUse` hook that runs our policy; "ask" falls through to the SDK's
permission callback, which asks the owner over the socket.

Measured with Haiku 5.5 in the sandbox: warm process ready 0.6 s after spawn; first token 1.2–1.5 s
after the question with `--effort low` (5.4 s with default adaptive thinking on a long request);
interrupt acknowledged in ~6 ms.

## Build and test

In the dev container or on any Linux with Python ≥ 3.11:

```
assistant/core/tests/run.sh                         # creates a test venv once (needs network)
KRISTALL_TEST_MODELS=/path/to/models tests/run.sh   # include the voice tests
```

Install into a scratch prefix (no dnf, models from a local cache or the network):

```
KRISTALL_PREFIX=/tmp/k KRISTALL_SRC=$PWD/assistant/core KRISTALL_SKIP_SYSTEM_PACKAGES=1 \
  bash assistant/core/image/install.sh
/tmp/k/bin/kristall-assistant --demo --demo-auto &   # then: /tmp/k/bin/kristall-assistant-ctl listen
```

Development helpers: `kristall-assistant --audio-in question.wav --audio-out answer.wav` replaces
microphone and speakers with files; `tools/record_fixtures.py <claude>` re-records the stream
fixtures (makes ~10 short real Haiku requests); `tools/voice_eval.py` benchmarks recognisers and voices.

## Known limits

* Not exercised on real hardware: microphone capture and playback through PipeWire (`pw-record`,
  `pw-play`), ducking via `pactl`, barge-in (needs an echo-cancelled source; off unless one exists).
* Wake word: setting reserved, not implemented.
* Permission questions are answered in the interface, not by voice.
* Recognition of very short or mixed-language utterances can pick the wrong language (Parakeet's
  automatic language detection); the "German only" recogniser avoids that for German speakers.
* The subscription's behaviour (usage pool, exact limit messages) could not be observed: the sandbox
  CLI authenticates with an API account. Error mapping relies on the CLI's structured fields
  (`rate_limit_event`, assistant `error`, `api_retry`) and is tested with synthetic streams.
