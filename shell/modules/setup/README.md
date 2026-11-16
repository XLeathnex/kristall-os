# setup — the Setup Assistant (Kristall shell module)

Owned by the `setup` component (`setup/`); interface in `docs/contracts/setup.md`, tests and evidence
in `setup/tests/`. Installed by `setup/image/install.sh` (which runs `image/install.sh` here).

```
Module.qml          state machine, requests (ShellBus "setup": start, claude-signin, close), resume, live check
SetupWindow.qml     one full-output Overlay surface per output; the welcome artwork or a glass card
Step*.qml           one question each (StepBase: title, sentence, Continue/Back/secondary)
AccountFlow.qml     "Sign in with Claude" through kristall-assistant-account
MicCheck.qml        microphone check through assistant.sock
SetupHelper.qml     kristall-setup-helper, kristall-power, apps status, keyboard plugin status
Backdrop, Crystal, MiniDesktop                       our own drawings (no images)
SetupTestHooks.qml  IPC target "setuptest" (KRISTALL_SHELL_TEST=1)
```

The binding-safe controls (`KToggle`, `KSlider`, `KSegmented`), `Spinner`, `ChoiceTile` and `Keycap` are in shell-core (`qs.core`, design.md §11).
