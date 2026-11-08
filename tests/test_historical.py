import pytest
from jurors_harness.historical import import_reading, blind_candidate


def retained():
    return dict(id="saved:1", line_id="e1", model="original", blind=True, informed=False,
        crop_sha256="abc", text=dict(name="A.",occupation="Clerk.",abode="On premises."))


def test_import_is_not_new_call_or_spending():
    r = import_reading(retained(), dict(ts="saved-time",prompt_version="old",cost_usd=0.2,crop_sha256="abc"), source_sha256="file-hash")
    assert r["timestamp"] == "saved-time" and r["historical_cost_usd"] == 0.2
    assert r["incremental_cost_usd"] == 0 and not r["new_harness_call"]
    assert blind_candidate(r,"abc")["name"] == "A."


def test_informed_and_changed_crops_cannot_be_blind():
    x = retained(); x.update(blind=False,informed=True)
    r = import_reading(x,{},source_sha256="f")
    with pytest.raises(ValueError): blind_candidate(r,"abc")
    x = retained(); r = import_reading(x,{},source_sha256="f")
    with pytest.raises(ValueError): blind_candidate(r,"changed")
    r["original_recorded_crop_sha256"] = "different"
    with pytest.raises(ValueError): blind_candidate(r,"abc")


def test_missing_metadata_stays_missing():
    r = import_reading(retained(),{},source_sha256="f")
    assert r["timestamp"] is None and r["prompt_version"] is None
    assert r["historical_cost_usd"] is None


def test_original_call_log_field_names_are_preserved():
    r = import_reading(retained(),dict(model_requested="original-route",prompt_sha256="original-prompt-hash"),source_sha256="file")
    assert r["original_model"] == "original-route"
    assert r["original_prompt_sha256"] == "original-prompt-hash"


def test_parser_alternatives_are_not_silently_selected():
    x = retained(); x["protocol"] = "parser-alternative (not silently selected)"
    r = import_reading(x,{},source_sha256="f")
    with pytest.raises(ValueError): blind_candidate(r,"abc")
