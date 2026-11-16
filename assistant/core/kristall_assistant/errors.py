# SPDX-License-Identifier: GPL-3.0-or-later
"""Owner-facing error states.

Every failure the owner can meet is one of these codes, with a short message in
German and English and an optional ``action`` the interface can offer as a
button.  Nothing here ever contains a stack trace or a secret.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ErrorSpec:
    de: str
    en: str
    retryable: bool = True
    action: str | None = None      # "sign_in" | "install_cli" | "update_cli" | "open_sound_settings" | None


ERRORS: dict[str, ErrorSpec] = {
    "cli_missing": ErrorSpec(
        "Ich bin noch nicht eingerichtet. Melde dich einmal mit deinem Claude-Konto an, dann kann ich loslegen.",
        "I'm not set up yet. Sign in once with your Claude account and I'm ready.",
        retryable=False, action="install_cli"),
    "cli_outdated": ErrorSpec(
        "Claude muss kurz aktualisiert werden, bevor ich weitermachen kann.",
        "Claude needs a quick update before I can continue.",
        retryable=False, action="update_cli"),
    "not_signed_in": ErrorSpec(
        "Du bist nicht mehr bei Claude angemeldet. Melde dich bitte wieder an.",
        "You're no longer signed in to Claude. Please sign in again.",
        retryable=False, action="sign_in"),
    "credit_exhausted": ErrorSpec(
        "Dein Claude-Kontingent für mich ist für diesen Zeitraum aufgebraucht. {when}",
        "Your Claude allowance for me is used up for now. {when}",
        retryable=False),
    "rate_limited": ErrorSpec(
        "Gerade kamen zu viele Anfragen auf einmal. {when}",
        "Too many requests just now. {when}",
        retryable=True),
    "overloaded": ErrorSpec(
        "Claude ist gerade stark ausgelastet. Versuch es bitte gleich noch einmal.",
        "Claude is very busy right now. Please try again in a moment.",
        retryable=True),
    "offline": ErrorSpec(
        "Ich habe gerade keine Internetverbindung. Sobald du wieder online bist, bin ich da.",
        "I don't have an internet connection right now. I'll be back as soon as you're online.",
        retryable=True),
    "refused": ErrorSpec(
        "Dabei kann ich leider nicht helfen.",
        "I'm sorry, I can't help with that.",
        retryable=False),
    "service_error": ErrorSpec(
        "Bei Claude ist gerade etwas schiefgelaufen. Versuch es bitte noch einmal.",
        "Something went wrong on Claude's side. Please try again.",
        retryable=True),
    "brain_crashed": ErrorSpec(
        "Ich musste mich kurz neu starten. Frag mich bitte noch einmal.",
        "I had to restart for a moment. Please ask me again.",
        retryable=True),
    "timeout": ErrorSpec(
        "Das hat zu lange gedauert, ich habe abgebrochen.",
        "That took too long, so I stopped.",
        retryable=True),
    "mic_unavailable": ErrorSpec(
        "Ich kann kein Mikrofon finden. Du kannst mir aber gern schreiben.",
        "I can't find a microphone. You can type to me instead.",
        retryable=False, action="open_sound_settings"),
    "audio_output_unavailable": ErrorSpec(
        "Ich kann gerade nichts abspielen. Meine Antworten zeige ich dir als Text.",
        "I can't play sound right now, so I'll show my answers as text.",
        retryable=False, action="open_sound_settings"),
    "speech_models_missing": ErrorSpec(
        "Die Spracherkennung ist nicht installiert. Du kannst mir aber schreiben.",
        "Speech recognition isn't installed. You can type to me instead.",
        retryable=False),
    "nothing_heard": ErrorSpec(
        "Ich habe nichts gehört.",
        "I didn't hear anything.",
        retryable=True),
    "busy": ErrorSpec(
        "Einen Moment, ich bin noch mit etwas anderem beschäftigt.",
        "One moment, I'm still busy with something else.",
        retryable=True),
    "internal": ErrorSpec(
        "Da ist bei mir etwas schiefgelaufen. Versuch es bitte noch einmal.",
        "Something went wrong on my side. Please try again.",
        retryable=True),
}


@dataclass
class AssistantError(Exception):
    code: str
    detail: str = ""                     # for the log only; never shown to the owner
    params: dict[str, Any] = field(default_factory=dict)

    def __str__(self) -> str:            # pragma: no cover - logging helper
        return f"{self.code}: {self.detail}"


def _when_text(lang: str, resets_at: float | None) -> str:
    if not resets_at:
        return "Versuch es bitte später noch einmal." if lang == "de" else "Please try again later."
    import datetime as _dt
    t = _dt.datetime.fromtimestamp(resets_at)
    now = _dt.datetime.now()
    if t.date() == now.date():
        s = t.strftime("%H:%M")
        return f"Ab {s} Uhr geht es wieder." if lang == "de" else f"It works again from {s}."
    if lang == "de":
        return f"Ab {t.day}.{t.month}. um {t.strftime('%H:%M')} Uhr geht es wieder."
    return f"It works again from {t.strftime('%b %d, %H:%M')}."


def error_event(code: str, turn_id: str | None = None, *, resets_at: float | None = None) -> dict[str, Any]:
    spec = ERRORS.get(code) or ERRORS["internal"]
    if code not in ERRORS:
        code = "internal"
    msg = {
        "de": spec.de.format(when=_when_text("de", resets_at)).strip(),
        "en": spec.en.format(when=_when_text("en", resets_at)).strip(),
    }
    ev: dict[str, Any] = {
        "type": "error", "code": code, "message": msg,
        "retryable": spec.retryable, "action": spec.action, "turn_id": turn_id,
    }
    if resets_at:
        ev["resets_at"] = int(resets_at)
    return ev
