"""Real request cache identity regressions; no network."""
from dataclasses import replace
import pytest
from test_router import dispatcher, ok_result

@pytest.mark.parametrize("change", ["crop_hash", "image", "candidate_text", "prior_context", "model", "temperature", "max_tokens", "provider", "full_request"])
def test_material_request_change_invalidates(tmp_path, change):
    machine, fake = dispatcher(tmp_path, lambda r: ok_result())
    args = dict(entry_id="e1", page=1, crop_sha="crop-a", prompt="Candidate A: literal; prior: none", image=b"image-a", reason="single adjudication", validate=lambda *_: (True, ""), shown="crop + candidates")
    assert machine.dispatch_adjudication(**args).kind == "ok"
    assert machine.dispatch_adjudication(**args).kind == "cached"
    if change == "crop_hash": args["crop_sha"] = "crop-b"
    elif change == "image": args["image"] = b"image-b"
    elif change == "candidate_text": args["prompt"] = "Candidate A: changed; prior: none"
    elif change == "prior_context": args["prompt"] += "; prior: changed"
    elif change == "full_request":
        original = machine._request
        def altered(*a, **kw):
            request = original(*a, **kw)
            request.body["provider"] = {"order": ["different"]}
            return request
        machine._request = altered
    else:
        values = {"model":"changed-model", "temperature":0.7, "max_tokens":2, "provider":"scripted"}
        machine.routes["adjudication"] = replace(machine.routes["adjudication"], **{change:values[change]})
    assert machine.dispatch_adjudication(**args).kind == "ok"
    assert len(fake.calls) == 2
    assert machine.dispatch_adjudication(**args).kind == "cached"


def test_reading_request_change_invalidates_after_restart(tmp_path):
    machine, fake = dispatcher(tmp_path, lambda r: ok_result())
    args = dict(stage="reader_a", entry_id="e1", page=1, crop_sha="crop-a", prompt="literal", image=b"a", reason="blind", validate=lambda *_: (True,""))
    assert machine.dispatch_reading(**args).kind == "ok"
    resumed, second = dispatcher(tmp_path, lambda r: ok_result())
    assert resumed.dispatch_reading(**args).kind == "cached"
    args["prompt"] = "literal with changed context"
    assert resumed.dispatch_reading(**args).kind == "ok"
    assert len(second.calls) == 1


def test_publish_selection_rejects_stale_requests(tmp_path, monkeypatch):
    from test_pipeline import CONFIG, ROOT
    from jurors_harness.config import load_config
    from jurors_harness.runbook import execute, make_dispatcher, prepare, compatible_rows
    from jurors_harness.io_util import read_json, write_json
    monkeypatch.setenv("JURORS_HARNESS_AUTHORIZE", "synthetic-1939-demo")
    config = load_config(CONFIG, root=ROOT, work_override=tmp_path / "work")
    assert execute(config) == 0
    entries = prepare(config)
    machine = make_dispatcher(config)
    before = compatible_rows(config, entries, machine)
    a = next(r for r in before if r["step"] == "adjudication")
    qpath = config.work_dir / "queue" / "FINAL-QUEUE.json"
    queue = read_json(qpath)
    item = next(i for i in queue if i["entry_id"] == a["line_id"])
    item["shown"][0]["text"]["name"] = "Changed candidate"
    write_json(qpath, queue)
    after = compatible_rows(config, entries, machine)
    assert a not in after
    machine.routes["reader_a"] = replace(machine.routes["reader_a"], temperature=0.8)
    assert not any(r["step"] == "reader_a" for r in compatible_rows(config, entries, machine))


def test_interruption_after_reservation_never_reissues_unknown(tmp_path):
    def interrupt(_request):
        raise KeyboardInterrupt("deliberate in-flight interruption")
    machine, first = dispatcher(tmp_path, interrupt)
    args = dict(stage="reader_a", entry_id="e1", page=1, crop_sha="crop", prompt="literal", image=b"a", reason="blind", validate=lambda *_:(True,""))
    with pytest.raises(KeyboardInterrupt): machine.dispatch_reading(**args)
    resumed, second = dispatcher(tmp_path, lambda r: ok_result())
    assert resumed.dispatch_reading(**args).kind == "skipped_unknown"
    assert second.calls == []
    assert resumed.encumbrance()["reader_a"]["inflight"] == 1


def test_interruption_after_raw_before_ledger_retains_evidence(tmp_path):
    machine, first = dispatcher(tmp_path, lambda r: ok_result())
    original = machine._persist_raw
    def interrupt(*a, **kw):
        original(*a, **kw)
        raise KeyboardInterrupt("deliberate raw-to-ledger boundary")
    machine._persist_raw = interrupt
    args = dict(stage="reader_a", entry_id="e1", page=1, crop_sha="crop", prompt="literal", image=b"a", reason="blind", validate=lambda *_:(True,""))
    with pytest.raises(KeyboardInterrupt): machine.dispatch_reading(**args)
    assert list((tmp_path / "raw").glob("*.json"))
    resumed, second = dispatcher(tmp_path, lambda r: ok_result())
    assert resumed.dispatch_reading(**args).kind == "skipped_unknown"
    assert not second.calls
