"""Inventory, freeze, and crop hashes.

A detector count, a reference count, and a source-derived count stay separate.
Nothing here certifies completeness. Page 1 is kept when the inventory includes it.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from jurors_harness.config import RunConfig
from jurors_harness.hashing import sha256_file, sha256_text
from jurors_harness.io_util import as_bool, read_csv, read_json, write_csv, write_json

INVENTORY_FIELDS = [
    "entry_id",
    "year",
    "witness",
    "edition",
    "physical_page",
    "printed_page_label",
    "juror_class",
    "slot",
    "included",
    "exclusion_reason",
    "crop_file",
    "baseline_name",
    "baseline_occupation",
    "baseline_abode",
    "held",
    "ownership_problem",
    "scan_loss",
    "edge_contact",
    "normalization_hazard",
    "hard_reason",
]

BASELINE_FIELDS = [
    "entry_id",
    "year",
    "witness",
    "edition",
    "physical_page",
    "printed_page_label",
    "juror_class",
    "slot",
    "included",
    "exclusion_reason",
    "held",
    "ownership_problem",
    "scan_loss",
    "edge_contact",
    "normalization_hazard",
    "hard_reason",
    "name",
    "occupation",
    "abode",
    "crop_relpath",
    "crop_sha256",
]


def inventory_path(config: RunConfig) -> Path:
    return config.inputs_dir / config.inventory


def load_inventory(config: RunConfig) -> list[dict]:
    path = inventory_path(config)
    if not path.exists():
        raise FileNotFoundError(f"inventory not found: {config.inventory}")
    rows = read_csv(path)
    if not rows:
        raise ValueError("inventory is empty")
    missing = [name for name in INVENTORY_FIELDS if name not in rows[0]]
    if missing:
        raise ValueError(f"inventory missing columns: {', '.join(missing)}")
    seen: set[str] = set()
    normalized = []
    for row in rows:
        entry_id = row["entry_id"].strip()
        if not entry_id or entry_id in seen:
            raise ValueError(f"duplicate or blank entry_id: {entry_id!r}")
        seen.add(entry_id)
        if int(row["year"]) != config.year:
            raise ValueError(f"{entry_id} year does not match the run")
        if row["witness"] != config.witness or row["edition"] != config.edition:
            raise ValueError(f"{entry_id} witness or edition does not match the run")
        crop_file = row["crop_file"].strip()
        if crop_file:
            _reject_abs(crop_file)
        normalized.append(
            {
                **{key: row.get(key, "").strip() for key in INVENTORY_FIELDS},
                "entry_id": entry_id,
                "included": as_bool(row["included"]),
                "held": as_bool(row["held"]),
                "ownership_problem": as_bool(row["ownership_problem"]),
                "scan_loss": as_bool(row["scan_loss"]),
                "edge_contact": as_bool(row["edge_contact"]),
                "normalization_hazard": as_bool(row["normalization_hazard"]),
                "physical_page": int(row["physical_page"]),
                "slot": int(row["slot"]),
                "year": int(row["year"]),
            }
        )
    return normalized


def write_census(config: RunConfig, rows: list[dict]) -> dict:
    census_file = config.inputs_dir / config.census
    declared = read_json(census_file) if census_file.exists() else {}
    if not isinstance(declared, dict):
        raise ValueError("census file must be a JSON object")
    included = [row for row in rows if row["included"]]
    excluded = [row for row in rows if not row["included"]]
    reasons = Counter(row["exclusion_reason"] or "(none)" for row in excluded)
    classes = Counter(row["juror_class"] or "(blank)" for row in included)
    pages = Counter(row["physical_page"] for row in included)
    established = bool(declared.get("source_census_established", False))
    measures = declared.get("measures") or {}
    report = {
        "source_census_established": established,
        "measures": {
            "inventory_rows": len(rows),
            "included_entries": len(included),
            "excluded_entries": len(excluded),
            "detector_count": measures.get("detector_count"),
            "reference_count": measures.get("reference_count"),
            "source_derived_count": measures.get("source_derived_count"),
        },
        "note": (
            "Inventory rows, detector hits, reference counts, and source-derived counts "
            "are different measures. A reference-count proximity is not a source census."
        ),
        "qualification": (
            None
            if established
            else "Source census is not established. This freeze is the supplied inventory, not a completeness certificate."
        ),
        "exclusion_reasons": dict(reasons),
        "included_by_class": dict(classes),
        "included_by_physical_page": {str(page): pages[page] for page in sorted(pages)},
        "page_one_included_entries": pages.get(1, 0),
        "duplicate_witnesses": declared.get("duplicate_witnesses") or [],
        "supplements": declared.get("supplements") or [],
        "source_notes": declared.get("notes") or "",
    }
    dest = config.work_dir / "census"
    dest.mkdir(parents=True, exist_ok=True)
    _refuse_if_changed(dest / "CENSUS.json", report)
    write_json(dest / "CENSUS.json", report)
    frozen_rows = [{key: row[key] for key in INVENTORY_FIELDS} for row in rows]
    csv_path = dest / "INVENTORY.csv"
    if csv_path.exists():
        current = read_csv(csv_path)
        # Re-read through the same writer by comparing entry ids and inclusion flags.
        if [row["entry_id"] for row in current] != [row["entry_id"] for row in frozen_rows]:
            raise RuntimeError("refusing to overwrite a frozen inventory with a different entry list")
    write_csv(csv_path, frozen_rows, INVENTORY_FIELDS)
    manifest = [
        {
            "path": "census/CENSUS.json",
            "bytes": (dest / "CENSUS.json").stat().st_size,
            "sha256": sha256_file(dest / "CENSUS.json"),
        },
        {
            "path": "census/INVENTORY.csv",
            "bytes": csv_path.stat().st_size,
            "sha256": sha256_file(csv_path),
        },
    ]
    write_csv(dest / "MANIFEST.csv", manifest, ["path", "bytes", "sha256"])
    return report


def freeze_baseline(config: RunConfig, rows: list[dict], crops: dict[str, dict]) -> str:
    """Write the provisional baseline once. A changed hash is refused, not overwritten."""
    baseline_rows = []
    for row in rows:
        crop = crops.get(row["entry_id"], {})
        baseline_rows.append(
            {
                "entry_id": row["entry_id"],
                "year": row["year"],
                "witness": row["witness"],
                "edition": row["edition"],
                "physical_page": row["physical_page"],
                "printed_page_label": row["printed_page_label"],
                "juror_class": row["juror_class"],
                "slot": row["slot"],
                "included": row["included"],
                "exclusion_reason": row["exclusion_reason"],
                "held": row["held"],
                "ownership_problem": row["ownership_problem"],
                "scan_loss": row["scan_loss"],
                "edge_contact": row["edge_contact"],
                "normalization_hazard": row["normalization_hazard"],
                "hard_reason": row["hard_reason"],
                "name": row["baseline_name"],
                "occupation": row["baseline_occupation"],
                "abode": row["baseline_abode"],
                "crop_relpath": crop.get("crop_relpath", ""),
                "crop_sha256": crop.get("crop_sha256", ""),
            }
        )
    dest_dir = config.work_dir / "baseline"
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / "BASELINE.csv"
    if dest.exists():
        existing_hash = sha256_file(dest)
        # Write to a sibling and compare so we never clobber a frozen file.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            trial = Path(tmp) / "BASELINE.csv"
            write_csv(trial, baseline_rows, BASELINE_FIELDS)
            new_hash = sha256_file(trial)
        if new_hash != existing_hash:
            raise RuntimeError(
                "refusing to overwrite frozen baseline "
                f"(existing {existing_hash}, new {new_hash}). Use a new run directory."
            )
        return existing_hash
    write_csv(dest, baseline_rows, BASELINE_FIELDS)
    digest = sha256_file(dest)
    write_csv(
        dest_dir / "BASELINE-MANIFEST.csv",
        [{"path": "baseline/BASELINE.csv", "bytes": dest.stat().st_size, "sha256": digest}],
        ["path", "bytes", "sha256"],
    )
    return digest


def hash_crops(config: RunConfig, rows: list[dict]) -> list[dict]:
    indexed = []
    for row in rows:
        rel = row["crop_file"]
        record = {
            "entry_id": row["entry_id"],
            "included": row["included"],
            "crop_relpath": rel,
            "crop_sha256": "",
            "bytes": 0,
            "sha_ok": False,
            "gap": "",
        }
        if not row["included"]:
            record["gap"] = ""
            indexed.append(record)
            continue
        if not rel:
            record["gap"] = "included entry has no crop path"
            indexed.append(record)
            continue
        path = config.inputs_dir / rel
        if not path.exists() or not path.is_file():
            record["gap"] = "crop file missing"
            indexed.append(record)
            continue
        digest = sha256_file(path)
        record.update(crop_sha256=digest, bytes=path.stat().st_size, sha_ok=True, gap="")
        indexed.append(record)
    dest = config.work_dir / "crops"
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(
        dest / "CROP-INDEX.csv",
        indexed,
        ["entry_id", "included", "crop_relpath", "crop_sha256", "bytes", "sha_ok", "gap"],
    )
    return indexed


def load_frozen_rows(config: RunConfig) -> list[dict]:
    path = config.work_dir / "baseline" / "BASELINE.csv"
    rows = read_csv(path)
    parsed = []
    for row in rows:
        parsed.append(
            {
                **row,
                "year": int(row["year"]),
                "physical_page": int(row["physical_page"]),
                "slot": int(row["slot"]),
                "included": as_bool(row["included"]),
                "held": as_bool(row["held"]),
                "ownership_problem": as_bool(row["ownership_problem"]),
                "scan_loss": as_bool(row["scan_loss"]),
                "edge_contact": as_bool(row["edge_contact"]),
                "normalization_hazard": as_bool(row["normalization_hazard"]),
                "baseline_name": row["name"],
                "baseline_occupation": row["occupation"],
                "baseline_abode": row["abode"],
                "entry_id": row["entry_id"],
            }
        )
    return parsed


def _refuse_if_changed(path: Path, obj: dict) -> None:
    if not path.exists():
        return
    import json

    new = json.dumps(obj, ensure_ascii=False, indent=2, sort_keys=True)
    old = json.dumps(read_json(path), ensure_ascii=False, indent=2, sort_keys=True)
    if sha256_text(new) != sha256_text(old):
        raise RuntimeError(f"refusing to overwrite frozen {path.name}")


def _reject_abs(value: str) -> None:
    if value.startswith("/") or (len(value) > 2 and value[1] == ":"):
        raise ValueError(f"absolute crop path is not allowed: {value}")
