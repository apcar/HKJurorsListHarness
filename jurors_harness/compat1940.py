"""Checks for an externally supplied 1940 RC1. This repository does not contain that edition."""

from __future__ import annotations

import csv
from pathlib import Path

from jurors_harness.constants import RC1_BASELINE_SHA256, RC1_CSV_SHA256, RC1_DISPOSITIONS, RC1_ROWS
from jurors_harness.hashing import sha256_file


def verify_1940(csv_path: Path, baseline_path: Path | None = None, dispositions_path: Path | None = None) -> dict:
    """Compare supplied files with the frozen RC1 constants. No network."""
    problems = []
    digest = sha256_file(csv_path)
    if digest != RC1_CSV_SHA256:
        problems.append("release csv sha256 does not match 1940 RC1")
    with csv_path.open(encoding="utf-8", newline="") as handle:
        rows = list(csv.DictReader(handle))
    if len(rows) != RC1_ROWS:
        problems.append(f"row count {len(rows)} != {RC1_ROWS}")
    if baseline_path is not None:
        if sha256_file(baseline_path) != RC1_BASELINE_SHA256:
            problems.append("baseline sha256 does not match 1940 RC1")
    if dispositions_path is not None:
        with dispositions_path.open(encoding="utf-8", newline="") as handle:
            dispositions = list(csv.DictReader(handle))
        counts: dict[str, int] = {}
        for row in dispositions:
            key = (row.get("disposition") or "").strip().lower()
            counts[key] = counts.get(key, 0) + 1
        for name, expected in RC1_DISPOSITIONS.items():
            if counts.get(name) != expected:
                problems.append(f"disposition {name} is {counts.get(name)} not {expected}")
    return {"passed": not problems, "problems": problems, "csv_sha256": digest, "rows": len(rows)}
