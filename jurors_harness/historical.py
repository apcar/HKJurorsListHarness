"""Narrow retained-reading adapter. Historical evidence is NOT a dispatcher cache.

Missing original metadata remains null. No invented prompt, timestamp, or price.
The caller retains source files and supplies their hashes. No network is used.
"""
from copy import deepcopy
from jurors_harness.hashing import sha256_text
import json


def import_reading(retained: dict, source_call: dict, *, source_sha256: str) -> dict:
    if not retained.get("id") or not retained.get("line_id"):
        raise ValueError("historical reading needs stable evidence and entry IDs")
    if not isinstance(retained.get("text"), dict):
        raise ValueError("historical reading text must be a field object")
    exposure = "blind" if retained.get("blind") is True and retained.get("informed") is False else "informed" if retained.get("informed") is True else "unknown"
    return {
        "schema": "HISTORICAL-READING-v1", "origin": "imported_historical",
        "evidence_id": retained["id"], "entry_id": retained["line_id"],
        "retained_variant_sha256": sha256_text(json.dumps(retained, sort_keys=True, ensure_ascii=False)),
        "model": retained.get("model"), "original_model": source_call.get("model") or source_call.get("model_requested"),
        "timestamp": source_call.get("ts"), "prompt_version": source_call.get("prompt_version"),
        "original_prompt_sha256": source_call.get("prompt_sha256"),
        "settings": deepcopy(source_call.get("settings")), "exposure": exposure,
        "crop_sha256": retained.get("crop_sha256"),
        "original_recorded_crop_sha256": source_call.get("crop_sha256"),
        "sent_image_sha256": source_call.get("sent_image_sha256"),
        "protocol": retained.get("protocol"), "text": deepcopy(retained["text"]),
        "illegible": deepcopy(retained.get("illegible")), "notes": retained.get("notes"),
        "source": retained.get("source"), "source_line": retained.get("source_line"),
        "source_file_sha256": source_sha256,
        "source_record_sha256": sha256_text(json.dumps(source_call, sort_keys=True, ensure_ascii=False)),
        "historical_cost_usd": source_call.get("cost_usd"),
        "incremental_cost_usd": 0, "new_harness_call": False,
    }


def blind_candidate(record: dict, crop_sha256: str) -> dict:
    """Require a retained matching crop; never promote an informed reading to blind."""
    if "parser-alternative" in (record.get("protocol") or ""):
        raise ValueError("conflicting parser alternatives are not a selected blind reading")
    if record["exposure"] != "blind":
        raise ValueError("informed/unknown evidence is not a blind candidate")
    if record.get("crop_sha256") != crop_sha256:
        raise ValueError("changed crop requires an explicit new evidence decision")
    original = record.get("original_recorded_crop_sha256")
    if original and original != crop_sha256:
        raise ValueError("original crop differs from retained crop")
    text = record["text"]
    if not all(isinstance(text.get(f), str) for f in ("name", "occupation", "abode")):
        raise ValueError("incomplete historical reading")
    return {"entry_id": record["entry_id"], **text,
        "scan_loss": any((record.get("illegible") or {}).values()),
        "notes": record.get("notes") or ""}
