"""Literal comparison. Unicode NFC only. Punctuation, accents, and marks count."""

from __future__ import annotations

import re
import unicodedata

from jurors_harness.hashing import nfc

_PUNCT = re.compile(r"[.,;:!?]")
_ABBREV_DOT = re.compile(r"\b[A-Za-z]{1,4}\.")
_ILLEGIBLE = re.compile(r"\[\?\]|\[illegible\]|\[UNRESOLVED\]")


def strict_equal(left: str | None, right: str | None) -> bool:
    return nfc(left) == nfc(right)


def fields_equal(left: dict, right: dict, fields: tuple[str, ...] | list[str]) -> bool:
    return all(strict_equal(left.get(field), right.get(field)) for field in fields)


def strip_marks(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(char for char in decomposed if not unicodedata.combining(char))


def alnum_key(text: str) -> str:
    """Case-folded letters and digits only. Used for practical class, never to settle a line."""
    return "".join(char for char in strip_marks(nfc(text)).casefold() if char.isalnum())


def practical_class(left: str, right: str) -> str:
    """Meaningful if letters/digits or asterisk/dagger counts differ; else literal-only."""
    if strict_equal(left, right):
        return "identical"
    meaningful_marks = ("*", "†", "‡")
    if alnum_key(left) != alnum_key(right):
        return "meaningful"
    if any(left.count(mark) != right.count(mark) for mark in meaningful_marks):
        return "meaningful"
    return "literal-only"


def difference_kinds(left: str, right: str) -> list[str]:
    """Classify a strict difference. Empty when the NFC strings are equal."""
    a = nfc(left)
    b = nfc(right)
    if a == b:
        return []
    kinds: list[str] = []
    if " ".join(a.split()) == " ".join(b.split()):
        kinds.append("line-break/whitespace")
        return kinds
    a2, b2 = " ".join(a.split()), " ".join(b.split())
    if a2.replace("\u2019", "'").replace("\u2018", "'") == b2.replace("\u2019", "'").replace("\u2018", "'"):
        kinds.append("apostrophe-form")
        return kinds
    if strip_marks(a2) == strip_marks(b2):
        kinds.append("accent")
        return kinds
    if a2.casefold() == b2.casefold():
        kinds.append("case")
        return kinds
    if _PUNCT.sub("", a2) == _PUNCT.sub("", b2):
        kinds.append("abbrev-dot" if _ABBREV_DOT.search(a2) or _ABBREV_DOT.search(b2) else "punctuation")
        return kinds
    if alnum_key(a2) == alnum_key(b2):
        kinds.append("punctuation/mark")
        return kinds
    kinds.append("letter/word")
    return kinds


def has_illegible_marker(text: str) -> bool:
    return bool(_ILLEGIBLE.search(text or ""))


def risk_features(
    texts: list[str],
    *,
    edge_contact: bool = False,
    normalization_hazard: bool = False,
) -> list[str]:
    """Reader/source risk features. These route a sample stratum; they do not edit text."""
    features: set[str] = set()
    blob = "\n".join(texts)
    if strip_marks(blob) != blob or any(unicodedata.combining(char) for char in unicodedata.normalize("NFKD", blob)):
        # Accent if a combining mark is present in NFKD, or the string itself carries a non-ascii letter.
        if any(unicodedata.category(char) == "Mn" for char in unicodedata.normalize("NFKD", blob)):
            features.add("accent")
    if _ABBREV_DOT.search(blob):
        features.add("abbrev-dot")
    if any(mark in blob for mark in ("*", "†", "‡")):
        features.add("meaningful-mark")
    if edge_contact:
        features.add("edge-contact")
    if normalization_hazard or re.search(r"\bLd\.", blob):
        features.add("normalization-hazard")
    return sorted(features)


def levenshtein(left: str, right: str) -> int:
    a = nfc(left)
    b = nfc(right)
    if a == b:
        return 0
    if not a:
        return len(b)
    if not b:
        return len(a)
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        current = [i]
        for j, cb in enumerate(b, 1):
            current.append(min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]
