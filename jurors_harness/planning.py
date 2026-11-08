"""Dry-run plan: routes, prompt hashes, and worst-case reservations before any call."""

from __future__ import annotations

from jurors_harness.config import RunConfig, dispatch_allowed
from jurors_harness.io_util import write_json


def write_plan(config: RunConfig, *, included: int, adjudication_cases: int | None) -> dict:
    probes = []
    for name in ("reader_a", "reader_b", "adjudication"):
        route = config.route(name)
        probes.append(
            {
                "stage": name,
                "provider": route.provider,
                "model": route.model,
                "prompt_version": route.prompt_version,
                "prompt_sha256": route.prompt_sha256,
                "worst_case_usd": route.worst_usd(),
                "probe_worst_case_usd": route.worst_usd(max_tokens=config.probe_max_tokens, worst_in=config.probe_worst_in),
            }
        )
    upper_adj = included
    adj_cases = included if adjudication_cases is None else adjudication_cases
    reader_worst = included * config.route("reader_a").worst_usd() + included * config.route("reader_b").worst_usd()
    adj_worst = adj_cases * config.route("adjudication").worst_usd()
    probe_worst = sum(item["probe_worst_case_usd"] for item in probes)
    allowed, why = dispatch_allowed(config)
    plan = {
        "run_id": config.run_id,
        "dispatch_allowed": allowed,
        "dispatch_block": None if allowed else why,
        "included_entries": included,
        "adjudication_cases": adjudication_cases,
        "adjudication_basis": "deduplicated queue" if adjudication_cases is not None else "upper bound: every included entry",
        "routes": probes,
        "worst_case_usd": {
            "probes": probe_worst,
            "readers": reader_worst,
            "adjudication": adj_worst,
            "total": probe_worst + reader_worst + adj_worst,
        },
        "caps": {"total_usd": config.total_usd, "stages": config.stage_budgets},
        "concurrency": config.concurrency,
        "fallback": "none",
        "upper_bound_if_every_line_is_adjudicated": upper_adj * config.route("adjudication").worst_usd(),
    }
    write_json(config.work_dir / "PLAN.json", plan)
    return plan
