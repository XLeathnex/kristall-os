# assistant-ui — the face of the assistant (`shell/modules/assistant/`)

A Kristall shell module (Quickshell/QML, contract: `docs/contracts/shell.md`) that makes the
assistant daemon (`docs/contracts/assistant-ipc.md`) visible: the **crystal light** around the
screen edge, the **glass panel** that grows from a listening capsule into a conversation, the
assistant's **own cursor** (`docs/contracts/hands.md` §8), invocation and push-to-talk.

```
Module.qml           controller: invocation (ShellBus target "assistant"), panel session, notices, push-to-talk
AssistantClient.qml  assistant.sock client: model rebuilt from every snapshot, reconnect (helper inotify / backoff)
EdgeLight.qml        the light of one output: state palettes, fade, frame clock (≤ 60 updates/s, 30 on battery)
LightStrip.qml       one edge surface (top/bottom carry the corners) + shaders/edgelight.frag; plain glow fallback
Panel.qml            panel surface (Top layer; Overlay over full screen) + click catcher; glass morph
PanelBody.qml        compact capsule / conversation / footer field; Orb, ReplyText (+Markdown.js), ActivityLine,
                     PermissionCard, NoticeCard, MicBadge
AgentCursor.qml      the cursor surface (moved by layer-shell margins), clock-anchored glides, ripples, label pill
AssistantTestHooks   IPC target "assistant-test" (KRISTALL_SHELL_TEST=1 only)
image/               install.sh, settings.json (defaults for assistant.ui)
kglobalaccel/        org.kristall.assistant.desktop (Alt+Space and the Copilot key Meta+Shift+F23)
tools/gen-shaders.sh rebuilds shaders/*.qsb (committed; the image needs no shader compiler)
tests/               run.sh, test_assistant.py, support.py, evidence/
```

Requests: `kristall-shellctl assistant invoke bar|shortcut|search` (shortcut while listening = done
talking; the bar button toggles), `assistant ask "<text>"` (Search's hand-off: a typed question,
panel open), `assistant dismiss|show|toggle`. Settings (`assistant.ui`): `light.enabled`,
`light.intensity` (0–1), `light.maxFps`, `light.cornerRadius`, `holdMs`.

## Surfaces (all click-through except the panel; all excluded by the bridge's `excludeShell`)

| namespace | layer | input | mapped while |
|---|---|---|---|
| `kristall-assistant-light-{top,bottom,left,right}` | Overlay | none | the light is visible or fading |
| `kristall-assistant-cursor` | Overlay | none | the cursor is shown or fading |
| `kristall-assistant-panel` | Top (Overlay if a full-screen window is in front) | the glass only; keyboard exclusive | the panel is open |
| `kristall-assistant-catcher` | Top | full output (a click dismisses) | the panel is open |

The panel lives on the Top layer on purpose: KWin raises a layer surface when it activates it, and
the cursor and light must stay above the panel.

## Build and test (dev container)

```sh
docker run --rm -v "$PWD":/work -w /work kristall-devenv:latest shell/modules/assistant/tests/run.sh [section…]
```

Sections: `shortcut static demo pointer errors ask typing robust idle cost timing scale looks fallback realbridge`.
The daemon runs from `assistant/core` in demo mode (Python + numpy are in the container), the owner
types and clicks through KWin's fake-input protocol (the bridge suite's `owner` client), `realbridge`
runs the real bridge plugin with the real `kristall-hands` clicking. Numbers: `tests/evidence/results.json`.

## Known limits

Not verifiable here: real microphone/speech-driven motion, GPU cost at 120 Hz on Iris Xe, the
KRunner Alt+Space hand-over in `/etc/xdg/kglobalshortcutsrc` on a real Plasma session. Push-to-talk:
kglobalaccel runs desktop-file shortcuts on press only and signals no release on D-Bus (verified with
KWin 6.8.3 in the dev container); holding works once something that sees the release sends
`kristall-shellctl assistant release` (a request for shell-core's helper). The light's shader runs only with a
GPU scene graph; Qt Quick's software renderer gets a still gradient glow.
