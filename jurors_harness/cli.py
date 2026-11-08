"""Command line for one year of diplomatic transcription."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from jurors_harness import __version__
from jurors_harness.compat1940 import verify_1940
from jurors_harness.config import ConfigError, load_config
from jurors_harness.evaluate import assign_sample, build_queue, compare_entries, readings_from_ledger, write_learning_flags
from jurors_harness.inventory import hash_crops, load_frozen_rows, load_inventory, write_census
from jurors_harness.io_util import read_jsonl
from jurors_harness.ledger import money_totals, per_thousand
from jurors_harness.planning import write_plan
from jurors_harness.replay import build_release_csv, verify_release
from jurors_harness.runbook import execute, make_dispatcher, prepare, publish, run_adjudication, run_readers
from jurors_harness.secret_scan import scan_history, scan_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jurors-harness", description="Diplomatic transcription harness")
    parser.add_argument("--version", action="version", version=f"jurors-harness {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    def add_config(command: argparse.ArgumentParser) -> None:
        command.add_argument("--config", required=True, type=Path)
        command.add_argument("--root", type=Path, default=Path("."))
        command.add_argument("--work", type=Path, default=None)

    for name in (
        "validate",
        "plan",
        "census",
        "freeze",
        "crops",
        "read",
        "compare",
        "sample",
        "queue",
        "adjudicate",
        "release",
        "closeout",
        "export-uncertain",
        "ledger",
        "status",
        "run",
    ):
        add_config(sub.add_parser(name))

    replay = sub.add_parser("replay")
    replay.add_argument("--rcdir", required=True, type=Path)
    replay.add_argument("--output", required=True, type=Path)
    verify = sub.add_parser("verify-release")
    verify.add_argument("--rcdir", required=True, type=Path)
    historical = sub.add_parser("verify-1940")
    historical.add_argument("--csv", required=True, type=Path)
    historical.add_argument("--baseline", type=Path)
    historical.add_argument("--dispositions", type=Path)
    secrets = sub.add_parser("secret-scan")
    secrets.add_argument("--root", type=Path, default=Path("."))
    secrets.add_argument("--history", action="store_true")

    args = parser.parse_args(argv)
    try:
        return _dispatch(args)
    except (ConfigError, FileNotFoundError, ValueError, RuntimeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _dispatch(args: argparse.Namespace) -> int:
    if args.command == "replay":
        digest = build_release_csv(args.rcdir, args.output)
        print(digest)
        return 0
    if args.command == "verify-release":
        result = verify_release(args.rcdir)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "verify-1940":
        result = verify_1940(args.csv, args.baseline, args.dispositions)
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1
    if args.command == "secret-scan":
        findings = scan_tree(args.root)
        if args.history:
            findings.extend(scan_history(args.root))
        if findings:
            for finding in findings:
                print(f"{finding.path}:{finding.line}: {finding.pattern}")
            return 1
        print("secret-scan: no findings")
        return 0
    config = load_config(args.config, root=args.root, work_override=args.work)
    if args.command == "validate":
        print(f"valid {config.run_id} year {config.year}")
        return 0
    if args.command == "status":
        path = config.work_dir / "RESUME.md"
        if not path.exists():
            print("no RESUME.md yet")
            return 0
        print(path.read_text(encoding="utf-8"))
        return 0
    if args.command == "run":
        return execute(config, source=args.config)
    if args.command == "census":
        write_census(config, load_inventory(config))
        return 0
    if args.command == "crops":
        hash_crops(config, load_inventory(config))
        return 0
    if args.command == "freeze":
        prepare(config)
        return 0
    if args.command == "plan":
        entries = prepare(config)
        included = sum(1 for entry in entries if entry["included"])
        queue_path = config.work_dir / "queue" / "FINAL-QUEUE.json"
        cases = None
        if queue_path.exists():
            cases = len(read_json_list(queue_path))
        plan = write_plan(config, included=included, adjudication_cases=cases)
        print(json.dumps({"dispatch_allowed": plan["dispatch_allowed"], "worst_case_usd": plan["worst_case_usd"]}, indent=2))
        return 0
    if args.command in {"read", "compare", "sample", "queue", "adjudicate", "release", "closeout", "export-uncertain", "ledger"}:
        return _stage(config, args.command)
    raise AssertionError(args.command)


def _stage(config: RunConfig, command: str) -> int:
    entries = prepare(config)
    if command == "ledger":
        rows = read_jsonl(config.work_dir / "ledger.jsonl")
        totals = money_totals(rows)
        included = sum(1 for entry in entries if entry["included"])
        totals["measured_usd_per_1000_included"] = per_thousand(totals["measured_usd"], included)
        print(json.dumps(totals, indent=2))
        return 0
    dispatcher = None
    if command in {"read", "adjudicate", "release", "closeout", "export-uncertain"}:
        from jurors_harness.config import dispatch_allowed

        allowed, why = dispatch_allowed(config)
        if command == "read" and not allowed:
            print(f"error: {why}", file=sys.stderr)
            return 2
        dispatcher = make_dispatcher(config)
    if command == "read":
        notes = run_readers(config, dispatcher, entries)
        for note in notes:
            print(note)
        return 3 if dispatcher.billing_active() else 0
    readings = readings_from_ledger(read_jsonl(config.work_dir / "ledger.jsonl"), config.fields)
    if command == "compare":
        compare_entries(config, entries, readings)
        return 0
    if command == "sample":
        assign_sample(config, entries, readings)
        return 0
    if command == "queue":
        compare_entries(config, entries, readings)
        write_learning_flags(config, entries, readings)
        queue = build_queue(config, entries, readings)
        print(f"queue {len(queue)}")
        return 0
    if command == "adjudicate":
        if dispatcher is None:
            dispatcher = make_dispatcher(config)
        notes = run_adjudication(config, dispatcher, entries)
        for note in notes:
            print(note)
        return 3 if dispatcher.billing_active() else 0
    if dispatcher is None:
        dispatcher = make_dispatcher(config) if (config.work_dir / "ledger.jsonl").exists() else None
    publish(config, entries, dispatcher)
    print(config.release_id)
    return 0


def read_json_list(path: Path):
    import json

    return json.loads(path.read_text(encoding="utf-8"))


if __name__ == "__main__":
    raise SystemExit(main())
