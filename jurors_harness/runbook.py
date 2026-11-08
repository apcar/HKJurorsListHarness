"""Per-year orchestration. Stages are resumable and share one ledger."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from jurors_harness.config import RunConfig, dispatch_allowed
from jurors_harness.evaluate import (
    assign_sample,
    build_queue,
    compare_entries,
    readings_from_ledger,
    write_learning_flags,
)
from jurors_harness.hashing import sha256_bytes, sha256_file
from jurors_harness.inventory import freeze_baseline, hash_crops, load_frozen_rows, load_inventory, write_census
from jurors_harness.io_util import read_json
from jurors_harness.parsing import parse_adjudication, parse_reading
from jurors_harness.planning import write_plan
from jurors_harness.prompts import informed_prior_block, render_adjudication, render_blind
from jurors_harness.publish import decide_all, load_adjudications, reference_flags, score_sample, write_release
from jurors_harness.resume import write_resume
from jurors_harness.router import Dispatcher, ScriptedTransport, Transport

READER_STAGES = ("reader_a", "reader_b")


def prepare(config: RunConfig) -> list[dict]:
    config.work_dir.mkdir(parents=True, exist_ok=True)
    rows = load_inventory(config)
    write_census(config, rows)
    crops = {item["entry_id"]: item for item in hash_crops(config, rows)}
    freeze_baseline(config, rows, crops)
    return load_frozen_rows(config)


def make_dispatcher(config: RunConfig, transport=None) -> Dispatcher:
    if transport is None:
        transport = default_transport(config)
    secret_names = tuple(route.env_key for route in config.routes.values() if route.env_key)
    return Dispatcher(
        run_id=config.run_id,
        year=config.year,
        work=config.work_dir,
        routes=config.routes,
        total_usd=config.total_usd,
        stage_budgets=config.stage_budgets,
        transport=transport,
        max_retries=config.max_retries,
        backoff_seconds=config.backoff_seconds,
        probe_max_tokens=config.probe_max_tokens,
        probe_worst_in=config.probe_worst_in,
        acknowledge_billing_stop=config.acknowledge_billing_stop,
        retry_unknown=config.retry_unknown,
        extra_secret_names=secret_names,
    )


def default_transport(config: RunConfig):
    providers = {route.provider for route in config.routes.values()}
    if providers == {"scripted"}:
        if config.scripted_responses is None:
            raise RuntimeError("scripted responses are not configured")
        return ScriptedTransport(read_json(config.scripted_responses))
    return Transport()


def run_readers(config: RunConfig, dispatcher: Dispatcher, entries: list[dict]) -> list[str]:
    notes: list[str] = []
    for stage in READER_STAGES:
        if dispatcher.billing_active() or dispatcher.stop_reason == "total_cap":
            notes.append(f"{stage} not started")
            break
        probe = dispatcher.probe(stage)
        if probe.kind == "stopped":
            notes.append(f"stopped during probe for {stage}: {probe.reason}")
            if probe.reason in {"billing", "total_cap"}:
                break
            continue
        if not _probe_ok(probe):
            notes.append(f"probe failed for {stage}; that route's bulk stage was not started")
            continue
        route = config.route(stage)
        for entry in entries:
            if not entry["included"] or not entry.get("crop_sha256"):
                continue
            image = _crop_bytes(config, entry)
            prompt = render_blind(route.prompt_text, entry_id=entry["entry_id"], year=config.year)
            outcome = dispatcher.dispatch_reading(
                stage=stage,
                entry_id=entry["entry_id"],
                page=entry["physical_page"],
                crop_sha=entry["crop_sha256"],
                prompt=prompt,
                image=image,
                reason="blind literal reading",
                validate=_reading_validator(entry["entry_id"], config.fields),
            )
            if outcome.kind == "stopped" and outcome.reason in {"billing", "total_cap"}:
                notes.append(f"stopped during {stage}: {outcome.reason}")
                break
            if outcome.kind == "stopped" and outcome.reason == "stage_cap":
                notes.append(f"{stage} stopped: stage budget")
                break
        if dispatcher.stop_reason in {"billing", "total_cap"}:
            break
    return notes


def run_adjudication(config: RunConfig, dispatcher: Dispatcher, entries: list[dict]) -> list[str]:
    notes: list[str] = []
    queue_path = config.work_dir / "queue" / "FINAL-QUEUE.json"
    if not queue_path.exists():
        return ["adjudication queue was not built"]
    queue = read_json(queue_path)
    if not isinstance(queue, list):
        raise RuntimeError("FINAL-QUEUE.json is not a list")
    if not queue:
        notes.append("adjudication queue is empty")
        return notes
    if config.reveal_priors:
        route = dispatcher.routes["adjudication"]
        dispatcher.routes["adjudication"] = replace(route, prompt_version=route.prompt_version + "+priors")
    if dispatcher.billing_active() or dispatcher.stop_reason == "total_cap":
        return ["adjudication not started"]
    probe = dispatcher.probe("adjudication")
    if probe.kind == "stopped":
        return [f"stopped during adjudication probe: {probe.reason}"]
    if not _probe_ok(probe):
        return ["adjudication probe failed; bulk adjudication was not started"]
    route = dispatcher.routes["adjudication"]
    prior_by_entry = _priors_by_entry(config) if config.reveal_priors else {}
    by_id = {entry["entry_id"]: entry for entry in entries}
    for item in queue:
        entry = by_id[item["entry_id"]]
        image = _crop_bytes(config, entry)
        prior_block = ""
        if config.reveal_priors and prior_by_entry.get(entry["entry_id"]):
            prior_block = informed_prior_block(prior_by_entry[entry["entry_id"]])
        prompt = render_adjudication(
            route.prompt_text,
            entry_id=entry["entry_id"],
            year=config.year,
            fields=config.fields,
            candidates=item.get("shown") or [],
            prior_block=prior_block,
        )
        shown = "crop + anonymized scan-derived candidates"
        if prior_block:
            shown += "; informed priors labelled as non-authority"
        outcome = dispatcher.dispatch_adjudication(
            entry_id=entry["entry_id"],
            page=entry["physical_page"],
            crop_sha=entry["crop_sha256"],
            prompt=prompt,
            image=image,
            reason="single anonymized adjudication",
            validate=_adjudication_validator(entry["entry_id"], config.fields),
            shown=shown,
        )
        if outcome.kind == "stopped" and outcome.reason in {"billing", "total_cap", "stage_cap"}:
            notes.append(f"stopped during adjudication: {outcome.reason}")
            break
    return notes


def publish(config: RunConfig, entries: list[dict], dispatcher: Dispatcher | None) -> Path | None:
    rows = dispatcher.rows() if dispatcher is not None else []
    readings = readings_from_ledger(rows, config.fields)
    adjudications, repairs = load_adjudications(rows, config.fields)
    billing = bool(dispatcher and dispatcher.billing_active())
    stop = dispatcher.stop_reason if dispatcher else None
    hints = _hints(config, entries, readings, rows, billing=billing, stop_reason=stop)
    decisions = decide_all(config, entries, readings, adjudications, operational_hints=hints)
    flags = reference_flags(config, entries, decisions)
    sample_results, sample_fields, sample_summary = score_sample(config, entries, decisions)
    inherited = list(config.inherited_ledgers)
    ledger_paths = [config.work_dir / "ledger.jsonl", *inherited]
    ledger_paths = [path for path in ledger_paths if path.exists()]
    release = config.work_dir / "release" / config.release_id
    if release.exists():
        return release
    return write_release(
        config,
        entries,
        decisions,
        flags,
        sample_results,
        sample_fields,
        sample_summary,
        repairs,
        ledger_paths,
    )


def execute(config: RunConfig, *, transport=None, source: Path | None = None) -> int:
    if source is not None:
        snapshot = config.work_dir / "config.snapshot.json"
        config.work_dir.mkdir(parents=True, exist_ok=True)
        snapshot.write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    entries = prepare(config)
    included = sum(1 for entry in entries if entry["included"])
    allowed, why = dispatch_allowed(config)
    if not allowed:
        write_plan(config, included=included, adjudication_cases=None)
        write_resume(config, reason=f"dispatch-not-authorized: {why}", stage="plan", notes=[why])
        return 0
    dispatcher = make_dispatcher(config, transport)
    notes = run_readers(config, dispatcher, entries)
    readings = readings_from_ledger(dispatcher.rows(), config.fields)
    compare_entries(config, entries, readings)
    assign_sample(config, entries, readings)
    write_learning_flags(config, entries, readings)
    queue = build_queue(config, entries, readings)
    write_plan(config, included=included, adjudication_cases=len(queue))
    notes.extend(run_adjudication(config, dispatcher, entries))
    publish(config, entries, dispatcher)
    reason = "completed"
    code = 0
    if dispatcher.billing_active():
        reason = "billing_stop"
        code = 3
    elif dispatcher.stop_reason in {"total_cap", "stage_cap"}:
        reason = dispatcher.stop_reason
        code = 4
    write_resume(config, reason=reason, stage="closeout", dispatcher=dispatcher, notes=notes)
    return code


def _probe_ok(outcome) -> bool:
    if outcome.kind == "cached" and outcome.record and outcome.record.get("outcome") == "ok":
        return True
    if outcome.kind == "ok" and outcome.record and outcome.record.get("outcome") == "ok":
        return True
    return False


def _crop_bytes(config: RunConfig, entry: dict) -> bytes:
    path = config.inputs_dir / entry["crop_relpath"]
    data = path.read_bytes()
    digest = sha256_bytes(data)
    recorded = entry.get("crop_sha256") or sha256_file(path)
    if digest != recorded:
        raise RuntimeError(f"crop hash mismatch for {entry['entry_id']}")
    return data


def _reading_validator(entry_id: str, fields: list[str]):
    def validate(_raw: str, parsed: dict | None):
        if parse_reading(parsed or {}, fields, entry_id) is None:
            return False, "schema failure"
        return True, ""

    return validate


def _adjudication_validator(entry_id: str, fields: list[str]):
    def validate(_raw: str, parsed: dict | None):
        if parse_adjudication(parsed or {}, fields, entry_id) is None:
            return False, "schema failure"
        return True, ""

    return validate


def _priors_by_entry(config: RunConfig) -> dict[str, list[dict]]:
    path = config.work_dir / "learning" / "CARRYOVER-FLAGS.csv"
    grouped: dict[str, list[dict]] = {}
    if not path.exists():
        return grouped
    from jurors_harness.io_util import read_csv

    for row in read_csv(path):
        grouped.setdefault(row["entry_id"], []).append(row)
    return grouped


def _hints(config, entries, readings, rows, *, billing: bool, stop_reason: str | None) -> dict[str, str]:
    from jurors_harness.evaluate import entry_status

    hints = {}
    for entry in entries:
        if not entry["included"]:
            hints[entry["entry_id"]] = "not_applicable"
            continue
        if not entry.get("crop_sha256"):
            hints[entry["entry_id"]] = "missing_evidence"
            continue
        status = entry_status(config, entry, readings)
        adjudication_done = any(
            row.get("line_id") == entry["entry_id"]
            and row.get("step") == "adjudication"
            and (row.get("outcome") == "ok" or row.get("http_status") == 200)
            for row in rows
        )
        if not status["queued_fields"] or adjudication_done:
            hints[entry["entry_id"]] = "reviewed"
            continue
        if billing:
            hints[entry["entry_id"]] = "billing_stopped"
        elif stop_reason in {"total_cap", "stage_cap"}:
            hints[entry["entry_id"]] = "pending_budget"
        else:
            hints[entry["entry_id"]] = "pending_budget"
    return hints
