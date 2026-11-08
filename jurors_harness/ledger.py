"""Append-only LEDGER-v1 JSONL plus a derived index that never rewrites source rows."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path

from jurors_harness.constants import LEDGER_EXT, LEDGER_SCHEMA
from jurors_harness.io_util import append_jsonl, read_jsonl


def ledger_row(
    *,
    run_id: str,
    ts: str,
    year: int,
    page: int,
    line_id: str,
    model: str,
    model_reported: str | None,
    step: str,
    reason: str,
    prompt_version: str,
    settings: dict,
    attempt: int,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    wasted: bool,
    wasted_reason: str,
    wall_secs: float,
    outcome: str,
    crop_sha256: str,
    provider: str,
    provider_request_id: str | None,
    input_sha256: dict,
    raw_response_relpath: str,
    reservation_usd: float,
    unresolved_charge_reserve_usd: float,
    http_status: int | None,
    billing_error: bool,
    attempt_id: str,
    raw_text: str | None,
    parsed: dict | None,
    supersedes: str | None = None,
) -> dict:
    return {
        "schema": LEDGER_SCHEMA,
        "schema_ext": LEDGER_EXT,
        "attempt_id": attempt_id,
        "run": run_id,
        "ts": ts,
        "year": year,
        "page": page,
        "line_id": line_id,
        "model": model,
        "model_reported": model_reported,
        "step": step,
        "reason": reason,
        "prompt_version": prompt_version,
        "settings": settings,
        "attempt": attempt,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "cost_usd": cost_usd,
        "wasted": wasted,
        "wasted_reason": wasted_reason,
        "wall_secs": wall_secs,
        "reviewer": None,
        "reviewer_minutes": None,
        "outcome": outcome,
        "crop_sha256": crop_sha256,
        "provider": provider,
        "provider_request_id": provider_request_id,
        "input_sha256": input_sha256,
        "raw_response_relpath": raw_response_relpath,
        "reservation_usd": reservation_usd,
        "unresolved_charge_reserve_usd": unresolved_charge_reserve_usd,
        "http_status": http_status,
        "billing_error": billing_error,
        "supersedes": supersedes,
        "raw_text": raw_text,
        "parsed": parsed,
    }


def append_ledger(path: Path, row: dict) -> None:
    if row.get("schema") != LEDGER_SCHEMA:
        raise ValueError("ledger rows must use LEDGER-v1")
    append_jsonl(path, row)


def cache_identity(row: dict) -> tuple:
    return (
        row.get("year"),
        row.get("crop_sha256") or "",
        row.get("step"),
        row.get("model"),
        row.get("prompt_version"),
        row.get("line_id"),
    )


def dedupe_key(row: dict) -> tuple:
    return (row.get("ts"), row.get("line_id"), row.get("model"), row.get("attempt"), row.get("step"))


def build_index(paths: list[Path]) -> list[dict]:
    """Derived rows. The same charged call is kept once. Source files are not modified."""
    seen: set[tuple] = set()
    index: list[dict] = []
    for path in paths:
        for line_no, row in enumerate(read_jsonl(path), 1):
            key = dedupe_key(row)
            if key in seen:
                continue
            seen.add(key)
            copied = dict(row)
            copied["index_source"] = path.name
            copied["index_source_line"] = line_no
            index.append(copied)
    return index


def money_totals(rows: list[dict]) -> dict:
    measured = 0.0
    wasted = 0.0
    unknown = 0.0
    by_stage: dict[str, dict[str, float]] = defaultdict(lambda: {"measured_usd": 0.0, "wasted_usd": 0.0, "unknown_reserve_usd": 0.0, "calls": 0})
    by_model: dict[str, dict[str, float]] = defaultdict(lambda: {"measured_usd": 0.0, "wasted_usd": 0.0, "calls": 0})
    reviewer_minutes = 0.0
    for row in rows:
        cost = float(row.get("cost_usd") or 0)
        reserve = float(row.get("unresolved_charge_reserve_usd") or 0)
        measured += cost
        unknown += reserve
        stage = str(row.get("step") or "")
        model = str(row.get("model") or "")
        by_stage[stage]["measured_usd"] += cost
        by_stage[stage]["unknown_reserve_usd"] += reserve
        by_stage[stage]["calls"] += 1
        by_model[model]["measured_usd"] += cost
        by_model[model]["calls"] += 1
        if row.get("wasted") or row.get("outcome") == "error":
            wasted += cost
            by_stage[stage]["wasted_usd"] += cost
            by_model[model]["wasted_usd"] += cost
        if row.get("reviewer_minutes"):
            reviewer_minutes += float(row["reviewer_minutes"])
    return {
        "calls": len(rows),
        "measured_usd": measured,
        "wasted_usd": wasted,
        "unknown_reserve_usd": unknown,
        "reviewer_minutes": reviewer_minutes,
        "by_stage": dict(by_stage),
        "by_model": dict(by_model),
    }


def per_thousand(measured_usd: float, included_entries: int) -> float | None:
    if included_entries <= 0:
        return None
    return measured_usd / included_entries * 1000
