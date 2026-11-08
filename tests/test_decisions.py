"""Literal comparison, dispositions, counterbalancing, and scoring."""

from __future__ import annotations

import inspect

from jurors_harness.compare import levenshtein, practical_class, strict_equal
from jurors_harness.decisions import decide_entry, field_needs_queue
from jurors_harness.evaluate import _dedupe_candidates
from jurors_harness.learning import alias_key, carryover_flags, lexicon_flags
from jurors_harness.order import counterbalance
from jurors_harness.prompts import informed_prior_block, render_adjudication, render_blind
from jurors_harness.scoring import defect_interval

FIELDS = ["name", "occupation", "abode"]


def entry(**kwargs):
    base = {
        "entry_id": "e1",
        "included": True,
        "held": False,
        "ownership_problem": False,
        "scan_loss": False,
        "baseline_name": "Ada",
        "baseline_occupation": "clerk",
        "baseline_abode": "1 Queen Road",
        "crop_sha256": "abc",
    }
    base.update(kwargs)
    return base


def reading(**kwargs):
    base = {"entry_id": "e1", "name": "Ada", "occupation": "clerk", "abode": "1 Queen Road", "ownership_uncertain": False, "scan_loss": False}
    base.update(kwargs)
    return base


def test_punctuation_and_accents_count():
    assert strict_equal("é", "e\u0301")
    assert not strict_equal("Mr.", "Mr")
    assert not strict_equal("José", "Jose")
    assert practical_class("José", "Jose") == "literal-only"
    assert practical_class("José", "Jose*") == "meaningful"
    assert practical_class("Ld.", "Ltd.") == "meaningful"
    assert levenshtein("kitten", "sitting") == 3


def test_blind_agreement_corrects_baseline_and_keeps_typos():
    decision = decide_entry(
        entry(baseline_abode="Queens Rd."),
        fields=FIELDS,
        left=reading(abode="Queen's Rd.", name="*José", occupation="Ld."),
        right=reading(abode="Queen's Rd.", name="*José", occupation="Ld."),
        adjudication=None,
        queued_fields=[],
    )
    assert decision.disposition == "CORRECTED"
    assert decision.method == "blind_agreement"
    assert {item.field: item.release_text for item in decision.fields}["occupation"] == "Ld."
    assert {item.field: item.release_text for item in decision.fields}["name"] == "*José"


def test_illegible_agreement_is_not_settled():
    blind = reading(name="[illegible]", occupation="[illegible]", abode="[illegible]")
    assert field_needs_queue(entry(), blind, blind, "name", FIELDS) is True
    held = entry(held=True, baseline_name="", baseline_occupation="", baseline_abode="")
    assert field_needs_queue(held, blind, blind, "name", FIELDS)
    decision = decide_entry(held, fields=FIELDS, left=blind, right=blind, adjudication=None, queued_fields=FIELDS)
    assert decision.disposition == "UNCERTAIN"


def test_normalization_confession_stays_uncertain():
    adjudication = {
        "entry_id": "e1",
        "ownership_uncertain": False,
        "name": {
            "exact": "Color",
            "outcome": "corrected",
            "uncertainty": "",
            "explanation": "the real word is Colour but I normalized to Color",
        },
        "occupation": {"exact": "clerk", "outcome": "confirmed", "uncertainty": "", "explanation": "clear"},
        "abode": {"exact": "1 Queen Road", "outcome": "confirmed", "uncertainty": "", "explanation": "clear"},
    }
    decision = decide_entry(
        entry(baseline_name="Colour"),
        fields=FIELDS,
        left=reading(name="Colour"),
        right=reading(name="Color"),
        adjudication=adjudication,
        queued_fields=["name"],
    )
    by_field = {item.field: item for item in decision.fields}
    assert by_field["name"].release_text == "[UNRESOLVED]"
    assert by_field["name"].reason == "normalization-conflict"
    assert by_field["occupation"].release_text == "clerk"
    assert by_field["occupation"].method == "blind_agreement"
    assert decision.disposition == "UNCERTAIN"


def test_non_queued_field_is_not_overwritten():
    adjudication = {
        "name": {"exact": "Mr. Chan", "outcome": "confirmed", "uncertainty": "", "explanation": "dot printed"},
        "occupation": {"exact": "Clerk", "outcome": "confirmed", "uncertainty": "", "explanation": "case"},
        "abode": {"exact": "1 Queen Road", "outcome": "confirmed", "uncertainty": "", "explanation": "same"},
    }
    decision = decide_entry(
        entry(baseline_name="Mr. Chan"),
        fields=FIELDS,
        left=reading(name="Mr. Chan"),
        right=reading(name="Mr Chan"),
        adjudication=adjudication,
        queued_fields=["name"],
    )
    by_field = {item.field: item for item in decision.fields}
    assert by_field["occupation"].release_text == "clerk"
    assert decision.disposition == "SETTLED"


def test_excluded_row():
    decision = decide_entry(entry(included=False, exclusion_reason="supplement"), fields=FIELDS, left=None, right=None, adjudication=None, queued_fields=[])
    assert decision.disposition == "EXCLUDED"
    assert decision.operational_state == "not_applicable"


def test_resolved_hold_is_settled():
    adjudication = {
        "ownership_uncertain": False,
        "name": {"exact": "Ada", "outcome": "confirmed", "uncertainty": "", "explanation": "now readable"},
        "occupation": {"exact": "clerk", "outcome": "confirmed", "uncertainty": "", "explanation": "clear"},
        "abode": {"exact": "1 Queen Road", "outcome": "confirmed", "uncertainty": "", "explanation": "clear"},
    }
    decision = decide_entry(
        entry(held=True, baseline_name="", baseline_occupation="", baseline_abode=""),
        fields=FIELDS,
        left=None,
        right=None,
        adjudication=adjudication,
        queued_fields=FIELDS,
    )
    assert decision.disposition == "SETTLED"
    assert decision.fields[0].release_text == "Ada"


def test_counterbalance_differs_by_at_most_one():
    cases = []
    for index in range(5):
        cases.append(
            {
                "entry_id": f"e{index:02d}",
                "candidates": [
                    {"role": "reader_a", "text": {"name": "Left"}, "evidence_ids": ["reader_a"]},
                    {"role": "reader_b", "text": {"name": "Right"}, "evidence_ids": ["reader_b"]},
                ],
            }
        )
    _ordered, audit = counterbalance(cases, seed=11)
    assert audit["balanced"]
    counts = audit["groups"][0]["position_counts"]["reader_a"]
    assert max(counts.values()) - min(counts.values()) <= 1


def test_identical_readings_keep_both_evidence_ids():
    pair = {
        "reader_a": {"name": "Ada", "occupation": "clerk", "abode": "1 Queen Road"},
        "reader_b": {"name": "Ada", "occupation": "clerk", "abode": "1 Queen Road"},
    }
    candidates = _dedupe_candidates(pair, FIELDS)
    assert len(candidates) == 1
    assert set(candidates[0]["evidence_ids"]) == {"reader_a", "reader_b"}


def test_interval_is_exact_when_the_sample_is_the_population():
    assert defect_interval(5, 5, 2, 0) == [0.4, 0.4]
    widened = defect_interval(5, 5, 0, 2)
    assert widened is not None
    assert widened[0] == 0
    assert widened[1] > widened[0]


def test_alias_is_not_diplomatic_equality():
    assert alias_key("José") == alias_key("jose")
    assert not strict_equal("José", "jose")
    flags = carryover_flags("Smyth", [{"field": "name", "year": 1938, "exact_form": "PRIORONLY-SMYTH", "normalized_alias": "smyth"}], field="name")
    assert flags and flags[0]["prior_exact_form"] == "PRIORONLY-SMYTH"
    assert lexicon_flags("printed XQZTYPO here", [{"exact_form": "XQZTYPO", "normalized_alias": "xqztypo"}])


def test_blind_renderer_cannot_accept_a_reference():
    signature = inspect.signature(render_blind)
    assert set(signature.parameters) == {"template", "entry_id", "year"}
    template = open_template("blind-v1.txt")
    rendered = render_blind(template, entry_id="e1", year=1939)
    lowered = rendered.lower()
    for token in ("gwulo", "claude", "gemini", "anthropic", "sonnet", "xqztypo", "prioronly", "refonly"):
        assert token not in lowered
    adjudication = open_template("adjudication-v1.txt")
    rendered_adj = render_adjudication(
        adjudication,
        entry_id="e1",
        year=1939,
        fields=FIELDS,
        candidates=[{"label": "A", "text": {"name": "Ada", "occupation": "clerk", "abode": "1 Queen Road"}, "role": "reader_a"}],
    )
    assert "reader_a" not in rendered_adj
    assert "PRIORONLY" not in rendered_adj
    with_prior = render_adjudication(
        adjudication,
        entry_id="e1",
        year=1939,
        fields=FIELDS,
        candidates=[{"label": "A", "text": {"name": "Ada", "occupation": "clerk", "abode": "1 Queen Road"}}],
        prior_block=informed_prior_block([{"field": "name", "prior_exact_form": "PRIORONLY-SMYTH", "prior_year": "1938"}]),
    )
    assert "INFORMED PRIOR" in with_prior
    assert "PRIORONLY-SMYTH" in with_prior


def open_template(name: str) -> str:
    from pathlib import Path

    return (Path(__file__).resolve().parents[1] / "prompts" / name).read_text(encoding="utf-8")
