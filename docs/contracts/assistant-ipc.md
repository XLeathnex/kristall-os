# Contract: assistant IPC (`assistant.sock`) — protocol version 1

Owner: **assistant-core** (`assistant/core/`). Consumers: the assistant interface (shell, QML),
the Setup Assistant, `hands` (MCP tool server), anything else that wants to talk to the assistant.
This document is normative. `assistant/core/tests/ipc_schema.py` is a machine-checked copy of §5;
the test suite fails if the daemon emits anything not described here.

Words: *daemon* = `kristall-assistant`; *client* = anything connected to the socket; *turn* = one
request from the owner and everything that follows from it (listening, thinking, acting, answering,
speaking); *conversation* = a series of turns the model sees as one dialogue.

---

## 1. Transport

| | |
|---|---|
| Path | `$XDG_RUNTIME_DIR/kristall/assistant.sock` (override: env `KRISTALL_ASSISTANT_SOCKET`) |
| Type | Unix stream socket. Directory mode `0700`, socket mode `0600`. |
| Peers | Same UID only (checked with `SO_PEERCRED`; other UIDs are disconnected immediately). |
| Framing | UTF-8 JSON, exactly one object per line, terminated by `\n`. No pretty-printing. |
| Max line | 1 MiB (1 048 576 bytes). A longer line from a client gets an `error` (`bad_request`) and the connection is closed. |
| Clients | Any number at once. Every client receives every broadcast event (except `level`, see `subscribe`). |
| Lifetime | The daemon may not be running yet, may restart, may crash. Clients must reconnect with backoff (suggested: 0.2 s doubling to 5 s, forever) and must rebuild their view from the `snapshot` they receive on every connect. Never assume state survives a reconnect. |
| Slow clients | A client that does not read and lets more than 2000 events queue up is disconnected. |

Compatibility rules: clients **must ignore** unknown event types and unknown fields. The daemon
ignores unknown fields in requests. A breaking change increments `protocol` in `hello`; additions
do not.

## 2. Message envelope

**Client → daemon (requests):** `{"type": "<request>", "id": <string|int, optional>, …}`.
If `id` is present the daemon answers with exactly one `ack` carrying the same `id`
(`ok: true`, or `ok: false` with a `code`). Requests without `id` get no `ack` on success.
Malformed JSON, or JSON that is not an object with a string `type`, gets
`{"type":"ack","id":null,"ok":false,"code":"bad_json"}`. An unknown `type` gets
`ack` with `code: "unknown_type"` (and `re: <type>` when the request had no `id`).

`ack.code` values: `bad_json`, `unknown_type`, `bad_request` (missing/invalid field),
`unknown_request` (permission `request_id` not pending), `busy` *(addition: `transcribe` while a turn
is active)*, `internal`.

**Daemon → client (events):** every event has `type`, `seq` (integer, strictly increasing over the
daemon's lifetime and shared by all clients — use it to order and to detect a restart: a smaller
`seq` than the last one seen means a new daemon) and `ts` (Unix time, milliseconds).

**Bilingual text:** every owner-facing string the daemon authors is an object
`{"de": "…", "en": "…"}`. Show the one matching the system language. Strings produced by the
model (reply text, transcripts, explanations) are plain strings in whatever language was spoken.

## 3. Ordering guarantees

1. On connect the daemon sends `hello`, then `snapshot`, before any other event to that client.
2. An `ack` for a request is sent before any event caused by that request
   (e.g. `ack{turn_id}` precedes `turn_started` for an `invoke`).
3. Within a turn (all events with that `turn_id`):
   `turn_started` → [voice: `transcript(final:false)`* → `transcript(final:true)`] →
   `conversation` → { `reply_delta` | `activity` | `permission_request` → `permission_resolved` |
   `speech` }* → [`error`] → [`reply_done`] → `speech`* → `turn_finished`.
   `turn_finished` is always the last event of a turn and is always sent, whatever happened.
   `error` (if any) precedes `turn_finished`. `reply_done` is sent only if the model produced text.
4. `state` events are emitted only on change and may interleave anywhere. After `turn_finished`
   the next `state` is `idle` (unless another turn has started).
5. At most one turn is active at a time. `invoke` while a turn is active cancels it first: the old
   turn's `turn_finished` (outcome `cancelled`) precedes the new turn's `turn_started`.
6. After `turn_finished`, no further `reply_delta`, `speech` or `transcript` for that turn is sent.
7. `permission_resolved` follows every `permission_request`, exactly once.
8. `reply_delta` texts concatenated in order equal `reply_done.text`.

## 4. Requests (client → daemon)

### `hello`
`{"type":"hello","client":"<name>","role":"ui"|"tool"|"control","subscribe":["levels"]}` — optional.
Names the client (≤ 40 chars, shown in logs and as `agent_cursor.source`). `role: "tool"` is required
before `agent_cursor`/`tool_activity` are attributed to a tool. `subscribe: ["levels"]` = `subscribe{levels:true}`.

### `subscribe`
`{"type":"subscribe","levels":true|false}` — receive `level` events (20 Hz while listening or
speaking, nothing when idle). Default off; only clients that animate levels should subscribe.

### `get_snapshot`
Sends a fresh `snapshot` to this client only.

### `invoke`
Start a turn.

| field | type | |
|---|---|---|
| `mode` | `"voice"` \| `"text"` | default: setting `assistant.input_mode` |
| `text` | string | required (non-empty) for `text` |
| `source` | string | free label: `"hotkey"`, `"click"`, `"search"`, `"wake"` … (≤ 20 chars) |
| `context` | object | optional: `front_app` (app name), `window_title`, `selection` (selected text); each ≤ 2000 chars |
| `speak` | bool | optional override; default from setting `assistant.speak_replies` (`voice_only`: spoken iff `mode` is `voice`) |
| `new_conversation` | bool | start a fresh conversation even inside the follow-up window |

`ack` carries `turn_id` (string). A follow-up within `assistant.conversation_window_seconds`
(default 180 s) of the previous turn's end continues the conversation; otherwise a new one starts
(see `conversation`).

### `end_listening`
The owner finished speaking (push-to-talk released, "done" clicked): stop listening now and
transcribe what was heard. Ignored when not listening.

### `cancel`
Stop everything immediately: listening, the model's work (interrupted, not just hidden), pending
permission prompts (resolved `by: "cancelled"`), speech. The turn ends with outcome `cancelled`.
Use for Escape, closing the panel, the owner speaking over the assistant.

### `stop_speaking`
Stop the voice only; text keeps streaming and the turn continues silently.

### `permission_reply`
`{"type":"permission_reply","request_id":"…","decision":"allow_once"|"allow_always"|"deny"}`.
`allow_always` on a request whose `can_always` is false is treated as `allow_once`.

### `prepare`
Hint that a request is likely soon (panel opened, hotkey pressed down). Starts a warm Claude
process in the background so the first answer is fast. Cheap and idempotent.

### `new_conversation`
Forget the current conversation context; the next `invoke` starts fresh.

### `account_changed`
Sent by `kristall-assistant-account` after install/update/login/logout; the daemon re-checks and
emits `account` if anything changed. Any client may send it.

### `agent_cursor`
From tool servers (role `tool`, e.g. `hands`): show/move the assistant's own cursor. Relayed to all
clients as the `agent_cursor` event.

| field | type | |
|---|---|---|
| `x`, `y` | number | logical pixels in the global compositor space — the same coordinates as `docs/contracts/bridge.md` uses for input and screenshots. Omit both to keep the last position. |
| `visible` | bool | default `true` |
| `pulse` | string | one-shot effect at this position: `click`, `double_click`, `right_click`, `drag_start`, `drag_end`, `type`, `scroll` |
| `label` | string | short caption next to the cursor (≤ 60 chars), e.g. the button being pressed |
| `output` | string | optional ≤ 80 chars, e.g. the text being typed |
| `duration_ms` | int | how long the interface should take to animate to `x,y` (0–5000; default: interface's choice) |

When a tool client disconnects while its cursor is visible, the daemon emits `agent_cursor` with
`visible:false`.

### `tool_activity`
From tool servers: a better human-readable status line than the daemon can derive, e.g.
`{"type":"tool_activity","text":{"de":"Klicke auf „Senden“","en":"Clicking “Send”"},"status":"running","activity_id":"…"}`.
`text` may also be a plain string (used for both languages). Relayed as `activity` with `source:"tool"`.

### `transcribe` *(addition, 2026-11-16)*
Transcribe only: open the microphone, run speech recognition, report levels and the text — and
nothing else. No turn is started, nothing is sent to Claude, no account or sign-in is needed, the
daemon's `state` does not change (stays `idle`), other audio is not ducked. For the Setup
Assistant's microphone check and any "dictate into this field" use.

| field | type | |
|---|---|---|
| `no_speech_timeout_seconds` | number 1–30 | optional; default setting `assistant.no_speech_timeout_seconds` |
| `max_seconds` | number 1–45 | optional; default setting `assistant.max_utterance_seconds` |

`ack` carries `transcription_id`. Refused with `ack.code: "busy"` while a turn is active; an `invoke`
cancels a running transcription (it ends with outcome `cancelled`) before its turn starts; a second
`transcribe` replaces the first (likewise). Events, in this order: `level` (source `mic`, 20 Hz,
only to clients that subscribed to levels), `transcription` (`final:false`)\*, then on success one
`transcription` with `final:true`, and always exactly one `transcription_finished`. End of speech is
detected as in a voice turn (`end_of_speech_ms`).

### `transcribe_stop` *(addition)*
`{"type":"transcribe_stop","transcription_id"?}` — stop listening now and transcribe what was heard
(push-to-talk released). Ignored when no transcription is running.

### `transcribe_cancel` *(addition)*
`{"type":"transcribe_cancel","transcription_id"?}` — throw the transcription away (outcome `cancelled`).

### `demo_error`
Only when the daemon runs with `--demo`: `{"type":"demo_error","code":"<error code>"}` emits that
`error` so every error state can be designed and screenshotted.

### `demo_account`
Only with `--demo`: `{"type":"demo_account","status":"signed_out"}` emits an `account` event with that status.

## 5. Events (daemon → client)

### `hello`
`protocol` (int, `1`), `daemon` (`"kristall-assistant"`), `version` (string), `demo` (bool).

### `snapshot`
Everything needed to draw the interface from scratch:
`state` (see `state`), `turn` (`null` or `{turn_id, input, text, reply, speak}` — `reply` is the text
so far), `account` (same fields as the `account` event), `pending_permissions` (array of
`permission_request` payloads still waiting), `agent_cursor` (`null` or last cursor fields without
`type`/`pulse`), `assistant` (`{name, language, input_mode}` from settings), `voice`
(`{input: bool, output: bool, live_transcript: bool}` — `input:false` means hide/disable the
microphone affordance and offer typing).

### `ack`
`id` (as sent, or `null`), `ok` (bool), optional `code` (§2), `message` (bilingual), `turn_id`
(for `invoke`), `detail`, `re`.

### `state`
`state`: one of

| state | meaning (what to show) |
|---|---|
| `idle` | nothing happening |
| `listening` | microphone open; animate with mic `level`; show live `transcript` |
| `transcribing` | speech ended, final transcript being computed (short) |
| `thinking` | waiting for / streaming the model's answer |
| `acting` | a tool is running or a permission prompt is waiting (`detail:"waiting_for_permission"`) |
| `speaking` | the answer is being spoken; animate with speech `level` |
| `error` | reserved for a persistent failure; transient failures are `error` events and the state returns to `idle` |

`turn_id`: the active turn or `null`. `detail`: optional string (`waiting_for_permission`).
While audio is playing `speaking` wins over `thinking`/`acting`; `activity` events still arrive.

### `turn_started`
`turn_id`, `input` (`voice`|`text`), `source`, `text` (string for text turns, `null` for voice until
transcribed), `speak` (bool: whether the reply will be spoken).

### `conversation`
`turn_id`, `conversation_id` (opaque), `continued` (bool: `true` = follow-up in the same
conversation; `false` = fresh conversation, the interface may clear older bubbles).

### `level`
Only to subscribed clients. `source`: `mic` (while listening) or `speech` (while speaking),
`value`: 0.0–1.0, perceptual (−60 dBFS → 0, 0 dBFS → 1). Up to 20 per second, a final `0` when the
source stops. Never sent while idle.

### `transcript`
`turn_id`, `text` (the whole utterance so far, not a delta), `final` (bool). Partial transcripts
replace each other; exactly one `final:true` per voice turn that heard speech.

### `transcription` *(addition)*
`transcription_id`, `text` (the whole utterance so far), `final` (bool). Like `transcript`, but for
`transcribe` (no turn); exactly one `final:true` when the outcome is `completed`.

### `transcription_finished` *(addition)*
`transcription_id`, `outcome` (`completed` \| `nothing_heard` \| `cancelled` \| `error`), `text` (the
final text, `""` unless completed), `error_code` (`null`, or `speech_models_missing`,
`mic_unavailable`, `internal` — §7.2), `audio_seconds` (number). Always the last event of a
transcription.

### `reply_delta`
`turn_id`, `text` (append to the reply; markup as §5.1 allows), `segment` (int, starts at 0, increments after each tool
use — text in an earlier segment is the model's "what I'm doing" preamble, the last segment is the
answer; an interface may render segments as separate paragraphs).

### `reply_done`
`turn_id`, `text` (the complete reply), `spoken` (bool: speech was produced for it). Speech may
continue after this event.

### `speech`
`turn_id`, `sentence` (int, 0-based), `text`: the sentence that starts playing now (for
highlighting/captions). Also used for spoken permission questions and spoken error messages.

### `activity`
What the assistant is doing right now, one line. `turn_id` (string, or `null` if a tool reports
outside a turn), `id` (stable per action; `running` then `done`/`failed` share it), `tool` (tool name, e.g.
`WebSearch`, `Bash`, `mcp__hands__click`, `_retry`), `status` (`running`|`done`|`failed`),
`text` (bilingual line, e.g. `{"de":"Suche im Web nach „Wetter Berlin“", …}`), optional
`detail` (the model's own description of a command, as written by the model), `source`
(`assistant` = derived by the daemon, `tool` = sent by a tool server via `tool_activity`).

### `permission_request`
The model wants to do something that needs the owner's yes.

| field | type | |
|---|---|---|
| `request_id` | string | answer with `permission_reply` |
| `turn_id` | string | |
| `question` | bilingual | the line to show: e.g. `{"de":"Darf ich „alt.txt“ endgültig löschen?","en":"May I permanently delete “alt.txt”?"}` |
| `action` | bilingual | the same as an infinitive phrase (`"„alt.txt“ endgültig löschen"`), for custom layouts |
| `explanation` | string | the model's own words about what it is about to do and why (may be empty) |
| `category` | string | §7.1 |
| `can_always` | bool | whether "always allow this kind of thing" may be offered |
| `options` | array | `["allow_once","allow_always","deny"]` or `["allow_once","deny"]` |
| `tool` | string | tool name |
| `technical` | string | exactly what would run (command, path, tool + arguments) — for a "Details" disclosure |
| `expires_in` | int | seconds until it is denied automatically (`assistant.permission_timeout_seconds`, default 120) |

Suggested buttons: **Erlauben** (`allow_once`), **Immer erlauben** (`allow_always`, only if
offered; label it with the category, e.g. "Löschen immer erlauben"), **Nicht erlauben** (`deny`).
If the reply is spoken, the daemon also speaks the question.

### `permission_resolved`
`request_id`, `turn_id`, `decision` (`allow_once`|`allow_always`|`deny`), `by` (`owner`|`timeout`|`cancelled`).
Remove the prompt on this event (another client may have answered).

### `turn_finished`
`turn_id`, `outcome` (`completed`|`cancelled`|`error`|`nothing_heard`), `error_code` (string or `null`).

### `error`
`code` (§7.2), `message` (bilingual, owner-facing, never technical), `retryable` (bool: offer
"try again"), `action` (`null` or a button to offer: `sign_in`, `install_cli`, `update_cli`,
`open_sound_settings`), `turn_id` (or `null`), optional `resets_at` (Unix seconds, when a usage
limit resets; already reflected in `message`).

### `account`
Sign-in state of the owner's Claude Code installation; sent when it changes.
`status`: `checking` | `ready` | `cli_missing` | `cli_outdated` | `signed_out` | `unknown`;
`cli_path`, `cli_version` (strings or null), `min_version`, `logged_in` (bool/null),
`auth_method`, `detail` (log text). Interfaces show the assistant as unavailable with a
"Sign in" / "Set up" action for anything but `ready` (and `unknown`, where a request is still tried).

### `usage_warning`
The owner is approaching a usage limit. `utilization` (0–1 or null), `resets_at` (Unix seconds or
null), `window` (e.g. `five_hour`, `seven_day`, or null). Optional to display.

### `agent_cursor`
Relay of a tool's `agent_cursor` request (§4) with `source` (the tool client's name), `visible`,
optional `x`, `y`, `pulse`, `label`, `output`, `duration_ms`, and `turn_id` (or `null`). Draw the
assistant's cursor in its own overlay; never move the owner's pointer.

### 5.1 Reply markup *(addition, 2026-11-16)*

What `reply_delta.text` / `reply_done.text` (and `snapshot.turn.reply`) may contain. The interface
renders it with `shell/core/Markdown.js`; the daemon normalises the model's text so
that nothing outside this list arrives (`assistant/core/kristall_assistant/replytext.py`, tested in
`tests/test_replytext.py`).

**Typed replies** (`turn_started.speak: false`) — line-based Markdown, this subset only:

| Construct | Form |
|---|---|
| paragraph / line break | blank line between paragraphs; a single `\n` is a line break |
| heading | `#` … `######` + space at line start (shown as a bold line) |
| bullet list | `-`, `*`, `+` or `•` + space; one nesting level: 2 leading spaces (deeper is sent as 2) |
| numbered list | 1–3 digits + `.` or `)` + space; nesting as above |
| list item continuation | a following line indented by ≥ 2 spaces |
| block quote | `>` at line start |
| code block | fenced with ```` ``` ```` or `~~~` (a language tag after the fence is allowed and ignored); content verbatim |
| rule | `---`, `***`, `___` alone on a line |
| inline | `**bold**` / `__bold__`, `*italic*` / `_italic_`, `` `code` ``, `~~strike~~`, `[text](url)` with an `http:`, `https:` or `mailto:` URL |

Everything else is rewritten by the daemon before it is sent: **Tables** → one bullet per row,
`- Header: cell; Header: cell` (the separator row disappears); images `![alt](url)` → `[alt](url)`
(http/https) or `alt`; links with any other scheme → `text (url)`; autolinks `<https://…>` →
`[https://…](https://…)`; raw HTML: `<br>` → line break, `<b>`/`<strong>` → `**`, `<i>`/`<em>` →
`*`, `<code>` → `` ` ``, `<s>`/`<del>` → `~~`, every other tag removed; HTML entities decoded;
backslash escapes removed (an escaped `*` becomes `∗` U+2217 so it never turns into emphasis);
task-list boxes `[ ]`/`[x]` → `☐`/`☑`; a setext `===` underline → `---`. Inside code spans and
fenced code nothing is rewritten. No raw HTML ever reaches a client.

**Spoken replies** (`speak: true`) are **plain**: no markup at all — markers of the constructs above
are removed (headings, list markers and quote markers dropped, links → their text, code → its text,
tables → `Header: cell; …` lines, fences and rules → empty lines); line breaks stay.

Streaming: the daemon holds back only what may still be rewritten — the first 8 characters of a
line (until its list/heading/quote/table/fence head is known), table and fence lines until they end,
and the rest of a line from the first `<`, `&`, `\`, `!`, `[` or `` ` `` (spoken: also `*`, `_`,
`~`). Ordinary prose streams at once. Guarantee 8 of §3 holds for the normalised text; held text of
a segment is sent before that segment's first `activity` and before `reply_done`.

## 6. Turn lifecycle and states

```
invoke(voice) ─► listening ─► transcribing ─► thinking ⇄ acting ─► (speaking) ─► idle
invoke(text)  ─────────────────────────────► thinking ⇄ acting ─► (speaking) ─► idle
                 any state ── cancel / new invoke ──► idle (turn_finished: cancelled)
```

* End of speech is detected automatically (silence ≥ `assistant.end_of_speech_ms`, default 800 ms),
  or by `end_listening`. If nothing is said within `assistant.no_speech_timeout_seconds` (7 s) the
  turn ends with outcome `nothing_heard` and an `error` with code `nothing_heard`.
* Speaking starts with the first complete sentence, while the model is still writing; the
  preamble ("Ich schaue kurz nach.") is spoken while the tool runs.
* Other applications' audio is lowered while listening and speaking (setting
  `assistant.duck_other_audio`).
* Interrupting by voice while the assistant speaks (barge-in) needs an echo-cancelled microphone;
  setting `assistant.barge_in`: `auto` (default: only if PipeWire offers an `echo-cancel` source),
  `on`, `off`. The interface should always send `cancel` on Escape.

## 7. Codes

### 7.1 Permission categories

What the model may do without asking: reading anything except credentials (`read`), and reversible
actions (`reversible`: opening apps and files, changing volume/brightness/theme, creating new files
and folders, moving to the trash, downloading). Everything else asks:

| category | meaning | "always" possible |
|---|---|---|
| `files.modify` | overwrite or edit an existing file of the owner | yes |
| `files.delete` | delete permanently (not trash) | yes |
| `system.config` | dotfiles, autostart, user services, shell profile | yes |
| `processes.stop` | quit/kill a running program, stop a user service | yes |
| `system.power` | shut down, reboot, log out | yes |
| `apps.install` | install/remove/update software (Flatpak, pip, npm …) | yes |
| `shell.run` | a command the policy cannot classify (granted per program) | yes |
| `tool.use` | a tool without a declared risk (granted per tool) | yes |
| `send` | send/post/upload anything on the owner's behalf (mail, messages, POST, git push, ssh) | no |
| `purchase` | buy or pay | no |
| `elevated` | administrator rights (sudo, pkexec, system services, writes outside the home folder) | no |
| `credentials` | passwords, keys, keyrings, browser logins | no |

Never allowed (no prompt, the model is told no): the owner's Claude Code credentials and
configuration (`~/.claude*`), the assistant's own permission store and tool-server directory.
"Always" grants are stored in `~/.config/kristall/assistant/permissions.json`
(`{"version":1,"always":{"<scope>":{"since":…,"label":…}}}`, scopes: a category, `shell.run:<program>`,
or `mcp:<server>:<tool>`); a settings UI may list and delete entries (write atomically; the daemon
reloads on change).

### 7.2 Error codes

| code | when | action |
|---|---|---|
| `cli_missing` | Claude Code is not installed | `install_cli` |
| `cli_outdated` | installed version older than the minimum, or the model is unknown to it | `update_cli` |
| `not_signed_in` | not signed in / sign-in expired | `sign_in` |
| `credit_exhausted` | subscription usage for the assistant used up (message says when it resets) | — |
| `rate_limited` | short-term limit; message says when to retry | — |
| `overloaded` | Claude is overloaded | — |
| `offline` | no connection to Claude | — |
| `refused` | the model declined the request | — |
| `service_error` | other error from Claude | — |
| `brain_crashed` | the Claude process died; it is restarted automatically | — |
| `timeout` | Claude did not start in time | — |
| `mic_unavailable` | no microphone / capture failed | `open_sound_settings` |
| `audio_output_unavailable` | playback failed; answers continue as text | `open_sound_settings` |
| `speech_models_missing` | speech models not installed; typing still works | — |
| `nothing_heard` | listening ended without speech | — |
| `busy` | reserved | — |
| `internal` | bug in the daemon (logged) | — |

## 8. Tool servers (`mcp.d`) — for `hands` and others

A tool server is an MCP server the daemon gives to Claude. Install one JSON file:
`/usr/share/kristall/assistant/mcp.d/<NN>-<name>.json` (system, from the image) or
`~/.config/kristall/assistant/mcp.d/<name>.json` (user). Files are read in that order, each
directory sorted by name; a later definition of the same server name wins; `null` removes one.
Changes apply to the next new conversation (inotify, no restart).

```json
{
  "mcpServers": {
    "hands": { "type": "stdio", "command": "/usr/bin/kristall-hands", "args": [], "env": {} }
  },
  "kristall": {
    "hands": {
      "label": { "de": "Bildschirmsteuerung", "en": "Screen control" },
      "publishes_events": true,
      "tools": {
        "screenshot":  { "risk": "read" },
        "click":       { "risk": "reversible", "label": { "de": "Klicken", "en": "Click" } },
        "type_text":   { "risk": "reversible" },
        "close_window":{ "risk": "reversible" },
        "*":           { "risk": "ask" }
      }
    }
  }
}
```

* `mcpServers.<name>`: `type` `stdio` (default; `command` required, `args`, `env`) or `http`/`sse`
  (`url`, `headers`). Name: `[A-Za-z0-9_-]{1,40}`; `kristall` is reserved.
* Tools appear to the model as `mcp__<name>__<tool>`. Every call goes through the permission policy
  (§7.1). `risk` is a category name from §7.1, `read`, `reversible`, `ask` (= `tool.use`) or
  `deny`. Undeclared tools ask (`tool.use`). Declare honestly: the risk of the *typical* call.
* **Model-declared risk:** if a tool's input schema has an optional string property `risk`
  (enum of §7.1 categories), the model can mark a specific call as riskier (e.g. a click on "Kaufen"
  → `purchase`); the policy then asks. It can only raise the risk, never lower it. Recommended for
  `click`/`type_text`. Likewise an optional `intent` string property ("Klicke auf Senden") is used
  as the activity line and shown in permission prompts.
* The daemon passes its environment to Claude, which passes it to stdio servers, so
  `XDG_RUNTIME_DIR` is set. To show the cursor, connect to `assistant.sock`, send
  `{"type":"hello","client":"hands","role":"tool"}`, then `agent_cursor` / `tool_activity`
  requests (§4). Send cursor positions at most at 60 Hz and only while moving; send `visible:false`
  when done. The connection may fail (daemon restarting) — never block a tool call on it.

## 9. Sign-in machinery: `kristall-assistant-account`

For the Setup Assistant's "Sign in with Claude" step. Run as the owner (never as root). Output:
JSON lines on stdout; the last line is always a `result`. Exit status 0 iff `result.ok`.

| command | does |
|---|---|
| `status` | `{"event":"status", …}` then `result` with `status` |
| `install [--channel stable\|latest]` | downloads Anthropic's official installer from `https://claude.ai/install.sh` over HTTPS and runs it for the current user (installs to `~/.local/bin/claude`, versions in `~/.local/share/claude/`) |
| `update` | `claude update` |
| `login [--console] [--open]` | starts `claude auth login --claudeai` (subscription; `--console` for API billing). The CLI itself tries to open the browser; `--open` additionally opens it with `xdg-open` |
| `logout` | `claude auth logout` |

Events:

| event | fields | interface should |
|---|---|---|
| `progress` | `stage` (`download_installer`, `running_installer`, `verifying`, `updating`, `waiting_for_browser`, `code_received`, `done`), optional `percent` | show progress |
| `log` | `line` (CLI/installer output, ANSI stripped) | keep for a "details" view only |
| `open_url` | `url` | show "Continue in your browser", with a button that opens `url` |
| `need_code` | — | show a field "Paste the code from the browser"; write the code as one line to the command's **stdin** (bare, or `{"code":"…"}`) |
| `status` | as `account` (§5) | |
| `result` | `ok` (bool), `status` (object, as `account`), optional `error` `{code, message{de,en}, detail}` | finish |

After `install`, `update`, `login`, `logout` the command notifies a running daemon
(`account_changed`), so the interface also gets an `account` event. The daemon never reads,
copies or stores the owner's Claude credentials; the CLI keeps them where it always does.

## 10. Other entry points

* `kristall-assistant [--demo [--demo-auto] [--demo-loop SECONDS]] [-v]` — the daemon (systemd user
  service `kristall-assistant.service`). **Demo mode** replays a scripted session (German voice
  question → live transcript → thinking → tool activity with agent-cursor movement → permission
  prompt → streamed answer → speaking) through the real socket/state machine, with no Claude and no
  audio. Every `invoke` starts it (`text` mode plays a shorter web-search answer).
  `--demo-auto` answers the permission prompt itself after 4 s; `--demo-loop N` starts a session
  every N seconds. `KRISTALL_DEMO_SPEED` (float) speeds it up.
* `kristall-assistant-ctl` — test client: `status`, `watch [--levels]`, `ask TEXT`, `listen`,
  `cancel`, `stop-speaking`, `allow ID [--always]`, `deny ID`, `cursor X Y [--label L] [--pulse P] [--hide]`,
  `demo-error CODE`, `demo-account STATUS`, `send JSON`.

## 11. Settings (`~/.config/kristall/settings.json`, key `assistant`)

Defaults ship as `/usr/share/kristall/defaults/settings.d/50-assistant-core.json` and are layered
as `docs/contracts/settings.md` specifies; change them only with `kristall-settings set assistant.<key> <json>`.
The daemon reads all layers (it never writes) and applies changes live.

| key | default | |
|---|---|---|
| `enabled` | `true` | *(addition)* the owner uses the assistant. While true, apps start with accessibility on (hands.md §5); the Setup Assistant / settings UI offer it as the assistant's main switch. Today only hands' session parts read it; the daemon keeps running when it is false (stopping it, and hiding the interface, is not implemented yet) |
| `name` | `"Kristall"` | name shown to the owner and used by the model |
| `owner_name` | `""` | the owner's name, if known |
| `language` | `"de"` | first language (`de`/`en`); replies follow the language spoken |
| `voice` | `{"de":"de_DE-thorsten-medium","en":"en_US-joe-medium"}` | voice per language |
| `speaking_rate` | `1.0` | 0.6–1.6 |
| `input_mode` | `"voice"` | what `invoke` without `mode` does |
| `speak_replies` | `"voice_only"` | `always` \| `voice_only` \| `never` |
| `recognizer` | `"parakeet"` | `parakeet` (German + English, automatic) \| `canary-de` (German only, more accurate on German, translates other languages) |
| `wake_word` | `false` | reserved; not implemented in this version |
| `barge_in` | `"auto"` | §6 |
| `duck_other_audio` | `true` | |
| `conversation_window_seconds` | `180` | follow-ups within this time share the conversation |
| `end_of_speech_ms` | `800` | |
| `no_speech_timeout_seconds` | `7` | |
| `max_utterance_seconds` | `45` | |
| `models_unload_after_seconds` | `300` | speech models leave memory after this quiet period |
| `brain_unload_after_seconds` | `600` | the warm Claude process is closed after this quiet period (an idle `claude` process still wakes up: ~0.2 % of a core measured) |
| `permission_timeout_seconds` | `120` | |
| `model` | `"claude-haiku-5-5"` | |
| `effort` | `"low"` | Claude effort level; `low` keeps the first word under a second |

## 12. Files

| path | |
|---|---|
| `~/.local/share/kristall/assistant/workspace/` | the model's private working directory |
| `~/.local/share/kristall/assistant/memory.json` | the assistant's memory (`{"version":1,"facts":[{"id","text","at"}]}`); a settings UI may show/delete facts |
| `~/.config/kristall/assistant/permissions.json` | "always" grants (§7.1) |
| `~/.config/kristall/assistant/mcp.d/` | user tool servers (§8) |
| `/usr/share/kristall/assistant/mcp.d/` | system tool servers (§8) |
| `/usr/share/kristall/assistant/models/` | speech models |
| Logs | `journalctl --user -t kristall-assistant` |

## 13. Integration notes: shell requests around the assistant *(addition, 2026-11-16)*

Two request-bus actions (`ShellBus.request(target, action, arg, output)`, i.e.
`kristall-shellctl <target> <action> [arg] [--output NAME]`, `docs/contracts/shell.md` §5) carry
assistant traffic between shell modules. They are not part of `assistant.sock`, but they end in it:

| Target / action | `arg` | Sent by | Handled by | What happens |
|---|---|---|---|---|
| `assistant ask` | the question, plain text (empty = just open the panel) | Search ("Search or Ask": the Ask row, only while the `assistant` target is claimed) | the assistant interface (`shell/modules/assistant`) | opens the panel on `output`, shows the question as typed, and sends `invoke {"mode":"text","text":<arg>,"source":"search","context":{…}}` once connected and the account is `ready` (otherwise the panel shows the account state). The reply is a typed reply (§5.1 markup) unless `assistant.speak_replies` is `always`. |
| `setup claude-signin` | why: the `error`'s action, `sign_in` \| `install_cli` \| `update_cli` (§7.2) | the assistant interface, when the owner presses that action on an `error` (`not_signed_in`, `cli_missing`, `cli_outdated`), only while the `setup` target is claimed (otherwise it says Setup is not available) | the Setup Assistant's shell module (`shell/modules/setup`) | opens the "Sign in with Claude" step on its own (or jumps there if Setup is open); the step drives `kristall-assistant-account` (§9) and sends `account_changed`, after which the daemon emits `account`. |

Quoting: Quickshell 0.2.1's IPC argument parser (behind `kristall-shellctl`) rejects a positional
argument that starts with `-` followed by a letter (`-x`, `--foo`, "-Hallo …") unless `--` precedes
the positional arguments; negative numbers and empty strings pass. Verified 2026-11-16 in
kristall-devenv: `quickshell ipc call shell request panels focus --foo ""` fails, `… request --
panels focus --foo ""` works. Senders of free text (`assistant ask`) must therefore go through a
`kristall-shellctl` that inserts `--`, or call `ShellBus.request` in-process as Search does.
