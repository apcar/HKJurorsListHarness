"""Strict comparison, stratified sample, and one deduplicated adjudication queue."""

from __future__ import annotations

import random
from pathlib import Path

from jurors_harness.compare import difference_kinds, fields_equal, practical_class, risk_features, strict_equal
from jurors_harness.config import RunConfig
from jurors_harness.constants import INCOMPLETE_COVERAGE, STRATA
from jurors_harness.decisions import field_needs_queue, reading_usable
from jurors_harness.io_util import read_csv, read_jsonl, write_csv, write_json
from jurors_harness.learning import carryover_flags, lexicon_flags
from jurors_harness.order import counterbalance
from jurors_harness.parsing import parse_reading

COMPARE_FIELDS = [
    "entry_id",
    "field",
    "reader_a",
    "reader_b",
    "equal",
    "kinds",
    "practical_class",
]


def readings_from_ledger(rows: list[dict], fields: list[str]) -> dict[str, dict[str, dict]]:
    """Latest successful reading per entry and stage. The ledger stays the source."""
    found: dict[str, dict[str, dict]] = {}
    for row in rows:
        if row.get("step") not in {"reader_a", "reader_b"} or row.get("outcome") != "ok":
            continue
        parsed = row.get("parsed")
        entry_id = row.get("line_id")
        if not isinstance(parsed, dict) or not entry_id:
            continue
        normalized = parse_reading(parsed, fields, entry_id)
        if normalized is None:
            continue
        found.setdefault(entry_id, {})[row["step"]] = normalized
    return found


def compare_entries(config: RunConfig, entries: list[dict], readings: dict[str, dict[str, dict]]) -> list[dict]:
    rows = []
    for entry in entries:
        if not entry["included"]:
            continue
        pair = readings.get(entry["entry_id"], {})
        left = pair.get("reader_a")
        right = pair.get("reader_b")
        for field in config.fields:
            a = "" if not left else left.get(field, "")
            b = "" if not right else right.get(field, "")
            if left is None or right is None:
                kinds = ["NO READING"]
                equal = False
                practical = "unresolved"
            elif strict_equal(a, b):
                kinds = []
                equal = True
                practical = "identical"
            else:
                kinds = difference_kinds(a, b)
                equal = False
                practical = practical_class(a, b)
            rows.append(
                {
                    "entry_id": entry["entry_id"],
                    "field": field,
                    "reader_a": a,
                    "reader_b": b,
                    "equal": equal,
                    "kinds": "|".join(kinds),
                    "practical_class": practical,
                }
            )
    dest = config.work_dir / "compare"
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(dest / "COMPARISON.csv", rows, COMPARE_FIELDS)
    return rows


def entry_status(config: RunConfig, entry: dict, readings: dict[str, dict]) -> dict:
    pair = readings.get(entry["entry_id"], {})
    left = pair.get("reader_a")
    right = pair.get("reader_b")
    usable_left = reading_usable(left, config.fields, entry["entry_id"])
    usable_right = reading_usable(right, config.fields, entry["entry_id"])
    queued = [field for field in config.fields if field_needs_queue(entry, left, right, field, config.fields)]
    agreed = bool(usable_left and usable_right and left and right and fields_equal(left, right, config.fields))
    texts = []
    for reading in (left, right):
        if reading:
            texts.extend(str(reading.get(field, "")) for field in config.fields)
    features = risk_features(
        texts,
        edge_contact=bool(entry.get("edge_contact")),
        normalization_hazard=bool(entry.get("normalization_hazard")),
    )
    if entry.get("held") or entry.get("scan_loss") or entry.get("ownership_problem"):
        stratum = "held_or_source_loss"
    elif not usable_left or not usable_right:
        stratum = INCOMPLETE_COVERAGE
    elif not agreed:
        stratum = "reader_disagreement"
    elif features:
        stratum = "agreement_with_risk"
    else:
        stratum = "other_agreement"
    return {
        "queued_fields": queued,
        "stratum": stratum,
        "risk_features": features,
        "literal_agreement": agreed and not queued,
    }


def assign_sample(config: RunConfig, entries: list[dict], readings: dict) -> list[dict]:
    """Freeze a sample before adjudication. An existing frame with the same seed is kept."""
    dest = config.work_dir / "sample" / "SAMPLE-FRAME.csv"
    if dest.exists():
        return read_csv(dest)
    statuses = {}
    populations: dict[str, list[str]] = {name: [] for name in (*STRATA, INCOMPLETE_COVERAGE)}
    for entry in entries:
        if not entry["included"]:
            continue
        status = entry_status(config, entry, readings)
        statuses[entry["entry_id"]] = status
        populations[status["stratum"]].append(entry["entry_id"])
    rng = random.Random(config.sample_seed)
    chosen: dict[str, set[str]] = {}
    meta: dict[str, dict] = {}
    for stratum in STRATA:
        pop = sorted(populations[stratum])
        requested = config.sample_allocations[stratum]
        n = min(requested, len(pop))
        pick = set(pop if n == len(pop) else rng.sample(pop, n))
        chosen[stratum] = pick
        for entry_id in pop:
            meta[entry_id] = {
                "N": len(pop),
                "n": n,
                "inclusion_prob": (n / len(pop)) if pop else 0,
                "weight": (len(pop) / n) if n else 0,
                "in_sample": entry_id in pick,
                "census": n == len(pop),
            }
    for entry_id in populations[INCOMPLETE_COVERAGE]:
        meta[entry_id] = {
            "N": len(populations[INCOMPLETE_COVERAGE]),
            "n": 0,
            "inclusion_prob": 0,
            "weight": 0,
            "in_sample": False,
            "census": False,
        }
    frame = []
    for entry in entries:
        if not entry["included"]:
            continue
        status = statuses[entry["entry_id"]]
        info = meta[entry["entry_id"]]
        frame.append(
            {
                "entry_id": entry["entry_id"],
                "stratum": status["stratum"],
                "N_stratum": info["N"],
                "n_stratum": info["n"],
                "inclusion_prob": f"{info['inclusion_prob']:.6f}",
                "weight": f"{info['weight']:.6f}" if info["n"] else "",
                "in_sample": info["in_sample"],
                "census_stratum": info["census"],
                "risk_features": "|".join(status["risk_features"]),
                "sample_seed": config.sample_seed,
            }
        )
    hard = []
    seen: set[str] = set()
    for entry in entries:
        reason = (entry.get("hard_reason") or "").strip()
        if not reason or entry["entry_id"] in seen:
            continue
        seen.add(entry["entry_id"])
        hard.append(
            {
                "entry_id": entry["entry_id"],
                "hard_reason": reason,
                "also_in_probability_sample": entry["entry_id"] in {row["entry_id"] for row in frame if row["in_sample"]},
            }
        )
    dest.parent.mkdir(parents=True, exist_ok=True)
    write_csv(
        dest,
        frame,
        [
            "entry_id",
            "stratum",
            "N_stratum",
            "n_stratum",
            "inclusion_prob",
            "weight",
            "in_sample",
            "census_stratum",
            "risk_features",
            "sample_seed",
        ],
    )
    write_csv(
        config.work_dir / "sample" / "HARD-CASES.csv",
        hard,
        ["entry_id", "hard_reason", "also_in_probability_sample"],
    )
    return frame


def build_queue(config: RunConfig, entries: list[dict], readings: dict) -> list[dict]:
    cases = []
    for entry in entries:
        if not entry["included"]:
            continue
        status = entry_status(config, entry, readings)
        if not status["queued_fields"]:
            continue
        pair = readings.get(entry["entry_id"], {})
        candidates = _dedupe_candidates(pair, config.fields)
        cases.append(
            {
                "entry_id": entry["entry_id"],
                "page": entry["physical_page"],
                "fields": status["queued_fields"],
                "stratum": status["stratum"],
                "crop_relpath": entry.get("crop_relpath", ""),
                "crop_sha256": entry.get("crop_sha256", ""),
                "candidates": candidates,
            }
        )
    ordered, audit = counterbalance(cases, config.order_seed)
    dest = config.work_dir / "queue"
    dest.mkdir(parents=True, exist_ok=True)
    # Provenance (roles, evidence ids) stays in the queue file for the operator.
    # Prompt rendering receives only label and text.
    write_json(dest / "FINAL-QUEUE.json", ordered)
    write_json(dest / "CANDIDATE-ORDER-AUDIT.json", audit)
    if not audit["balanced"]:
        raise RuntimeError("candidate order is not counterbalanced")
    return ordered


def write_learning_flags(config: RunConfig, entries: list[dict], readings: dict) -> None:
    """Post-read flags. Stored beside the run, never passed into blind prompts."""
    lexicon = _load_jsonl(config.inputs_dir / config.lexicon) if config.lexicon else []
    priors = read_csv(config.inputs_dir / config.priors) if config.priors else []
    lex_rows = []
    prior_rows = []
    for entry in entries:
        if not entry["included"]:
            continue
        pair = readings.get(entry["entry_id"], {})
        for stage, reading in pair.items():
            for field in config.fields:
                text = str(reading.get(field, ""))
                for flag in lexicon_flags(text, lexicon):
                    lex_rows.append({"entry_id": entry["entry_id"], "stage": stage, "field": field, **flag})
                for flag in carryover_flags(text, priors, field=field):
                    prior_rows.append({"entry_id": entry["entry_id"], "stage": stage, **flag})
    dest = config.work_dir / "learning"
    dest.mkdir(parents=True, exist_ok=True)
    write_csv(
        dest / "LEXICON-FLAGS.csv",
        lex_rows,
        ["entry_id", "stage", "field", "exact_form", "normalized_alias", "lexicon_version", "evidence_source", "match"],
    )
    write_csv(
        dest / "CARRYOVER-FLAGS.csv",
        prior_rows,
        ["entry_id", "stage", "field", "prior_year", "prior_witness", "prior_exact_form", "normalized_alias", "note"],
    )


def load_queue(config: RunConfig) -> list[dict]:
    path = config.work_dir / "queue" / "FINAL-QUEUE.json"
    if not path.exists():
        return []
    data = read_json_list(path)
    return data


def read_json_list(path: Path) -> list:
    import json

    with path.open(encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError(f"{path.name} must be a list")
    return data


def _dedupe_candidates(pair: dict[str, dict], fields: list[str]) -> list[dict]:
    grouped: dict[str, dict] = {}
    for role in ("reader_a", "reader_b"):
        reading = pair.get(role)
        if not reading:
            continue
        text = {field: reading.get(field, "") for field in fields}
        import json

        key = json.dumps(text, ensure_ascii=False, sort_keys=True)
        slot = grouped.setdefault(key, {"role": role, "text": text, "evidence_ids": [], "roles": []})
        slot["evidence_ids"].append(role)
        slot["roles"].append(role)
        # Keep the earliest role as the canonical role for ordering; record every source.
        if role < slot["role"]:
            slot["role"] = role
    return list(grouped.values())


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return read_jsonl(path)
