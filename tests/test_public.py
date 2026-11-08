"""Public-repo boundary: secrets, history needles, and the 1940 acceptance constants."""

from __future__ import annotations

import ast
import csv
import json
from pathlib import Path

from jurors_harness.compat1940 import verify_1940
from jurors_harness.constants import RC1_BASELINE_SHA256, RC1_CSV_SHA256, RC1_DISPOSITIONS, RC1_ROWS
from jurors_harness.ledger import build_index, per_thousand
from jurors_harness.parsing import recover_adjudication
from jurors_harness.secret_scan import scan_tree

ROOT = Path(__file__).resolve().parents[1]


def test_repository_tree_has_no_secret_findings():
    findings = scan_tree(ROOT)
    assert findings == []


def test_secret_scan_catches_a_planted_credential_and_path(tmp_path: Path):
    planted = "sk-" + "or-" + "notrealbutlong"
    (tmp_path / "notes.txt").write_text("token " + planted + "\n", encoding="utf-8")
    (tmp_path / "path.txt").write_text("root " + "/" + "Users" + "/ada/notes\n", encoding="utf-8")
    kinds = {finding.pattern for finding in scan_tree(tmp_path)}
    assert "credential" in kinds
    assert "personal-path" in kinds


def test_public_files_exist_and_license_is_undecided():
    for relative in (
        "README.md",
        "CONTRIBUTING.md",
        "CHANGELOG.md",
        "LICENSE",
        ".env.example",
        ".gitignore",
        "docs/devlog/2026-11-08-initial-harness.md",
        "docs/PIPELINE.md",
        "docs/LEDGER.md",
        "docs/POLICIES.md",
        "docs/INTERPRETATIONS.md",
    ):
        assert (ROOT / relative).is_file(), relative
    license_text = (ROOT / "LICENSE").read_text(encoding="utf-8")
    assert "UNDECIDED" in license_text
    assert "MIT" not in license_text.splitlines()[0]
    ignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    for needle in (".env", "runs/", "data/", "scans/", "ledgers/"):
        assert needle in ignore
    assert "!.env.example" in ignore


def test_replay_module_does_not_import_network():
    source = (ROOT / "jurors_harness" / "replay.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module.split(".")[0])
    assert "urllib" not in imported
    assert "socket" not in imported
    assert "requests" not in source


def test_1940_constants_and_verifier(tmp_path: Path):
    assert RC1_ROWS == 3505
    assert RC1_DISPOSITIONS == {"settled": 3058, "corrected": 84, "uncertain": 363}
    assert len(RC1_CSV_SHA256) == 64
    assert len(RC1_BASELINE_SHA256) == 64
    tiny = tmp_path / "tiny.csv"
    with tiny.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["crop_id"], lineterminator="\n")
        writer.writeheader()
        writer.writerow({"crop_id": "x"})
    result = verify_1940(tiny)
    assert result["passed"] is False
    assert result["rows"] == 1


def test_ledger_index_counts_a_call_once(tmp_path: Path):
    row = {
        "schema": "LEDGER-v1",
        "ts": "2026-11-08T00:00:00+00:00",
        "line_id": "e1",
        "model": "test",
        "attempt": 1,
        "step": "reader_a",
        "cost_usd": 1.5,
        "wasted": False,
        "outcome": "ok",
    }
    for name in ("a.jsonl", "b.jsonl"):
        (tmp_path / name).write_text(json.dumps(row) + "\n", encoding="utf-8")
    index = build_index([tmp_path / "a.jsonl", tmp_path / "b.jsonl"])
    assert len(index) == 1
    assert per_thousand(1.5, 3) == 500


def test_parser_keeps_only_unique_field_objects():
    unique = '{"entry_id":"e1","name":{"exact":"Ada","outcome":"confirmed","uncertainty":"","explanation":"clear"}}'
    recovered, detail = recover_adjudication(unique, "e1", ["name", "occupation", "abode"])
    assert recovered is not None
    assert recovered["name"]["exact"] == "Ada"
    assert "occupation" not in detail["recovered"]
    conflict = (
        '{"entry_id":"e1",'
        '"name":{"exact":"Ada","outcome":"confirmed","uncertainty":"","explanation":"a"},'
        '"name":{"exact":"Ade","outcome":"confirmed","uncertainty":"","explanation":"b"}}'
    )
    recovered, detail = recover_adjudication(conflict, "e1", ["name", "occupation", "abode"])
    assert recovered is None
    assert detail["fields"]["name"]["conflict"] is True
