"""Dispositions: SETTLED, CORRECTED, UNCERTAIN, or EXCLUDED.

Blind agreement can settle a line. It does not prove the line correct.
A held, illegible, ownership-problem, or scan-loss line stays unresolved
even when two readers emit the same placeholder. One adjudication may
resolve queued fields. An explanation that proposes normalization keeps
the field uncertain. Unread lines keep baseline text and are not settled.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from jurors_harness.compare import has_illegible_marker, strict_equal
from jurors_harness.constants import (
    REASON_ILLEGIBLE,
    REASON_MISSING_EVIDENCE,
    REASON_MISSING_SCAN,
    REASON_MODEL_SPLIT,
    REASON_NORMALIZATION,
    REASON_OWNERSHIP,
    REASON_PARSER,
    REASON_TRANSPORT,
    REASON_UNREAD_BUDGET,
)
_NORMALIZATION = re.compile(
    r"the real word|the correct spelling|read it that way|normali[sz]ed to|"
    r"corrected the (?:printer'?s?|typo)|standard spelling (?:is|rather)|"
    r"should actually be|moderni[sz]ed",
    re.IGNORECASE,
)


@dataclass
class FieldDecision:
    field: str
    baseline: str
    release_text: str
    uncertain: bool
    reason: str
    method: str
    note: str


@dataclass
class EntryDecision:
    entry_id: str
    included: bool
    disposition: str
    operational_state: str
    method: str
    evidence_level: str
    fields: list[FieldDecision] = field(default_factory=list)

    @property
    def uncertain_fields(self) -> list[str]:
        return [item.field for item in self.fields if item.uncertain]

    @property
    def uncertainty_reasons(self) -> list[str]:
        reasons = []
        for item in self.fields:
            if item.uncertain and item.reason and item.reason not in reasons:
                reasons.append(item.reason)
        return reasons


def reading_usable(parsed: dict | None, fields: list[str], entry_id: str) -> bool:
    if not isinstance(parsed, dict):
        return False
    if parsed.get("entry_id") not in (None, "", entry_id) and parsed.get("crop_id") not in (None, "", entry_id):
        if parsed.get("entry_id") != entry_id and parsed.get("crop_id") != entry_id:
            return False
    if parsed.get("ownership_uncertain") is True or parsed.get("scan_loss") is True:
        return False
    for name in fields:
        value = parsed.get(name)
        if not isinstance(value, str):
            return False
        if has_illegible_marker(value):
            return False
    return True


def field_needs_queue(
    entry: dict,
    left: dict | None,
    right: dict | None,
    field: str,
    fields: list[str],
) -> bool:
    """A field joins the single adjudication queue when blind agreement cannot settle it."""
    if not entry.get("included", True):
        return False
    if entry.get("held") or entry.get("ownership_problem") or entry.get("scan_loss"):
        return True
    if not reading_usable(left, fields, entry["entry_id"]) or not reading_usable(right, fields, entry["entry_id"]):
        return True
    assert left is not None and right is not None
    return not strict_equal(left.get(field, ""), right.get(field, ""))


def normalization_conflict(explanation: str) -> bool:
    return bool(_NORMALIZATION.search(explanation or ""))


def _reason_from_adjudication(obj: dict, *, ownership: bool) -> str:
    if ownership or obj.get("ownership_uncertain") is True:
        return REASON_OWNERSHIP
    uncertainty = (obj.get("uncertainty") or "").lower()
    outcome = obj.get("outcome") or ""
    exact = obj.get("exact") or ""
    if outcome == "better_source_needed" or "scan" in uncertainty or "clip" in uncertainty:
        return REASON_MISSING_SCAN
    if has_illegible_marker(exact) or "illegib" in uncertainty:
        return REASON_ILLEGIBLE
    if outcome in {"neither", "unresolved"}:
        return REASON_MODEL_SPLIT
    return REASON_MODEL_SPLIT


def apply_adjudicated_field(obj: dict | None, *, ownership: bool) -> tuple[str, bool, str, str]:
    """Return release text, uncertain, reason, note. Does not spend a new call."""
    if not isinstance(obj, dict) or not isinstance(obj.get("exact"), str):
        return "[UNRESOLVED]", True, REASON_PARSER, "no complete field object"
    explanation = obj.get("explanation") or ""
    if normalization_conflict(explanation):
        return "[UNRESOLVED]", True, REASON_NORMALIZATION, "explanation proposes normalization"
    exact = obj["exact"]
    outcome = obj.get("outcome") or ""
    uncertainty = (obj.get("uncertainty") or "").strip()
    if ownership or outcome in {"unresolved", "better_source_needed", "neither"} or uncertainty:
        reason = _reason_from_adjudication(obj, ownership=ownership)
        if has_illegible_marker(exact):
            return exact, True, reason, outcome or "unresolved"
        return "[UNRESOLVED]", True, reason, outcome or "unresolved"
    if outcome in {"confirmed", "corrected"}:
        if has_illegible_marker(exact):
            return exact, True, REASON_ILLEGIBLE, outcome
        return exact, False, "", outcome
    return "[UNRESOLVED]", True, REASON_MODEL_SPLIT, f"unrecognized outcome {outcome}"


def decide_entry(
    entry: dict,
    *,
    fields: list[str],
    left: dict | None,
    right: dict | None,
    adjudication: dict | None,
    queued_fields: list[str],
    operational_hint: str = "reviewed",
) -> EntryDecision:
    """Decide one inventory row.

    `entry` uses baseline_name / baseline_occupation / baseline_abode, or the
    field names directly under `baseline`.
    `adjudication` is a parsed object, possibly locally recovered, or None.
    """
    entry_id = entry["entry_id"]
    baseline = _baseline(entry, fields)
    if not entry.get("included", True):
        decided = [
            FieldDecision(field, baseline[field], "", False, "", "excluded", entry.get("exclusion_reason", ""))
            for field in fields
        ]
        return EntryDecision(
            entry_id=entry_id,
            included=False,
            disposition="EXCLUDED",
            operational_state="not_applicable",
            method="excluded",
            evidence_level="excluded",
            fields=decided,
        )

    ownership = bool(adjudication and adjudication.get("ownership_uncertain") is True)
    field_decisions: list[FieldDecision] = []
    for name in fields:
        base = baseline[name]
        needs = name in queued_fields or field_needs_queue(entry, left, right, name, fields)
        if (
            not needs
            and left
            and right
            and reading_usable(left, fields, entry_id)
            and reading_usable(right, fields, entry_id)
            and strict_equal(left.get(name, ""), right.get(name, ""))
        ):
            field_decisions.append(
                FieldDecision(
                    name,
                    base,
                    str(left.get(name, "")),
                    False,
                    "",
                    "blind_agreement",
                    "two literal-equal usable readings",
                )
            )
            continue
        if needs and adjudication is not None:
            text, uncertain, reason, note = apply_adjudicated_field(
                adjudication.get(name) if isinstance(adjudication.get(name), dict) else None,
                ownership=ownership,
            )
            method = "adjudicated" if not adjudication.get("_parser_recovered") else "parser_recovered"
            field_decisions.append(FieldDecision(name, base, text, uncertain, reason, method, note))
            continue
        if needs and not left and not right and not entry.get("crop_sha256"):
            field_decisions.append(
                FieldDecision(name, base, base, True, REASON_MISSING_EVIDENCE, "not_reviewed", "crop missing")
            )
            continue
        if needs and operational_hint in {"pending_budget", "billing_stopped"}:
            field_decisions.append(
                FieldDecision(name, base, base, True, REASON_UNREAD_BUDGET, "not_reviewed", operational_hint)
            )
            continue
        if needs and operational_hint == "transport_exhausted":
            field_decisions.append(
                FieldDecision(name, base, base, True, REASON_TRANSPORT, "not_reviewed", operational_hint)
            )
            continue
        if needs:
            field_decisions.append(
                FieldDecision(name, base, base, True, REASON_UNREAD_BUDGET, "not_reviewed", "no completed adjudication")
            )
            continue
        # One side missing on a field that somehow was not queued: still unresolved.
        field_decisions.append(
            FieldDecision(name, base, base, True, REASON_MISSING_EVIDENCE, "not_reviewed", "coverage incomplete")
        )

    uncertain = any(item.uncertain for item in field_decisions)
    changed = any(not item.uncertain and not strict_equal(item.release_text, item.baseline) for item in field_decisions)
    if uncertain:
        disposition = "UNCERTAIN"
    elif entry.get("held"):
        # A resolved original hold is settled. The overlay still records the new text.
        disposition = "SETTLED"
    elif changed:
        disposition = "CORRECTED"
    else:
        disposition = "SETTLED"

    methods = {item.method for item in field_decisions}
    if methods == {"blind_agreement"}:
        method = "blind_agreement"
        level = "blind_agreement"
    elif methods <= {"adjudicated", "blind_agreement"} and "adjudicated" in methods:
        method = "adjudicated" if methods == {"adjudicated"} else "mixed"
        level = "adjudicated"
    elif "parser_recovered" in methods:
        method = "parser_recovered"
        level = "parser_recovered"
    elif methods <= {"not_reviewed"}:
        method = "not_reviewed"
        level = "not_reviewed"
    else:
        method = "mixed"
        level = "mixed"

    if disposition == "UNCERTAIN" and operational_hint in {"pending_budget", "billing_stopped", "missing_evidence", "transport_exhausted"}:
        state = operational_hint
    elif disposition == "UNCERTAIN" and method == "not_reviewed":
        state = "pending_budget"
    elif any(item.method == "not_reviewed" for item in field_decisions) and any(
        item.method != "not_reviewed" for item in field_decisions
    ):
        state = "partial"
    else:
        state = "reviewed"

    return EntryDecision(
        entry_id=entry_id,
        included=True,
        disposition=disposition,
        operational_state=state,
        method=method,
        evidence_level=level,
        fields=field_decisions,
    )


def _baseline(entry: dict, fields: list[str]) -> dict[str, str]:
    block = entry.get("baseline")
    if isinstance(block, dict):
        return {name: str(block.get(name, "")) for name in fields}
    return {name: str(entry.get(f"baseline_{name}", entry.get(name, ""))) for name in fields}

