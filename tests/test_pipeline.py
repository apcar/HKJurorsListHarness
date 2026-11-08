"""Synthetic year: scripted readers, replay, isolation, and a billing stop."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from jurors_harness.config import load_config
from jurors_harness.io_util import read_csv, read_json, read_jsonl
from jurors_harness.router import HttpResult
from jurors_harness.runbook import execute

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "configs" / "examples" / "synthetic-year.json"
FORBIDDEN = (
    "REFONLY-OCCUPATION",
    "PRIORONLY-SMYTH",
    "XQZTYPO",
    "gwulo",
    "/" + "Users" + "/",
    "/" + "workspace" + "/",
)


def test_scripted_year_round_trip(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JURORS_HARNESS_AUTHORIZE", "synthetic-1939-demo")
    work = tmp_path / "run"
    config = load_config(CONFIG, root=ROOT, work_override=work)
    assert execute(config, source=CONFIG) == 0
    release = work / "release" / "1939-synthetic-rc1"
    dispositions = {row["entry_id"]: row for row in read_csv(release / "DISPOSITIONS.csv")}
    counts = {}
    for row in dispositions.values():
        counts[row["disposition"]] = counts.get(row["disposition"], 0) + 1
    assert counts == {"SETTLED": 2, "CORRECTED": 2, "UNCERTAIN": 2, "EXCLUDED": 1}
    by_suffix = {key.split("-")[-1]: value for key, value in dispositions.items()}
    assert by_suffix["e0004"]["juror_class"] == "Special"
    assert by_suffix["e0001"]["juror_class"] == "Common"
    assert by_suffix["e0004"]["physical_page"] == "1"
    fields = read_csv(release / "FIELD-DECISIONS.csv")
    occupation = {
        (row["entry_id"].split("-")[-1], row["field"]): row["release_text"]
        for row in fields
    }
    assert occupation[("e0003", "occupation")] == "clerk"
    assert occupation[("e0002", "occupation")] == "Ld."
    assert occupation[("e0002", "name")].startswith("*José")
    assert occupation[("e0007", "name")] == "[UNRESOLVED]"
    flags = {row["entry_id"].split("-")[-1]: row for row in read_csv(release / "REFERENCE-FLAGS.csv")}
    assert flags["e0001"]["reference_difference_fields"] == "occupation"
    assert flags["e0001"]["decision_changed_by_reference"] == "false"
    assert flags["e0004"]["reference_available"] == "false"
    audit = read_json(work / "queue" / "CANDIDATE-ORDER-AUDIT.json")
    assert audit["balanced"] is True
    for path in release.rglob("*"):
        if path.is_file():
            text = path.read_text(encoding="utf-8", errors="replace")
            for token in FORBIDDEN:
                assert token not in text, path.name
    sent = [json.loads(line)["prompt"].lower() for line in (work / "prompts-sent.jsonl").read_text(encoding="utf-8").splitlines()]
    for prompt in sent:
        for token in ("gwulo", "claude", "gemini", "anthropic", "sonnet", "xqztypo", "prioronly", "refonly", "reader_a"):
            assert token not in prompt
    replay_out = tmp_path / "replayed.csv"
    completed = subprocess.run(
        [sys.executable, "-m", "jurors_harness", "replay", "--rcdir", str(release), "--output", str(replay_out)],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    assert replay_out.read_bytes() == (release / "1939-synthetic-rc1.csv").read_bytes()
    recorded = read_json(release / "REPLAY-RESULT.json")
    assert completed.stdout.strip() == recorded["release_sha256"]
    before = (work / "ledger.jsonl").read_bytes()
    assert execute(config, source=CONFIG) == 0
    assert (work / "ledger.jsonl").read_bytes() == before
    census = read_json(work / "census" / "CENSUS.json")
    assert census["source_census_established"] is False
    assert census["page_one_included_entries"] == 1
    frame = read_csv(work / "sample" / "SAMPLE-FRAME.csv")
    assert "gwulo" not in {row["stratum"] for row in frame}
    summary = read_json(release / "SAMPLE-SUMMARY.json")
    assert summary["label"] == "same-sample post-repair"
    rows = read_jsonl(work / "ledger.jsonl")
    assert any(row["step"] == "probe" for row in rows)
    assert all(row["schema"] == "LEDGER-v1" for row in rows)


def test_unauthorized_run_does_not_dispatch(tmp_path: Path, monkeypatch):
    monkeypatch.delenv("JURORS_HARNESS_AUTHORIZE", raising=False)
    work = tmp_path / "unauth"
    config = load_config(CONFIG, root=ROOT, work_override=work)
    assert execute(config, source=CONFIG) == 0
    assert not (work / "release").exists()
    assert "dispatch-not-authorized" in (work / "RESUME.md").read_text(encoding="utf-8")
    assert not (work / "ledger.jsonl").exists()


def test_billing_stop_through_the_year_pipeline(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("JURORS_HARNESS_AUTHORIZE", "synthetic-1939-demo")
    work = tmp_path / "billed"

    class Stop:
        requires_credentials = False

        def __init__(self):
            self.calls = 0

        def post(self, _request):
            self.calls += 1
            return HttpResult(402, {"error": {"message": "payment required"}})

    transport = Stop()
    config = load_config(CONFIG, root=ROOT, work_override=work)
    assert execute(config, transport=transport, source=CONFIG) == 3
    assert transport.calls == 1
    release = work / "release" / "1939-synthetic-rc1"
    rows = read_csv(release / "DISPOSITIONS.csv")
    included = [row for row in rows if row["included"] == "true"]
    assert included
    assert all(row["disposition"] == "UNCERTAIN" for row in included)
    assert all(row["operational_state"] == "billing_stopped" for row in included)
    resume = (work / "RESUME.md").read_text(encoding="utf-8")
    assert "billing_stop" in resume
    assert "acknowledge_billing_stop" in resume


def test_network_shaped_config_refuses_to_dispatch_without_authority(monkeypatch):
    monkeypatch.delenv("JURORS_HARNESS_AUTHORIZE", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    config = load_config(ROOT / "configs" / "examples" / "openrouter-gemini.json", root=ROOT, work_override=Path("runs/unused"))
    from jurors_harness.config import dispatch_allowed

    allowed, reason = dispatch_allowed(config)
    assert not allowed
    assert "dispatch" in reason


def test_absolute_config_path_is_rejected(tmp_path: Path):
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw["inputs_dir"] = "/tmp/scans"
    path = tmp_path / "bad.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        load_config(path, root=ROOT)
    except Exception as exc:  # noqa: BLE001
        assert "relative" in str(exc).lower() or "absolute" in str(exc).lower()
    else:
        raise AssertionError("absolute inputs_dir was accepted")


def test_stage_budgets_cannot_exceed_the_total(tmp_path: Path):
    raw = json.loads(CONFIG.read_text(encoding="utf-8"))
    raw["caps"]["total_usd"] = 0.1
    path = tmp_path / "over.json"
    path.write_text(json.dumps(raw), encoding="utf-8")
    try:
        load_config(path, root=ROOT)
    except Exception as exc:  # noqa: BLE001
        assert "stage budgets" in str(exc)
    else:
        raise AssertionError("over-budget stages were accepted")
