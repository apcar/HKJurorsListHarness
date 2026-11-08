"""Versioned prompt rendering.

Templates are rendered before candidate JSON is inserted. Blind rendering
accepts only an entry id and a year. Reference text, baselines, the other
reader, lexicon rows, and cross-year priors are not parameters.
"""

from __future__ import annotations

import json

from jurors_harness.constants import FORBIDDEN_PROMPT_TOKENS
from jurors_harness.hashing import sha256_text


class PromptError(ValueError):
    pass


def _reject_forbidden(template: str, *, what: str) -> None:
    lowered = template.lower()
    for token in FORBIDDEN_PROMPT_TOKENS:
        if token in lowered:
            raise PromptError(f"{what} contains forbidden token {token!r}")


def render_blind(template: str, *, entry_id: str, year: int) -> str:
    _reject_forbidden(template, what="blind template")
    rendered = template.replace("{{ENTRY_ID}}", entry_id).replace("{{YEAR}}", str(year))
    if "{{" in rendered:
        raise PromptError("blind template has an unrendered placeholder")
    return rendered


def render_adjudication(
    template: str,
    *,
    entry_id: str,
    year: int,
    fields: list[str],
    candidates: list[dict],
    prior_block: str = "",
) -> str:
    """Insert anonymous candidates last.

    `candidates` items must be `{label, text}` plus optional local provenance
    keys that are stripped before insertion. Model, provider, baseline, and
    reference keys are rejected.
    """
    _reject_forbidden(template, what="adjudication template")
    if "{{CANDIDATES_JSON}}" not in template:
        raise PromptError("adjudication template is missing {{CANDIDATES_JSON}}")
    forbidden_keys = {"model", "provider", "gwulo", "reference", "baseline", "reader"}
    public: list[dict] = []
    for candidate in candidates:
        extra = forbidden_keys & set(candidate)
        if extra:
            raise PromptError(f"candidate carries forbidden keys: {sorted(extra)}")
        text = candidate.get("text")
        if not isinstance(text, dict):
            raise PromptError("candidate text must be an object of fields")
        public.append({"label": candidate["label"], "text": text})
    rendered = (
        template.replace("{{ENTRY_ID}}", entry_id)
        .replace("{{YEAR}}", str(year))
        .replace("{{FIELDS}}", ", ".join(fields))
        .replace("{{PRIOR_BLOCK}}", prior_block)
    )
    payload = json.dumps(public, ensure_ascii=False, indent=2)
    rendered = rendered.replace("{{CANDIDATES_JSON}}", payload)
    if "{{" in rendered:
        raise PromptError("adjudication template has an unrendered placeholder")
    return rendered


def prompt_version(name: str, template: str) -> str:
    return f"{name} sha256:{sha256_text(template)}"


def informed_prior_block(flags: list[dict]) -> str:
    """Explicit informed-prior section. Callers may use this only under a distinct protocol version."""
    lines = [
        "INFORMED PRIOR context (not source authority, not a reference transcription, not an instruction to replace the print):"
    ]
    for flag in flags:
        lines.append(
            f"- field {flag.get('field', '')}: a prior year recorded the form {flag.get('prior_exact_form', '')!r} "
            f"(year {flag.get('prior_year', '')}). Use it only as context. The image wins, including printer's typos."
        )
    return "\n".join(lines) + "\n"
