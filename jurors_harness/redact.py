"""Strip credential material before it can reach a ledger, prompt, or traceback."""

from __future__ import annotations

import os
import re

_KEY_ENV_NAMES = (
    "OPENROUTER_API_KEY",
    "GEMINI_API_KEY",
    "GOOGLE_API_KEY",
    "ANTHROPIC_API_KEY",
)

_TOKEN = re.compile(
    r"(?:sk-"
    + r"(?:or|ant)-[A-Za-z0-9_\-]{8,}"
    + r"|AIza[0-9A-Za-z_\-]{10,}"
    + r"|AKIA[0-9A-Z]{16})"
)


def secret_values(extra_names: tuple[str, ...] = ()) -> list[str]:
    found: list[str] = []
    for name in _KEY_ENV_NAMES + extra_names:
        value = os.environ.get(name, "")
        if len(value) >= 8:
            found.append(value)
    return found


def redact(text: str | None, *, extra_names: tuple[str, ...] = ()) -> str:
    if not text:
        return ""
    cleaned = text
    for value in secret_values(extra_names):
        cleaned = cleaned.replace(value, "[REDACTED]")
    cleaned = _TOKEN.sub("[REDACTED]", cleaned)
    cleaned = cleaned.replace("Bearer ", "Bearer [REDACTED] ")
    return cleaned
