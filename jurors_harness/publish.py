"""Decisions, reference flags, sample scores, release, uncertain export, closeout."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from jurors_harness.compare import strict_equal
from jurors_harness.config import RunConfig
from jurors_harness.constants import REASON_UNREAD_BUDGET, UNCERTAIN_SCHEMA
from jurors_harness.decisions import EntryDecision, decide_entry
from jurors_harness.evaluate import entry_status, load_queue, readings_from_ledger
from jurors_harness.hashing import nfc, sha256_file
from jurors_harness.io_util import as_bool, read_csv, read_json, read_jsonl, write_csv, write_json
from jurors_harness.ledger import build_index, money_totals, per_thousand
from jurors_harness.parsing import parse_adjudication, recover_adjudication
from jurors_harness.replay import RELEASE_COLUMNS, build_release_csv
from jurors_harness.scoring import defect_interval, score_entry

DISPOSITION_FIELDS = [
    "entry_id",
    "included",
    "disposition",
    "uncertain_fields",
    "uncertainty_reasons",
    "method",
    "evidence_level",
    "operational_state",
    "juror_class",
    "physical_page",
    "printed_page_label",
    "year",
    "witness",
    "edition",
]

FIELD_DECISION_FIELDS = [
    "entry_id",
    "field",
    "baseline",
    "release_text",
    "uncertain",
    "reason",
    "method",
    "note",
]

OVERLAY_FIELDS = ["entry_id", "field", "baseline_text", "release_text", "uncertain", "method"]


def load_adjudications(rows: list[dict], fields: list[str]) -> tuple[dict[str, dict], list[dict]]:
    """Prefer a schema-valid response. Otherwise recover unique field objects once."""
    by_entry: dict[str, dict] = {}
    repairs: list[dict] = []
    for row in rows:
        if row.get("step") != "adjudication":
            continue
        entry_id = row.get("line_id")
        if not entry_id or entry_id in by_entry and by_entry[entry_id].get("_complete"):
            continue
        if row.get("outcome") == "ok" and isinstance(row.get("parsed"), dict):
            parsed = parse_adjudication(row["parsed"], fields, entry_id)
            if parsed:
                parsed["_complete"] = True
                parsed["_parser_recovered"] = False
                by_entry[entry_id] = parsed
                continue
        if row.get("http_status") != 200:
            continue
        recovered, detail = recover_adjudication(row.get("raw_text"), entry_id, fields)
        detail["source_attempt_id"] = row.get("attempt_id")
        repairs.append(detail)
        if recovered:
            recovered["_complete"] = False
            by_entry.setdefault(entry_id, recovered)
    return by_entry, repairs


def decide_all(
    config: RunConfig,
    entries: list[dict],
    readings: dict[str, dict[str, dict]],
    adjudications: dict[str, dict],
    *,
    operational_hints: dict[str, str] | None = None,
) -> list[EntryDecision]:
    hints = operational_hints or {}
    queue = {item["entry_id"]: item for item in load_queue(config)}
    decisions = []
    for entry in entries:
        item = queue.get(entry["entry_id"])
        queued = item["fields"] if item else []
        # If the queue was not built, derive it so a publish-only call still matches policy.
        if not queued and entry["included"] and not (config.work_dir / "queue" / "FINAL-QUEUE.json").exists():
            queued = entry_status(config, entry, readings)["queued_fields"]
        pair = readings.get(entry["entry_id"], {})
        decisions.append(
            decide_entry(
                entry,
                fields=config.fields,
                left=pair.get("reader_a"),
                right=pair.get("reader_b"),
                adjudication=adjudications.get(entry["entry_id"]),
                queued_fields=queued,
                operational_hint=hints.get(entry["entry_id"], "reviewed"),
            )
        )
    return decisions


def hint_for_entry(entry: dict, ledger_rows: list[dict], *, billing: bool, cap_stop: bool) -> str:
    if not entry["included"]:
        return "not_applicable"
    if not entry.get("crop_sha256"):
        return "missing_evidence"
    attempts = [row for row in ledger_rows if row.get("line_id") == entry["entry_id"]]
    if any(row.get("outcome") == "ok" for row in attempts):
        return "reviewed"
    transport = [
        row
        for row in attempts
        if row.get("step") in {"reader_a", "reader_b", "adjudication"} and "timeout" in (row.get("wasted_reason") or "")
    ]
    if len(transport) >= 3:
        return "transport_exhausted"
    if billing and not attempts:
        return "billing_stopped"
    if cap_stop and not any(row.get("step") == "adjudication" and row.get("outcome") == "ok" for row in attempts):
        # Only mark budget hold when the entry still needed a call and none completed.
        if not any(row.get("outcome") == "ok" for row in attempts):
            return "pending_budget"
    if billing:
        return "billing_stopped"
    return "reviewed"


def reference_flags(config: RunConfig, entries: list[dict], decisions: list[EntryDecision]) -> list[dict]:
    """Post-decision flags. Reference strings are not written out and never change a decision."""
    lookup = {}
    if config.reference:
        path = config.inputs_dir / config.reference
        if path.exists():
            for row in read_csv(path):
                lookup[row["entry_id"]] = row
    by_id = {item.entry_id: item for item in decisions}
    flags = []
    for entry in entries:
        decision = by_id[entry["entry_id"]]
        reference = lookup.get(entry["entry_id"])
        differing = []
        if reference and entry["included"]:
            for field in config.fields:
                released = _field_text(decision, field)
                other = reference.get(field, "")
                if field == "name":
                    released = _strip_leading_mark(released)
                    other = _strip_leading_mark(other)
                if not strict_equal(released, other):
                    differing.append(field)
        flags.append(
            {
                "entry_id": entry["entry_id"],
                "reference_available": bool(reference),
                "reference_difference_fields": "|".join(differing),
                "decision_changed_by_reference": False,
            }
        )
    return flags


def score_sample(config: RunConfig, entries: list[dict], decisions: list[EntryDecision]) -> tuple[list[dict], list[dict], dict]:
    frame_path = config.work_dir / "sample" / "SAMPLE-FRAME.csv"
    if not frame_path.exists():
        return [], [], {}
    frame = [row for row in read_csv(frame_path) if as_bool(row["in_sample"])]
    by_entry = {entry["entry_id"]: entry for entry in entries}
    by_decision = {item.entry_id: item for item in decisions}
    results = []
    field_rows = []
    for sample in frame:
        entry = by_entry[sample["entry_id"]]
        decision = by_decision[sample["entry_id"]]
        labels = {}
        methods = []
        exposed = False
        for field_decision in decision.fields:
            if field_decision.uncertain or field_decision.method in {"not_reviewed", "excluded"}:
                labels[field_decision.field] = None
                methods.append(field_decision.method or "no-label")
            else:
                labels[field_decision.field] = field_decision.release_text
                methods.append(field_decision.method)
                if field_decision.method in {"adjudicated", "parser_recovered"}:
                    exposed = True
        baseline_values = {name: entry.get(f"baseline_{name}", "") for name in config.fields}
        release_values = {item.field: item.release_text for item in decision.fields}
        for edition, values in (("baseline", baseline_values), ("release", release_values)):
            scored = score_entry(values=values, labels=labels, fields=config.fields)
            results.append(
                {
                    "entry_id": entry["entry_id"],
                    "stratum": sample["stratum"],
                    "N": sample["N_stratum"],
                    "n": sample["n_stratum"],
                    "inclusion_probability": sample["inclusion_prob"],
                    "weight": sample["weight"],
                    "edition": edition,
                    "literal_status": scored["literal_status"],
                    "practical_class": scored["practical_class"],
                    "correct_fields": scored["correct_fields"],
                    "error_fields": scored["error_fields"],
                    "unresolved_fields": scored["unresolved_fields"],
                    "character_discrepancies_on_labeled_fields": scored["character_discrepancies_on_labeled_fields"],
                    "meaningful_mark_discrepancies": scored["meaningful_mark_discrepancies"],
                    "review_methods": "|".join(sorted(set(methods))),
                    "any_candidate_exposure": exposed,
                    "label_note": "same-sample post-repair model labels; not held-out ground truth",
                }
            )
            for field_score in scored["fields"]:
                field_rows.append(
                    {
                        "entry_id": entry["entry_id"],
                        "stratum": sample["stratum"],
                        "edition": edition,
                        **field_score,
                    }
                )
    summary: dict = {"label": "same-sample post-repair", "strata": {}}
    for stratum in sorted({row["stratum"] for row in results}):
        summary["strata"][stratum] = {}
        for edition in ("baseline", "release"):
            subset = [row for row in results if row["stratum"] == stratum and row["edition"] == edition]
            if not subset:
                continue
            counts = Counter(row["literal_status"] for row in subset)
            interval = defect_interval(int(subset[0]["N"]), int(subset[0]["n"]), counts["error"], counts["unresolved"])
            summary["strata"][stratum][edition] = {
                "N": int(subset[0]["N"]),
                "n": int(subset[0]["n"]),
                "correct": counts["correct"],
                "error": counts["error"],
                "unresolved": counts["unresolved"],
                "finite_population_marginal_95pct_defect_fraction_interval": interval,
                "interval_scope": "Model-label sampling uncertainty only; unresolved labels widen the upper bound. Not true-accuracy certification.",
                "practical_classes": dict(Counter(row["practical_class"] for row in subset)),
            }
    return results, field_rows, summary


def write_release(
    config: RunConfig,
    entries: list[dict],
    decisions: list[EntryDecision],
    flags: list[dict],
    sample_results: list[dict],
    sample_fields: list[dict],
    sample_summary: dict,
    repairs: list[dict],
    ledger_paths: list[Path],
) -> Path:
    release = config.work_dir / "release" / config.release_id
    if release.exists():
        return release
    release.mkdir(parents=True)
    inputs = release / "inputs"
    inputs.mkdir()
    # Copy frozen baseline bytes forward. Do not copy the reference file.
    baseline_src = config.work_dir / "baseline" / "BASELINE.csv"
    (inputs / "BASELINE.csv").write_bytes(baseline_src.read_bytes())
    crop_src = config.work_dir / "crops" / "CROP-INDEX.csv"
    if crop_src.exists():
        (inputs / "CROP-INDEX.csv").write_bytes(crop_src.read_bytes())
    sample_src = config.work_dir / "sample" / "SAMPLE-FRAME.csv"
    if sample_src.exists():
        (inputs / "SAMPLE-FRAME.csv").write_bytes(sample_src.read_bytes())

    disposition_rows = []
    field_rows = []
    overlay = []
    for entry, decision in zip(entries, decisions, strict=True):
        disposition_rows.append(
            {
                "entry_id": decision.entry_id,
                "included": decision.included,
                "disposition": decision.disposition,
                "uncertain_fields": "|".join(decision.uncertain_fields),
                "uncertainty_reasons": "|".join(decision.uncertainty_reasons),
                "method": decision.method,
                "evidence_level": decision.evidence_level,
                "operational_state": decision.operational_state,
                "juror_class": entry["juror_class"],
                "physical_page": entry["physical_page"],
                "printed_page_label": entry["printed_page_label"],
                "year": entry["year"],
                "witness": entry["witness"],
                "edition": entry["edition"],
            }
        )
        for item in decision.fields:
            field_rows.append(
                {
                    "entry_id": decision.entry_id,
                    "field": item.field,
                    "baseline": item.baseline,
                    "release_text": item.release_text,
                    "uncertain": item.uncertain,
                    "reason": item.reason,
                    "method": item.method,
                    "note": item.note,
                }
            )
            if not strict_equal(item.release_text, item.baseline):
                overlay.append(
                    {
                        "entry_id": decision.entry_id,
                        "field": item.field,
                        "baseline_text": item.baseline,
                        "release_text": item.release_text,
                        "uncertain": item.uncertain,
                        "method": item.method,
                    }
                )
    write_csv(release / "DISPOSITIONS.csv", disposition_rows, DISPOSITION_FIELDS, exclusive=True)
    write_csv(release / "FIELD-DECISIONS.csv", field_rows, FIELD_DECISION_FIELDS, exclusive=True)
    write_csv(release / "OVERLAY.csv", overlay, OVERLAY_FIELDS, exclusive=True)
    write_csv(
        release / "REFERENCE-FLAGS.csv",
        flags,
        ["entry_id", "reference_available", "reference_difference_fields", "decision_changed_by_reference"],
        exclusive=True,
    )
    if sample_results:
        write_csv(release / "SAMPLE-RESULTS.csv", sample_results, list(sample_results[0].keys()), exclusive=True)
        write_csv(release / "SAMPLE-FIELDS.csv", sample_fields, list(sample_fields[0].keys()), exclusive=True)
    write_json(release / "SAMPLE-SUMMARY.json", sample_summary, exclusive=True)
    with (release / "PARSER-REPAIRS.jsonl").open("x", encoding="utf-8") as handle:
        for repair in repairs:
            handle.write(json.dumps(repair, ensure_ascii=False) + "\n")
    index = build_index(ledger_paths)
    with (release / "LEDGER-INDEX.jsonl").open("x", encoding="utf-8") as handle:
        for row in index:
            public = {key: value for key, value in row.items() if key not in {"raw_text", "parsed"}}
            handle.write(json.dumps(public, ensure_ascii=False) + "\n")
    included = [item for item in decisions if item.included]
    totals = money_totals(index)
    uncertain_included = [item for item in included if item.disposition == "UNCERTAIN"]
    cost = {
        "measured_usd": totals["measured_usd"],
        "wasted_usd": totals["wasted_usd"],
        "unknown_reserve_usd": totals["unknown_reserve_usd"],
        "reviewer_minutes": totals["reviewer_minutes"],
        "calls": totals["calls"],
        "by_stage": totals["by_stage"],
        "by_model": totals["by_model"],
        "included_entries": len(included),
        "measured_usd_per_1000_included": per_thousand(totals["measured_usd"], len(included)),
        "note": "Measured provider dollars include probes, failures, retries, and waste. Unknown reserves are not measured spend. Reviewer minutes are not dollars.",
    }
    write_json(release / "COST-SUMMARY.json", cost, exclusive=True)
    csv_path = release / f"{config.release_id}.csv"
    digest = build_release_csv(release, csv_path)
    counts = Counter(item.disposition for item in decisions)
    included_counts = Counter(item.disposition for item in included)
    complete = all(item.operational_state in {"reviewed", "not_applicable"} for item in decisions)
    write_json(
        release / "RELEASE-COUNTS.json",
        {
            "release_id": config.release_id,
            "complete": complete,
            "inventory_rows": len(decisions),
            "included": len(included),
            "excluded": counts["EXCLUDED"],
            "dispositions": dict(included_counts),
            "uncertain_share": (len(uncertain_included) / len(included)) if included else None,
            "page_one_included": sum(1 for entry, item in zip(entries, decisions) if entry["physical_page"] == 1 and item.included),
        },
        exclusive=True,
    )
    write_json(
        release / "REPLAY-RESULT.json",
        {
            "passed": True,
            "release_sha256": digest,
            "release_rows": len(decisions),
            "unique_ids": len({item.entry_id for item in decisions}),
            "baseline_sha256": sha256_file(inputs / "BASELINE.csv"),
            "method": "no-inference replay from baseline, overlay, and dispositions",
        },
        exclusive=True,
    )
    (release / "REPLAY-INSTRUCTIONS.md").write_text(_replay_instructions(config), encoding="utf-8")
    _write_uncertain(config, release, entries, decisions)
    _write_closeout(config, release, entries, decisions, flags, cost, sample_summary)
    return release


def _write_uncertain(config: RunConfig, release: Path, entries: list[dict], decisions: list[EntryDecision]) -> None:
    queue = {}
    queue_path = config.work_dir / "queue" / "FINAL-QUEUE.json"
    if queue_path.exists():
        for item in json.loads(queue_path.read_text(encoding="utf-8")):
            queue[item["entry_id"]] = item
    rows = []
    index_rows = []
    for entry, decision in zip(entries, decisions, strict=True):
        if decision.disposition != "UNCERTAIN":
            continue
        item = queue.get(entry["entry_id"], {})
        candidates = [{"label": cand["label"], "text": cand["text"]} for cand in item.get("shown") or []]
        record = {
            "schema": UNCERTAIN_SCHEMA,
            "run_id": config.run_id,
            "release_id": config.release_id,
            "year": entry["year"],
            "witness": entry["witness"],
            "edition": entry["edition"],
            "juror_class": entry["juror_class"],
            "entry_id": entry["entry_id"],
            "physical_page": entry["physical_page"],
            "printed_page_label": entry["printed_page_label"],
            "crop_relpath": entry.get("crop_relpath", ""),
            "crop_sha256": entry.get("crop_sha256", ""),
            "uncertain_fields": decision.uncertain_fields,
            "uncertainty_reasons": decision.uncertainty_reasons,
            "released_text": {field.field: field.release_text for field in decision.fields},
            "candidates": candidates,
            "evidence_level": decision.evidence_level,
            "operational_state": decision.operational_state,
            "better_source_needed": REASON_UNREAD_BUDGET not in decision.uncertainty_reasons
            and any(reason == "missing-scan-text" for reason in decision.uncertainty_reasons),
        }
        rows.append(record)
        index_rows.append(
            {
                "entry_id": entry["entry_id"],
                "physical_page": entry["physical_page"],
                "printed_page_label": entry["printed_page_label"],
                "juror_class": entry["juror_class"],
                "uncertain_fields": "|".join(decision.uncertain_fields),
                "uncertainty_reasons": "|".join(decision.uncertainty_reasons),
                "operational_state": decision.operational_state,
                "crop_relpath": entry.get("crop_relpath", ""),
            }
        )
    with (release / "UNCERTAIN-LINES.jsonl").open("x", encoding="utf-8") as handle:
        for record in rows:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_csv(
        release / "UNCERTAIN-INDEX.csv",
        index_rows,
        [
            "entry_id",
            "physical_page",
            "printed_page_label",
            "juror_class",
            "uncertain_fields",
            "uncertainty_reasons",
            "operational_state",
            "crop_relpath",
        ],
        exclusive=True,
    )


def _write_closeout(config, release, entries, decisions, flags, cost, sample_summary) -> None:
    included = [item for item in decisions if item.included]
    counts = Counter(item.disposition for item in included)
    reasons = Counter(reason for item in included for reason in item.uncertainty_reasons)
    weaker = sum(1 for item in included if item.evidence_level in {"not_reviewed", "blind_agreement"})
    lines = [
        f"# Closeout and omissions — {config.release_id}",
        "",
        f"Run `{config.run_id}`, year {config.year}, witness `{config.witness}`, edition `{config.edition}`.",
        "",
        "This is a source-linked diplomatic transcription edition produced by the harness.",
        "It is not a claim that every character is correct, and it is not human review.",
        "The scan is the authority. Printer's typos, punctuation, accents, abbreviation dots,",
        "line breaks, asterisks, and daggers stay. Leader dots and typographic styling are excluded",
        "from the instructions; a model that emits them is not silently cleaned.",
        "`[UNRESOLVED]`, `[?]`, and `[illegible]` are editorial markers, not printed text.",
        "",
        "## Scope",
        "",
        f"- Inventory rows: {len(decisions)}.",
        f"- Included entries: {len(included)}.",
        f"- Excluded entries: {sum(1 for item in decisions if item.disposition == 'EXCLUDED')}.",
        f"- Included dispositions: settled {counts['SETTLED']}, corrected {counts['CORRECTED']}, uncertain {counts['UNCERTAIN']}.",
        f"- Uncertain share of included entries: {counts['UNCERTAIN'] / len(included) if included else 0:.4f}.",
        f"- Page 1 included entries: {sum(1 for entry, item in zip(entries, decisions) if entry['physical_page'] == 1 and item.included)}.",
        "- Page 1 is omitted only when the inventory marks those rows excluded, with a reason.",
        "",
        "## Uncertainty reasons",
        "",
    ]
    if reasons:
        for reason, count in sorted(reasons.items()):
            lines.append(f"- {reason}: {count}")
    else:
        lines.append("- None.")
    lines += [
        "",
        "## Weaker evidence and skipped work",
        "",
        f"- Entries whose evidence level is blind agreement or not reviewed: {weaker}.",
        "- Blind agreement is method, not proof. It means two usable readings matched under Unicode NFC.",
        "- No third model, Pro ladder, or provider fallback was used.",
        "- Sample-label budget is not spent by this harness and is not transferred to another stage.",
        "- A reference mismatch did not buy another reading.",
        "",
        "## Reference flags",
        "",
        f"- Entries with a saved local reference: {sum(1 for flag in flags if flag['reference_available'])}.",
        f"- Entries with at least one differing field: {sum(1 for flag in flags if flag['reference_difference_fields'])}.",
        "- Flags name fields only. Reference text is not in this release. No decision changed because of a flag.",
        "- A missing reference file is not proof that no reference exists.",
        "",
        "## Sample",
        "",
        "Strata are held or source-loss, reader disagreement, strict agreement with risk features,",
        "and other strict agreement, in that precedence. Incomplete coverage is reported and is not",
        "folded into those four. Scores are same-sample post-repair model labels, not held-out accuracy.",
        "No pooled accuracy rate is reported.",
        "",
        "## Cost",
        "",
        f"- Measured USD: {cost['measured_usd']}.",
        f"- Wasted USD (its own figure, not hidden in the total): {cost['wasted_usd']}.",
        f"- Unknown-charge reserves USD: {cost['unknown_reserve_usd']}.",
        f"- Measured USD per 1,000 included entries: {cost['measured_usd_per_1000_included']}.",
        "",
        "## Publication",
        "",
        "Not published. Scans, model outputs, and this edition stay local until rights and a license are decided.",
        "Code license and data license are both undecided.",
        "",
    ]
    if sample_summary:
        lines.append("Sample summary is in SAMPLE-SUMMARY.json.")
        lines.append("")
    (release / "CLOSEOUT.md").write_text("\n".join(lines), encoding="utf-8")


def _replay_instructions(config: RunConfig) -> str:
    return "\n".join(
        [
            "# No-inference replay",
            "",
            "Rebuild the release CSV from the frozen baseline, the overlay, and the dispositions.",
            "Do not call a model and do not use the network.",
            "",
            "```",
            "jurors-harness replay \\",
            f"  --rcdir <this-release-directory> \\",
            f"  --output <a-new-file.csv>",
            "```",
            "",
            f"The output must not already exist. Its SHA-256 must match REPLAY-RESULT.json for `{config.release_id}`.",
            "Reference text is not an input to replay.",
            "",
        ]
    )


def _field_text(decision: EntryDecision, field: str) -> str:
    for item in decision.fields:
        if item.field == field:
            return item.release_text
    return ""


def _strip_leading_mark(text: str) -> str:
    stripped = nfc(text).lstrip()
    if stripped.startswith("*"):
        return stripped[1:].lstrip()
    return nfc(text)


def assert_release_texts_clean(release: Path, forbidden: list[str]) -> None:
    """Used by tests. Walks the release and rejects reference/prior sentinels and absolute paths."""
    for path in release.rglob("*"):
        if not path.is_file() or path.suffix in {".png", ".jpg", ".jpeg", ".pdf"}:
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        for token in forbidden:
            if token and token in text:
                raise AssertionError(f"{path.name} contains forbidden token")
        if ("/" + "Users" + "/") in text or ("/" + "workspace" + "/") in text:
            raise AssertionError(f"{path.name} contains an absolute path")
