"""Billing stop, retry limits, resume, and caps. Providers are mocked."""

from __future__ import annotations

import json
from pathlib import Path

from jurors_harness.router import Dispatcher, HttpResult, ProviderRequest

ROOT = Path(__file__).resolve().parents[1]


def route(name: str, *, price_in: float = 1000.0, worst_in: int = 1000, max_tokens: int = 1, prompt_sha: str = "sha-a"):
    from jurors_harness.config import Route

    return Route(
        name=name,
        provider="openrouter",
        model="test-model",
        env_key="OPENROUTER_API_KEY",
        prompt_version="blind-v1",
        prompt_path=ROOT / "prompts" / "blind-v1.txt",
        prompt_text="template",
        prompt_sha256=prompt_sha,
        temperature=0,
        max_tokens=max_tokens,
        price_in=price_in,
        price_out=0,
        worst_in_tokens=worst_in,
        timeout=5,
    )


class Fake:
    requires_credentials = False

    def __init__(self, handler):
        self.handler = handler
        self.calls: list[ProviderRequest] = []

    def post(self, request: ProviderRequest) -> HttpResult:
        self.calls.append(request)
        return self.handler(request)


def dispatcher(tmp_path: Path, handler, *, total: float = 10, stages: dict | None = None, **kwargs) -> tuple[Dispatcher, Fake]:
    fake = Fake(handler)
    budgets = stages or {"probe": 2, "reader_a": 4, "reader_b": 4, "adjudication": 4, "sample_label": 1}
    machine = Dispatcher(
        run_id="router-test",
        year=1939,
        work=tmp_path,
        routes={"reader_a": route("reader_a"), "reader_b": route("reader_b"), "adjudication": route("adjudication")},
        total_usd=total,
        stage_budgets=budgets,
        transport=fake,
        backoff_seconds=1,
        probe_max_tokens=8,
        probe_worst_in=10,
        sleep=kwargs.pop("sleep", lambda _seconds: None),
        **kwargs,
    )
    return machine, fake


def http(status: int, message: str = "nope") -> HttpResult:
    return HttpResult(status, {"error": {"message": message}, "id": "err"})


def ok_result(entry_id: str = "e1") -> HttpResult:
    body = {
        "id": "req-1",
        "model": "test-model",
        "usage": {"prompt_tokens": 4, "completion_tokens": 2, "cost": 0.0002},
        "choices": [{"message": {"content": json.dumps({"entry_id": entry_id, "ok": True})}}],
    }
    return HttpResult(200, body)


def test_billing_stops_every_later_call(tmp_path: Path):
    machine, fake = dispatcher(tmp_path, lambda _request: http(402, "insufficient credits"))
    first = machine.probe("reader_a")
    second = machine.probe("reader_b")
    third = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="abc",
        prompt="p",
        image=b"png",
        reason="blind",
        validate=lambda _raw, _parsed: (True, ""),
    )
    assert first.reason == "billing"
    assert second.reason == "billing"
    assert third.reason == "billing"
    assert len(fake.calls) == 1
    text = (tmp_path / "BILLING-STOP.json").read_text(encoding="utf-8")
    assert "Bearer" not in text
    assert "sk-" not in text


def test_billing_phrase_on_403_is_a_stop(tmp_path: Path):
    machine, fake = dispatcher(tmp_path, lambda _request: http(403, "available credits depleted"))
    machine.probe("reader_a")
    machine.dispatch_reading(
        stage="reader_b",
        entry_id="e1",
        page=1,
        crop_sha="abc",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert len(fake.calls) == 1
    assert machine.billing_active()


def test_4xx_is_not_retried(tmp_path: Path):
    for status in (400, 401, 403, 404, 422, 429):
        work = tmp_path / str(status)
        machine, fake = dispatcher(work, lambda _request, status=status: http(status, "nope"))
        outcome = machine.dispatch_reading(
            stage="reader_a",
            entry_id="e1",
            page=1,
            crop_sha="crop",
            prompt="p",
            image=b"x",
            reason="blind",
            validate=lambda *_: (True, ""),
        )
        assert len(fake.calls) == 1, status
        assert outcome.kind == "error"
        assert not machine.billing_active()


def test_5xx_retries_twice_then_stops(tmp_path: Path):
    sleeps: list[float] = []
    machine, fake = dispatcher(tmp_path, lambda _request: http(503, "unavailable"), sleep=sleeps.append)
    outcome = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=2,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert len(fake.calls) == 3
    assert sleeps == [1.0, 2.0]
    assert outcome.kind == "error"
    assert {call.provider for call in fake.calls} == {"openrouter"}
    assert all(call.url.startswith("https://openrouter.ai/") for call in fake.calls)


def test_timeout_keeps_reserve_and_blocks_the_next_call(tmp_path: Path):
    def timeout(_request):
        return HttpResult(None, None, "timeout")

    machine, fake = dispatcher(tmp_path, timeout, total=1, stages={"probe": 1, "reader_a": 1, "reader_b": 1, "adjudication": 1, "sample_label": 1})
    # worst-case for this route is (1000 * 1000) / 1e6 = 1.0, so one timeout fills the cap.
    first = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    second = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e2",
        page=1,
        crop_sha="crop-2",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert len(fake.calls) == 1
    assert first.record is not None
    assert first.record["unresolved_charge_reserve_usd"] == 1
    assert second.reason == "total_cap"
    resumed, fake2 = dispatcher(
        tmp_path,
        timeout,
        total=1,
        stages={"probe": 1, "reader_a": 1, "reader_b": 1, "adjudication": 1, "sample_label": 1},
    )
    again = resumed.dispatch_reading(
        stage="reader_a",
        entry_id="e2",
        page=1,
        crop_sha="crop-2",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert again.reason == "total_cap"
    assert fake2.calls == []


def test_schema_failure_is_not_retried(tmp_path: Path):
    machine, fake = dispatcher(tmp_path, lambda _request: ok_result())
    outcome = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (False, "schema failure"),
    )
    assert len(fake.calls) == 1
    assert outcome.record is not None
    assert outcome.record["raw_text"]
    assert (tmp_path / "raw").exists()
    assert list((tmp_path / "raw").glob("*.json"))


def test_resume_skips_a_completed_call(tmp_path: Path):
    machine, fake = dispatcher(tmp_path, lambda _request: ok_result())
    machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="please read",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    again, fake2 = dispatcher(tmp_path, lambda _request: ok_result())
    cached = again.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="please read",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert cached.kind == "cached"
    assert fake2.calls == []
    assert len(machine.rows()) == 1


def test_prompt_version_change_is_not_a_cache_hit(tmp_path: Path):
    machine, _fake = dispatcher(tmp_path, lambda _request: ok_result())
    machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    other = route("reader_a", prompt_sha="sha-b")
    again, fake2 = dispatcher(tmp_path, lambda _request: ok_result())
    again.routes["reader_a"] = other
    outcome = again.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert outcome.kind == "ok"
    assert len(fake2.calls) == 1


def test_cap_blocks_before_any_call(tmp_path: Path):
    machine, fake = dispatcher(tmp_path, lambda _request: ok_result(), total=0.01)
    outcome = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert outcome.reason == "total_cap"
    assert fake.calls == []


def test_stage_budget_does_not_spend_another_stage(tmp_path: Path):
    machine, fake = dispatcher(
        tmp_path,
        lambda _request: ok_result(),
        total=10,
        stages={"probe": 2, "reader_a": 0.01, "reader_b": 4, "adjudication": 4, "sample_label": 1},
    )
    blocked = machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    allowed = machine.dispatch_reading(
        stage="reader_b",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"x",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    assert blocked.reason == "stage_cap"
    assert allowed.kind == "ok"
    assert len(fake.calls) == 1
    assert fake.calls[0].stage == "reader_b"


def test_gemini_request_does_not_carry_the_credential(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "test-secret-value-0123456789")
    machine, fake = dispatcher(tmp_path, lambda _request: ok_result())
    gemini = route("reader_a")
    machine.routes["reader_a"] = type(gemini)(
        **{
            **gemini.__dict__,
            "provider": "gemini",
            "model": "gemini-3.8-flash",
            "env_key": "GEMINI_API_KEY",
        }
    )
    machine.dispatch_reading(
        stage="reader_a",
        entry_id="e1",
        page=1,
        crop_sha="crop",
        prompt="p",
        image=b"\x89PNG\r\n",
        reason="blind",
        validate=lambda *_: (True, ""),
    )
    request = fake.calls[0]
    blob = json.dumps(request.body)
    assert "generativelanguage.googleapis.com" in request.url
    assert "key=" not in request.url
    assert "test-secret-value" not in request.url
    assert "test-secret-value" not in blob
    assert request.env_key == "GEMINI_API_KEY"


def test_acknowledge_billing_stop_archives_the_marker(tmp_path: Path):
    machine, _fake = dispatcher(tmp_path, lambda _request: http(402, "payment required"))
    stopped = machine.probe("reader_a")
    stamp = stopped.record["ts"]
    resumed, fake2 = dispatcher(
        tmp_path,
        lambda _request: ok_result(),
        acknowledge_billing_stop=stamp,
    )
    assert not resumed.billing_active()
    outcome = resumed.probe("reader_b")
    assert outcome.kind == "ok"
    assert fake2.calls
