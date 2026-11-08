"""Deterministic release rebuild. Standard library only. No network and no model calls."""

from __future__ import annotations

import csv
from pathlib import Path

from jurors_harness.hashing import sha256_file
from jurors_harness.io_util import read_csv

RELEASE_COLUMNS = [
    "entry_id",
    "version",
    "year",
    "witness",
    "edition",
    "physical_page",
    "printed_page_label",
    "juror_class",
    "included",
    "name",
    "occupation",
    "abode",
    "disposition",
    "uncertain_fields",
    "uncertainty_reasons",
    "method",
    "evidence_level",
    "operational_state",
    "crop_relpath",
    "crop_sha256",
]


def build_release_csv(rcdir: Path, dest: Path) -> str:
    """Write a new CSV. `dest` must not exist. Returns the SHA-256 of the bytes written."""
    if dest.exists():
        raise FileExistsError(f"refusing to overwrite {dest}")
    baseline = read_csv(rcdir / "inputs" / "BASELINE.csv")
    dispositions = {row["entry_id"]: row for row in read_csv(rcdir / "DISPOSITIONS.csv")}
    overlay = {
        (row["entry_id"], row["field"]): row["release_text"]
        for row in read_csv(rcdir / "OVERLAY.csv")
    }
    if len(baseline) != len(dispositions):
        raise ValueError("baseline and dispositions name different rows")
    ids = [row["entry_id"] for row in baseline]
    if len(ids) != len(set(ids)):
        raise ValueError("baseline entry ids are not unique")
    missing = [entry_id for entry_id in ids if entry_id not in dispositions]
    if missing:
        raise ValueError("dispositions do not cover the baseline")
    dest.parent.mkdir(parents=True, exist_ok=True)
    with dest.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=RELEASE_COLUMNS, lineterminator="\n")
        writer.writeheader()
        for row in sorted(baseline, key=lambda item: item["entry_id"]):
            entry_id = row["entry_id"]
            decision = dispositions[entry_id]
            values = {
                field: overlay.get((entry_id, field), row[field])
                for field in ("name", "occupation", "abode")
            }
            writer.writerow(
                {
                    "entry_id": entry_id,
                    "version": rcdir.name,
                    "year": row["year"],
                    "witness": row["witness"],
                    "edition": row["edition"],
                    "physical_page": row["physical_page"],
                    "printed_page_label": row["printed_page_label"],
                    "juror_class": row["juror_class"],
                    "included": row["included"],
                    "name": values["name"],
                    "occupation": values["occupation"],
                    "abode": values["abode"],
                    "disposition": decision["disposition"],
                    "uncertain_fields": decision["uncertain_fields"],
                    "uncertainty_reasons": decision["uncertainty_reasons"],
                    "method": decision["method"],
                    "evidence_level": decision["evidence_level"],
                    "operational_state": decision["operational_state"],
                    "crop_relpath": row["crop_relpath"],
                    "crop_sha256": row["crop_sha256"],
                }
            )
    return sha256_file(dest)


def verify_release(rcdir: Path) -> dict:
    """Rebuild beside the release and compare bytes. Does not contact the network."""
    original = rcdir / f"{rcdir.name}.csv"
    if not original.exists():
        raise FileNotFoundError(original.name)
    dest = rcdir / f"{rcdir.name}.replayed.csv"
    if dest.exists():
        dest.unlink()
    digest = build_release_csv(rcdir, dest)
    same = dest.read_bytes() == original.read_bytes()
    result = {
        "passed": same,
        "replay_sha256": digest,
        "release_sha256": sha256_file(original),
        "byte_equal": same,
    }
    recorded = rcdir / "REPLAY-RESULT.json"
    if recorded.exists():
        import json

        saved = json.loads(recorded.read_text(encoding="utf-8"))
        result["matches_recorded_sha256"] = saved.get("release_sha256") == sha256_file(original)
        result["passed"] = bool(result["passed"] and result["matches_recorded_sha256"])
    return result
