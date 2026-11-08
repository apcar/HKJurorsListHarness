"""Human-readable status written whenever a run stops or finishes."""

from __future__ import annotations

from jurors_harness.config import RunConfig
from jurors_harness.io_util import read_json, write_json
from jurors_harness.ledger import money_totals


def write_resume(config: RunConfig, *, reason: str, stage: str, dispatcher=None, notes: list[str] | None = None) -> None:
    work = config.work_dir
    work.mkdir(parents=True, exist_ok=True)
    rows = dispatcher.rows() if dispatcher is not None else []
    totals = money_totals(rows)
    enc = dispatcher.encumbrance() if dispatcher is not None else {}
    billing = bool(dispatcher and dispatcher.billing_active())
    billing_doc = None
    if billing and (work / "BILLING-STOP.json").exists():
        billing_doc = read_json(work / "BILLING-STOP.json")
    census_path = work / "census" / "CENSUS.json"
    census = read_json(census_path) if census_path.exists() else {}
    included = (census.get("measures") or {}).get("included_entries")
    payload = {
        "run_id": config.run_id,
        "year": config.year,
        "witness": config.witness,
        "edition": config.edition,
        "release_id": config.release_id,
        "reason": reason,
        "stage": stage,
        "billing_stop": billing,
        "billing": billing_doc,
        "included_entries": included,
        "ledger_rows": len(rows),
        "measured_usd": totals["measured_usd"],
        "wasted_usd": totals["wasted_usd"],
        "unknown_reserve_usd": totals["unknown_reserve_usd"],
        "encumbrance": enc,
        "notes": notes or [],
        "new_authorization_required": billing,
    }
    write_json(work / "RESUME.json", payload)
    lines = [
        "# Resume status",
        "",
        f"- Run: {config.run_id}",
        f"- Year: {config.year}",
        f"- Witness: {config.witness}",
        f"- Edition: {config.edition}",
        f"- Release: {config.release_id}",
        f"- Reason: {reason}",
        f"- Stage: {stage}",
        f"- Included entries: {included if included is not None else 'not frozen yet'}",
        f"- Ledger rows: {len(rows)}",
        f"- Measured USD: {totals['measured_usd']}",
        f"- Wasted USD: {totals['wasted_usd']}",
        f"- Unknown-charge reserves USD: {totals['unknown_reserve_usd']}",
        f"- Billing stop: {billing}",
        "",
    ]
    if billing and isinstance(billing_doc, dict):
        lines += [
            "Paid dispatch is stopped for every stage and every route.",
            "No fallback provider was contacted.",
            "To resume after a real billing failure, fund the account, then set",
            f"`authority.acknowledge_billing_stop` to `{billing_doc.get('ts')}`",
            "and authorize the run again. Do not delete the ledger.",
            "",
        ]
    if notes:
        lines.append("## Notes")
        lines.append("")
        for note in notes:
            lines.append(f"- {note}")
        lines.append("")
    lines += [
        "Completed calls are cached by year, crop hash, stage, model, and prompt version.",
        "A restart skips those calls and does not pay them again.",
        "In-flight reservations without a saved response stay unknown and are not treated as free.",
        "",
    ]
    (work / "RESUME.md").write_text("\n".join(lines), encoding="utf-8")
