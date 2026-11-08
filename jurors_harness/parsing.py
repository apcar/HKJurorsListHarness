"""Local recovery of complete adjudication fields. This never spends a new call."""

from __future__ import annotations

import json
import re

from jurors_harness.constants import ADJUDICATION_OUTCOMES
from jurors_harness.hashing import sha256_text


def parse_reading(obj: dict, fields: list[str], entry_id: str) -> dict | None:
    if not isinstance(obj, dict):
        return None
    if obj.get("entry_id") != entry_id:
        return None
    parsed = {"entry_id": entry_id}
    for name in fields:
        value = obj.get(name)
        if not isinstance(value, str):
            return None
        parsed[name] = value
    parsed["ownership_uncertain"] = bool(obj.get("ownership_uncertain"))
    parsed["scan_loss"] = bool(obj.get("scan_loss"))
    parsed["notes"] = obj.get("notes") or ""
    return parsed


def parse_adjudication(obj: dict, fields: list[str], entry_id: str) -> dict | None:
    if not isinstance(obj, dict) or obj.get("entry_id") != entry_id:
        return None
    parsed: dict = {
        "entry_id": entry_id,
        "ownership_uncertain": bool(obj.get("ownership_uncertain")),
        "notes": obj.get("notes") or "",
    }
    for name in fields:
        field_obj = obj.get(name)
        if not isinstance(field_obj, dict) or not isinstance(field_obj.get("exact"), str):
            return None
        if field_obj.get("outcome") not in ADJUDICATION_OUTCOMES:
            return None
        parsed[name] = {
            "exact": field_obj["exact"],
            "outcome": field_obj["outcome"],
            "uncertainty": field_obj.get("uncertainty") or "",
            "explanation": field_obj.get("explanation") or "",
            "chosen_candidate": field_obj.get("chosen_candidate") or "",
        }
    return parsed


def recover_adjudication(raw: str | None, entry_id: str, fields: list[str]) -> tuple[dict | None, dict]:
    """Keep a field only when every recovered object for it is identical.

    Conflicting objects are reported and left unresolved. The raw response is unchanged.
    """
    detail = {
        "entry_id": entry_id,
        "raw_text_sha256": sha256_text(raw or ""),
        "fields": {},
        "recovered": [],
        "policy": "completed unique field objects only; conflicting answers stay unresolved",
    }
    if not raw or entry_id not in raw:
        return None, detail
    decoder = json.JSONDecoder()
    recovered: dict = {
        "entry_id": entry_id,
        "ownership_uncertain": False,
        "notes": "Completed fields recovered locally; missing or conflicting fields stay unresolved.",
        "_parser_recovered": True,
    }
    ownership = re.search(r'"ownership_uncertain"\s*:\s*(true|false)', raw)
    if ownership:
        recovered["ownership_uncertain"] = ownership.group(1) == "true"
        detail["ownership_explicit"] = True
    else:
        detail["ownership_explicit"] = False
    any_field = False
    for name in fields:
        options = []
        for match in re.finditer(r'"' + re.escape(name) + r'"\s*:\s*', raw):
            try:
                obj, _end = decoder.raw_decode(raw[match.end() :])
            except json.JSONDecodeError:
                continue
            if (
                isinstance(obj, dict)
                and isinstance(obj.get("exact"), str)
                and obj.get("outcome") in ADJUDICATION_OUTCOMES
            ):
                options.append(
                    {
                        "exact": obj["exact"],
                        "outcome": obj["outcome"],
                        "uncertainty": obj.get("uncertainty") or "",
                        "explanation": obj.get("explanation") or "",
                        "chosen_candidate": obj.get("chosen_candidate") or "",
                    }
                )
        unique = {json.dumps(item, sort_keys=True, ensure_ascii=False) for item in options}
        detail["fields"][name] = {"alternatives": len(unique)}
        if len(unique) == 1:
            recovered[name] = options[0]
            detail["recovered"].append(name)
            any_field = True
        elif len(unique) > 1:
            detail["fields"][name]["conflict"] = True
    if not any_field:
        return None, detail
    return recovered, detail
