"""Guarded model router.

One probe before each bulk stage. The first billing error stops every paid
stage. 4xx responses are not retried. 5xx and timeouts get at most two
retries, each with a new reservation and backoff. There is no provider fallback.
Completed calls are cached by full material request hash and source identity.
"""

from __future__ import annotations

import json
import os
import socket
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from jurors_harness.constants import BILLING_MARKERS
from jurors_harness.io_util import append_jsonl, read_json, read_jsonl, write_json
from jurors_harness.ledger import append_ledger, cache_identity, ledger_row
from jurors_harness.redact import redact

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"
GEMINI_URL = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


@dataclass
class ProviderRequest:
    provider: str
    url: str
    body: dict
    timeout: float
    env_key: str | None
    stage: str
    entry_id: str
    attempt: int
    model: str


@dataclass
class HttpResult:
    status: int | None
    body: dict | None
    transport_error: str | None = None


class Transport:
    """Network transport. Credentials are read here and are not returned."""

    requires_credentials = True

    def post(self, request: ProviderRequest) -> HttpResult:
        if not request.env_key:
            return HttpResult(status=None, body=None, transport_error="missing_credential")
        key = os.environ.get(request.env_key, "")
        if not key:
            return HttpResult(status=None, body=None, transport_error="missing_credential")
        headers = {"Content-Type": "application/json"}
        if request.provider == "openrouter":
            headers["Authorization"] = "Bearer " + key
        elif request.provider == "gemini":
            headers["x-goog-api-key"] = key
        else:
            return HttpResult(status=None, body=None, transport_error="transport")
        data = json.dumps(request.body).encode("utf-8")
        http = urllib.request.Request(request.url, data=data, method="POST")
        for name, value in headers.items():
            http.add_header(name, value)
        try:
            with urllib.request.urlopen(http, timeout=request.timeout) as response:
                raw = response.read()
                status = response.status
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            status = exc.code
        except (TimeoutError, socket.timeout):
            return HttpResult(status=None, body=None, transport_error="timeout")
        except urllib.error.URLError as exc:
            if isinstance(getattr(exc, "reason", None), socket.timeout):
                return HttpResult(status=None, body=None, transport_error="timeout")
            return HttpResult(status=None, body=None, transport_error="transport")
        try:
            parsed = json.loads(raw.decode("utf-8")) if raw else {}
        except (UnicodeDecodeError, json.JSONDecodeError):
            parsed = {}
        if not isinstance(parsed, dict):
            parsed = {"_non_object": True}
        return HttpResult(status=status, body=parsed, transport_error=None)


class ScriptedTransport:
    """Offline fixture transport. It is selected only when every route is scripted."""

    requires_credentials = False

    def __init__(self, book: dict):
        self.book = book
        self.calls: list[ProviderRequest] = []

    def post(self, request: ProviderRequest) -> HttpResult:
        self.calls.append(request)
        if request.stage == "probe":
            spec = self.book.get("probe") or {}
            content = spec.get("text") or '{"ok": true}'
            return _scripted_result(request, content, spec)
        stage_book = self.book.get(request.stage) or {}
        spec = stage_book.get(request.entry_id)
        if spec is None:
            return HttpResult(status=None, body=None, transport_error="fixture_missing")
        if request.stage == "adjudication":
            payload = {
                "entry_id": request.entry_id,
                "ownership_uncertain": spec.get("ownership_uncertain", False),
                "notes": spec.get("notes", ""),
            }
            for field_name, field_value in (spec.get("fields") or {}).items():
                payload[field_name] = field_value
            content = json.dumps(payload, ensure_ascii=False)
        else:
            reading = spec.get("reading") or {}
            content = json.dumps({"entry_id": request.entry_id, **reading}, ensure_ascii=False)
        return _scripted_result(request, content, spec)


def _scripted_result(request: ProviderRequest, content: str, spec: dict) -> HttpResult:
    return HttpResult(
        status=200,
        body={
            "id": f"scripted-{request.stage}-{request.entry_id}-{request.attempt}",
            "model": request.model,
            "usage": {
                "prompt_tokens": spec.get("tokens_in", 12),
                "completion_tokens": spec.get("tokens_out", 12),
                "cost": spec.get("cost_usd", 0.0001),
            },
            "choices": [{"message": {"content": content}}],
        },
    )


@dataclass
class CallOutcome:
    kind: str
    reason: str
    record: dict | None = None


class Dispatcher:
    def __init__(
        self,
        *,
        run_id: str,
        year: int,
        work: Path,
        routes: dict,
        total_usd: float,
        stage_budgets: dict[str, float],
        transport,
        max_retries: int = 2,
        backoff_seconds: float = 1.0,
        probe_max_tokens: int = 32,
        probe_worst_in: int = 256,
        acknowledge_billing_stop: str | None = None,
        retry_unknown: bool = False,
        now=None,
        sleep=None,
        extra_secret_names: tuple[str, ...] = (),
    ):
        self.run_id = run_id
        self.year = year
        self.work = work
        self.routes = routes
        self.total_usd = total_usd
        self.stage_budgets = stage_budgets
        self.transport = transport
        self.max_retries = max_retries
        self.backoff_seconds = backoff_seconds
        self.probe_max_tokens = probe_max_tokens
        self.probe_worst_in = probe_worst_in
        self.acknowledge_billing_stop = acknowledge_billing_stop
        self.retry_unknown = retry_unknown
        self.now = now or (lambda: datetime.now(timezone.utc).astimezone())
        self.sleep = sleep or (lambda _seconds: None)
        self.extra_secret_names = extra_secret_names
        self.work.mkdir(parents=True, exist_ok=True)
        (self.work / "raw").mkdir(exist_ok=True)
        self.ledger_path = self.work / "ledger.jsonl"
        self.reservation_path = self.work / "reservations.jsonl"
        self.billing_path = self.work / "BILLING-STOP.json"
        self.prompt_log = self.work / "prompts-sent.jsonl"
        self.stop_reason: str | None = None
        self._acknowledge_if_matched()

    def rows(self) -> list[dict]:
        return read_jsonl(self.ledger_path)

    def billing_active(self) -> bool:
        return self.billing_path.exists()

    def probe(self, stage: str) -> CallOutcome:
        route = self.routes[stage]
        line_id = f"PROBE:{stage}"
        prompt = 'Return JSON {"ok":true}.'
        return self._send(
            route=route,
            budget_stage="probe",
            step="probe",
            line_id=line_id,
            page=0,
            crop_sha="",
            reason=f"probe-before-{stage}",
            prompt=prompt,
            prompt_name=f"probe-{route.prompt_version}",
            image=None,
            shown="tiny text probe",
            max_tokens=self.probe_max_tokens,
            worst_in=self.probe_worst_in,
            probe=True,
            validate=lambda text, _obj: (True, ""),
        )

    def dispatch_reading(
        self,
        *,
        stage: str,
        entry_id: str,
        page: int,
        crop_sha: str,
        prompt: str,
        image: bytes,
        reason: str,
        validate,
    ) -> CallOutcome:
        route = self.routes[stage]
        return self._send(
            route=route,
            budget_stage=stage,
            step=stage,
            line_id=entry_id,
            page=page,
            crop_sha=crop_sha,
            reason=reason,
            prompt=prompt,
            prompt_name=route.prompt_version,
            image=image,
            shown="crop only",
            max_tokens=None,
            worst_in=None,
            probe=False,
            validate=validate,
        )

    def dispatch_adjudication(
        self,
        *,
        entry_id: str,
        page: int,
        crop_sha: str,
        prompt: str,
        image: bytes,
        reason: str,
        validate,
        shown: str,
    ) -> CallOutcome:
        route = self.routes["adjudication"]
        return self._send(
            route=route,
            budget_stage="adjudication",
            step="adjudication",
            line_id=entry_id,
            page=page,
            crop_sha=crop_sha,
            reason=reason,
            prompt=prompt,
            prompt_name=route.prompt_version,
            image=image,
            shown=shown,
            max_tokens=None,
            worst_in=None,
            probe=False,
            validate=validate,
        )

    def encumbrance(self) -> dict[str, dict[str, float]]:
        """Measured from the ledger; unknown and in-flight from reservations without a ledger row."""
        rows = self.rows()
        by_attempt = {row["attempt_id"]: row for row in rows if row.get("attempt_id")}
        stages: dict[str, dict[str, float]] = {}

        def bucket(stage: str) -> dict[str, float]:
            return stages.setdefault(stage, {"measured": 0.0, "unknown": 0.0, "inflight": 0.0})

        for row in rows:
            slot = bucket(str(row.get("step") if row.get("step") != "probe" else "probe"))
            # Probe rows use step "probe"; stage budgets for probes are shared.
            if row.get("step") == "probe":
                slot = bucket("probe")
            slot["measured"] += float(row.get("cost_usd") or 0)
            slot["unknown"] += float(row.get("unresolved_charge_reserve_usd") or 0)
        reservations = _latest_reservations(read_jsonl(self.reservation_path))
        for attempt_id, reservation in reservations.items():
            if attempt_id in by_attempt:
                continue
            stage = reservation.get("stage") or "probe"
            slot = bucket(stage)
            amount = float(reservation.get("reserved_usd") or 0)
            if reservation.get("state") == "unknown":
                slot["unknown"] += amount
            else:
                slot["inflight"] += amount
        return stages

    def _send(
        self,
        *,
        route,
        budget_stage: str,
        step: str,
        line_id: str,
        page: int,
        crop_sha: str,
        reason: str,
        prompt: str,
        prompt_name: str,
        image: bytes | None,
        shown: str,
        max_tokens: int | None,
        worst_in: int | None,
        probe: bool,
        validate,
    ) -> CallOutcome:
        # Hash the exact wire body (including rendered candidates, priors, and image),
        # destination, and material transport settings before consulting saved calls.
        version = f"{route.prompt_version} sha256:{route.prompt_sha256}"
        if probe:
            version = f"probe sha256:{route.prompt_sha256}"
        request = self._request(route, prompt, image, max_tokens or route.max_tokens, line_id, 1)
        request_sha = material_request_sha256(request)
        existing = [
            row
            for row in self.rows()
            if cache_identity(row)
            == (self.year, crop_sha, step, route.model, version, line_id, request_sha)
        ]
        success = next((row for row in existing if row.get("outcome") == "ok"), None)
        if success is not None:
            return CallOutcome("cached", "completed", success)
        if step == "adjudication":
            completed = next((row for row in existing if row.get("http_status") == 200), None)
            if completed is not None:
                return CallOutcome("cached", "adjudication-already-completed", completed)
        terminal = _terminal_error(existing)
        if terminal is not None:
            return CallOutcome("skipped_terminal", terminal.get("wasted_reason") or "terminal", terminal)
        if self.billing_active():
            self.stop_reason = "billing"
            return CallOutcome("stopped", "billing")
        unknown = self._unknown_inflight(line_id, step)
        if unknown is not None and not self.retry_unknown:
            return CallOutcome("skipped_unknown", "unknown-outcome-reserve-held", None)
        worst = route.worst_usd(max_tokens=max_tokens, worst_in=worst_in)
        prior_attempts = len(existing)
        attempts_allowed = 1 if _non_retriable(existing) else self.max_retries + 1
        if prior_attempts >= attempts_allowed:
            return CallOutcome("skipped_terminal", "retries-exhausted", existing[-1] if existing else None)
        outcome = CallOutcome("error", "not-sent")
        attempt = prior_attempts
        while attempt < attempts_allowed:
            attempt += 1
            room = self._room(budget_stage, worst)
            if room is not None:
                self.stop_reason = room
                return CallOutcome("stopped", room, outcome.record)
            attempt_id = str(uuid.uuid4())
            self._reserve(attempt_id, budget_stage, line_id, worst, "open")
            started = self.now()
            request = self._request(route, prompt, image, max_tokens or route.max_tokens, line_id, attempt)
            try:
                result = self.transport.post(request)
            except Exception as exc:  # noqa: BLE001 — provider bugs must not escape with headers attached
                result = HttpResult(status=None, body=None, transport_error="transport")
                _ = redact(str(exc), extra_names=self.extra_secret_names)
            record, retriable, billing = self._interpret(
                result=result,
                route=route,
                step=step,
                line_id=line_id,
                page=page,
                crop_sha=crop_sha,
                reason=reason,
                version=version,
                attempt=attempt,
                attempt_id=attempt_id,
                worst=worst,
                shown=shown,
                started=started,
                probe=probe,
                validate=validate,
                max_tokens=max_tokens or route.max_tokens,
                image=image,
                prompt=prompt,
            )
            record["input_sha256"]["material_request"] = request_sha
            self._persist_raw(attempt_id, result, record)
            append_ledger(self.ledger_path, record)
            append_jsonl(
                self.prompt_log,
                {
                    "attempt_id": attempt_id,
                    "line_id": line_id,
                    "step": step,
                    "prompt_sha256": record["input_sha256"].get("prompt"),
                    "prompt": prompt,
                },
            )
            unknown_charge = float(record["unresolved_charge_reserve_usd"]) > 0
            self._reserve(
                attempt_id,
                budget_stage,
                line_id,
                worst,
                "unknown" if unknown_charge else "reconciled",
                actual=float(record["cost_usd"]),
            )
            outcome = CallOutcome("ok" if record["outcome"] == "ok" else "error", record.get("wasted_reason") or "", record)
            if billing:
                self._write_billing_stop(record)
                self.stop_reason = "billing"
                return CallOutcome("stopped", "billing", record)
            if record["outcome"] == "ok" or not retriable:
                return outcome
            if attempt >= attempts_allowed:
                return outcome
            self.sleep(self.backoff_seconds * (2 ** (attempt - 1)))
        return outcome

    def _room(self, stage: str, worst: float) -> str | None:
        state = self.encumbrance()
        total = sum(slot["measured"] + slot["unknown"] + slot["inflight"] for slot in state.values())
        stage_state = state.get(stage, {"measured": 0.0, "unknown": 0.0, "inflight": 0.0})
        stage_total = stage_state["measured"] + stage_state["unknown"] + stage_state["inflight"]
        if total + worst - self.total_usd > 1e-12:
            return "total_cap"
        budget = self.stage_budgets.get(stage)
        if budget is None:
            return "stage_cap"
        if stage_total + worst - budget > 1e-12:
            return "stage_cap"
        return None

    def _reserve(self, attempt_id: str, stage: str, line_id: str, amount: float, state: str, actual: float | None = None) -> None:
        append_jsonl(
            self.reservation_path,
            {
                "schema": "RESERVATION-v1",
                "attempt_id": attempt_id,
                "stage": stage,
                "line_id": line_id,
                "reserved_usd": amount,
                "state": state,
                "actual_usd": actual,
                "ts": self.now().isoformat(),
            },
        )

    def _request(self, route, prompt: str, image: bytes | None, max_tokens: int, line_id: str, attempt: int) -> ProviderRequest:
        if route.provider == "gemini":
            url = GEMINI_URL.format(model=route.model)
            parts: list[dict] = [{"text": prompt}]
            if image is not None:
                import base64

                parts.append({"inline_data": {"mime_type": _mime(image), "data": base64.b64encode(image).decode("ascii")}})
            generation = {
                "temperature": route.temperature,
                "maxOutputTokens": max_tokens,
                "responseMimeType": "application/json",
            }
            if route.thinking_level:
                generation["thinkingConfig"] = {"thinkingLevel": route.thinking_level}
            body = {"contents": [{"parts": parts}], "generationConfig": generation}
        else:
            url = OPENROUTER_URL if route.provider == "openrouter" else "scripted://local"
            content: list[dict] | str
            if image is not None:
                import base64

                content = [
                    {"type": "text", "text": prompt},
                    {"type": "image_url", "image_url": {"url": f"data:{_mime(image)};base64," + base64.b64encode(image).decode("ascii")}},
                ]
            else:
                content = prompt
            body = {
                "model": route.model,
                "temperature": route.temperature,
                "max_tokens": max_tokens,
                "response_format": {"type": "json_object"},
                "usage": {"include": True},
                "messages": [{"role": "user", "content": content}],
            }
        return ProviderRequest(
            provider=route.provider,
            url=url,
            body=body,
            timeout=route.timeout,
            env_key=route.env_key,
            stage="probe" if line_id.startswith("PROBE:") else route.name,
            entry_id=line_id,
            attempt=attempt,
            model=route.model,
        )

    def _interpret(
        self,
        *,
        result: HttpResult,
        route,
        step: str,
        line_id: str,
        page: int,
        crop_sha: str,
        reason: str,
        version: str,
        attempt: int,
        attempt_id: str,
        worst: float,
        shown: str,
        started,
        probe: bool,
        validate,
        max_tokens: int,
        image: bytes | None,
        prompt: str,
    ) -> tuple[dict, bool, bool]:
        from jurors_harness.hashing import sha256_bytes, sha256_text

        status = result.status
        body = result.body or {}
        transport_error = result.transport_error
        raw_text, usage, model_reported, request_id, error_message = _extract(route.provider, body)
        billing = _is_billing(status, error_message)
        retriable = False
        unknown = False
        if transport_error == "timeout":
            error_message = "timeout"
            retriable = True
            unknown = True
        elif transport_error == "fixture_missing":
            error_message = "scripted fixture missing"
            retriable = False
            unknown = False
        elif transport_error:
            error_message = transport_error
            retriable = False
            unknown = transport_error != "missing_credential"
        elif billing:
            error_message = redact(error_message or f"HTTP {status}", extra_names=self.extra_secret_names)
            retriable = False
        elif status is None or status >= 500:
            error_message = redact(error_message or f"HTTP {status}", extra_names=self.extra_secret_names)
            retriable = True
        elif status >= 400:
            error_message = redact(error_message or f"HTTP {status}", extra_names=self.extra_secret_names)
            retriable = False
        tokens_in = int((usage or {}).get("prompt_tokens") or (usage or {}).get("promptTokenCount") or 0)
        tokens_out = int((usage or {}).get("completion_tokens") or 0)
        if "candidatesTokenCount" in (usage or {}):
            tokens_out = int(usage.get("candidatesTokenCount") or 0) + int(usage.get("thoughtsTokenCount") or 0)
        reported_cost = None if not usage else usage.get("cost")
        if reported_cost is None and not unknown and transport_error is None and status == 200:
            reported_cost = (tokens_in * route.price_in + tokens_out * route.price_out) / 1_000_000
        if unknown or (status == 200 and not usage):
            unknown = True
        cost = 0.0 if reported_cost is None else float(reported_cost)
        if unknown and reported_cost is None:
            cost = 0.0
        hold = max(0.0, worst - cost) if unknown else 0.0
        parsed = None
        schema_error = ""
        if status == 200 and not transport_error and not billing:
            if probe:
                parsed = {"ok": True}
            else:
                parsed, schema_error = _parse_json_object(raw_text)
                if schema_error:
                    parsed = None
                else:
                    ok, schema_error = validate(raw_text or "", parsed)
                    if not ok:
                        parsed = parsed if isinstance(parsed, dict) else None
                        if not schema_error:
                            schema_error = "schema failure"
        wasted_reason = ""
        outcome = "ok"
        if transport_error or billing or (status is not None and status >= 400) or schema_error:
            outcome = "error"
            wasted_reason = schema_error or error_message or "error"
        elif probe:
            wasted_reason = "billing probe overhead"
        wasted = outcome == "error" or probe
        # Schema failure is a completed HTTP response: do not retry.
        if schema_error:
            retriable = False
        if probe and outcome != "ok" and not billing and retriable:
            retriable = True
        finished = self.now()
        wall = max(0.0, (finished - started).total_seconds())
        record = ledger_row(
            run_id=self.run_id,
            ts=started.isoformat(),
            year=self.year,
            page=page,
            line_id=line_id,
            model=route.model,
            model_reported=model_reported,
            step=step,
            reason=reason,
            prompt_version=version,
            settings={
                "temperature": route.temperature,
                "max_tokens": max_tokens,
                "shown": shown,
                "concurrency": 1,
                "provider": route.provider,
            },
            attempt=attempt,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
            wasted=wasted,
            wasted_reason=wasted_reason,
            wall_secs=round(wall, 3),
            outcome=outcome,
            crop_sha256=crop_sha,
            provider=route.provider,
            provider_request_id=request_id,
            input_sha256={"prompt": sha256_text(prompt), "image": sha256_bytes(image) if image else ""},
            raw_response_relpath=f"raw/{attempt_id}.json",
            reservation_usd=worst,
            unresolved_charge_reserve_usd=hold,
            http_status=status,
            billing_error=billing,
            attempt_id=attempt_id,
            raw_text=raw_text,
            parsed=parsed if outcome == "ok" or (parsed and not probe) else parsed,
            supersedes=None,
        )
        return record, retriable and not billing, billing

    def _persist_raw(self, attempt_id: str, result: HttpResult, record: dict) -> None:
        payload = {
            "attempt_id": attempt_id,
            "http_status": result.status,
            "transport_error": result.transport_error,
            "raw_text": record.get("raw_text"),
            "error_redacted": redact(record.get("wasted_reason") or "", extra_names=self.extra_secret_names),
        }
        path = self.work / "raw" / f"{attempt_id}.json"
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        # Raw file is on disk before the ledger append in the caller... caller persists raw first.
        # This method is invoked before append_ledger.

    def _write_billing_stop(self, record: dict) -> None:
        if self.billing_path.exists():
            return
        write_json(
            self.billing_path,
            {
                "ts": record["ts"],
                "http_status": record.get("http_status"),
                "stage": record.get("step"),
                "line_id": record.get("line_id"),
                "message_redacted": redact(record.get("wasted_reason") or "", extra_names=self.extra_secret_names),
                "run_id": self.run_id,
                "note": "The paid dispatcher is stopped. A new explicit acknowledgment is required.",
            },
        )

    def _acknowledge_if_matched(self) -> None:
        if not self.billing_path.exists() or not self.acknowledge_billing_stop:
            return
        payload = read_json(self.billing_path)
        if isinstance(payload, dict) and payload.get("ts") == self.acknowledge_billing_stop:
            archived = self.work / f"BILLING-STOP.{payload['ts'].replace(':', '')}.acknowledged.json"
            self.billing_path.replace(archived)

    def _unknown_inflight(self, line_id: str, step: str) -> dict | None:
        rows = {row.get("attempt_id") for row in self.rows()}
        for attempt_id, reservation in _latest_reservations(read_jsonl(self.reservation_path)).items():
            if attempt_id in rows:
                continue
            if reservation.get("line_id") == line_id and reservation.get("state") in {"open", "unknown"}:
                if step == "probe" and str(line_id).startswith("PROBE:"):
                    return reservation
                if reservation.get("stage") == step or step == "probe":
                    return reservation
        return None


def _latest_reservations(rows: list[dict]) -> dict[str, dict]:
    latest: dict[str, dict] = {}
    for row in rows:
        latest[row["attempt_id"]] = row
    return latest


def _terminal_error(existing: list[dict]) -> dict | None:
    if any(row.get("outcome") == "ok" for row in existing):
        return None
    if not existing:
        return None
    if _non_retriable(existing) and existing[-1].get("outcome") != "ok":
        # A single non-retriable error is terminal. Retriable errors are terminal only once retries are spent.
        last = existing[-1]
        if not _row_retriable(last):
            return last
    retriable_rows = [row for row in existing if _row_retriable(row)]
    if len(existing) >= 3 and all(_row_retriable(row) for row in existing):
        return existing[-1]
    if len(retriable_rows) >= 3:
        return retriable_rows[-1]
    return None


def _non_retriable(existing: list[dict]) -> bool:
    return any(not _row_retriable(row) and row.get("outcome") != "ok" for row in existing)


def _row_retriable(row: dict) -> bool:
    if row.get("billing_error"):
        return False
    status = row.get("http_status")
    reason = (row.get("wasted_reason") or "").lower()
    if status == 200 and row.get("outcome") == "error":
        return False
    if reason.startswith("timeout") or (status is not None and status >= 500):
        return True
    if "http 5" in reason:
        return True
    return False


def _is_billing(status: int | None, message: str) -> bool:
    if status == 402:
        return True
    lowered = (message or "").lower()
    if status is not None and status >= 400 and any(marker in lowered for marker in BILLING_MARKERS):
        return True
    return False


def _extract(provider: str, body: dict) -> tuple[str | None, dict | None, str | None, str | None, str]:
    if not body:
        return None, None, None, None, ""
    if body.get("error"):
        error = body["error"]
        message = error.get("message", "") if isinstance(error, dict) else str(error)
        return None, body.get("usage") if isinstance(body.get("usage"), dict) else None, body.get("model"), body.get("id"), message
    if provider == "gemini" and "candidates" in body:
        parts = (((body.get("candidates") or [{}])[0].get("content") or {}).get("parts") or [])
        text = "".join(part.get("text", "") for part in parts if not part.get("thought"))
        usage = body.get("usageMetadata") or {}
        return text, usage, body.get("modelVersion"), body.get("responseId"), ""
    choices = body.get("choices") or []
    message = ""
    if choices:
        message = ((choices[0] or {}).get("message") or {}).get("content")
    usage = body.get("usage") if isinstance(body.get("usage"), dict) else None
    return message, usage, body.get("model"), body.get("id"), ""


def _parse_json_object(raw: str | None) -> tuple[dict | None, str]:
    if not raw:
        return None, "empty response"
    text = raw.strip()
    if text.startswith("```"):
        text = text.removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end < start:
        return None, "json parse"
    try:
        obj = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None, "json parse"
    if not isinstance(obj, dict):
        return None, "json was not an object"
    return obj, ""


def _mime(image: bytes) -> str:
    if image.startswith(b"\x89PNG"):
        return "image/png"
    if image.startswith(b"\xff\xd8"):
        return "image/jpeg"
    if image.startswith(b"GIF"):
        return "image/gif"
    if image.startswith(b"RIFF"):
        return "image/webp"
    return "application/octet-stream"


def material_request_sha256(request: ProviderRequest) -> str:
    """Canonical wire request identity. Credentials and attempt IDs are never included."""
    from jurors_harness.hashing import sha256_text
    return sha256_text(json.dumps({
        "provider": request.provider, "url": request.url,
        "body": request.body, "timeout": request.timeout,
        "model": request.model,
    }, sort_keys=True, ensure_ascii=False, separators=(",", ":")))
