"""Printer's-typo lexicon and cross-year name flags.

Both are indexes of observed possibilities. They never settle a transcription
and they are not inserted into blind prompts. Alias keys exist for search only.
"""

from __future__ import annotations

import unicodedata

from jurors_harness.hashing import nfc


def alias_key(text: str) -> str:
    """Search alias. Not a diplomatic equality test and not a correction."""
    decomposed = unicodedata.normalize("NFKD", nfc(text))
    stripped = "".join(char for char in decomposed if not unicodedata.combining(char))
    pieces: list[str] = []
    for char in stripped.casefold():
        if char.isalnum():
            pieces.append(char)
        else:
            pieces.append(" ")
    return " ".join("".join(pieces).split())


def lexicon_flags(field_text: str, lexicon_rows: list[dict]) -> list[dict]:
    """Flag when an exact printed lexicon form occurs in a field. Substring, NFC, case-sensitive."""
    haystack = nfc(field_text)
    found = []
    for row in lexicon_rows:
        form = nfc(row.get("exact_form", ""))
        if len(form) < 2:
            continue
        if form and form in haystack:
            found.append(
                {
                    "exact_form": form,
                    "normalized_alias": row.get("normalized_alias") or alias_key(form),
                    "lexicon_version": row.get("lexicon_version", ""),
                    "evidence_source": row.get("evidence_source", ""),
                    "match": "exact-form",
                }
            )
    return found


def carryover_flags(field_text: str, prior_rows: list[dict], *, field: str) -> list[dict]:
    """Flag alias matches against other years. The match is not identity and not a reading."""
    key = alias_key(field_text)
    if not key:
        return []
    found = []
    for row in prior_rows:
        if row.get("field") and row["field"] != field:
            continue
        prior_alias = row.get("normalized_alias") or alias_key(row.get("exact_form", ""))
        if prior_alias and prior_alias == key:
            found.append(
                {
                    "field": field,
                    "prior_year": row.get("year", ""),
                    "prior_witness": row.get("witness", ""),
                    "prior_exact_form": row.get("exact_form", ""),
                    "normalized_alias": prior_alias,
                    "note": "flag only; not identity and not source text",
                }
            )
    return found


def public_flag(flag: dict, *, include_text: bool) -> dict:
    """Drop prior/lexicon strings unless an explicit export switch keeps them."""
    if include_text:
        return dict(flag)
    hidden = {"exact_form", "prior_exact_form", "normalized_alias"}
    return {key: value for key, value in flag.items() if key not in hidden}
