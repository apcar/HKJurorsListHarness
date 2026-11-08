"""Content identity: SHA-256 and Unicode NFC. Paths stay relative."""

from __future__ import annotations

import hashlib
import unicodedata
from pathlib import Path


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_text(text: str) -> str:
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def nfc(text: str | None) -> str:
    return unicodedata.normalize("NFC", text or "")


def reject_absolute(path: Path, *, label: str) -> None:
    if path.is_absolute():
        raise ValueError(
            f"{label} must be a relative path; absolute paths are rejected so "
            "machine-specific locations never enter manifests"
        )
