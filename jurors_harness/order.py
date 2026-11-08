"""Seeded counterbalancing of anonymous candidates.

Within each candidate-count group, display position is a rotation of a stable
canonical order. Position counts differ by at most one. This is not a shuffle.
"""

from __future__ import annotations

import json


def counterbalance(cases: list[dict], seed: int) -> tuple[list[dict], dict]:
    """Return cases with `display` labels and an audit document.

    Each case needs `entry_id` and `candidates`, a list of
    `{role, text, evidence_ids}`. `text` is a field dict. Identical texts are
    already deduplicated by the caller; provenance stays on `evidence_ids`.
    """
    grouped: dict[int, list[dict]] = {}
    for case in cases:
        grouped.setdefault(len(case["candidates"]), []).append(case)
    audit_groups = []
    displayed: dict[str, dict] = {}
    for count, members in sorted(grouped.items()):
        members = sorted(members, key=lambda item: item["entry_id"])
        position_counts: dict[str, dict[str, int]] = {}
        for index, case in enumerate(members):
            canonical = sorted(
                case["candidates"],
                key=lambda item: (item.get("role") or "", json.dumps(item["text"], sort_keys=True, ensure_ascii=False)),
            )
            if count == 0:
                labels: list[dict] = []
            else:
                rotation = (index + (seed % count)) % count
                rotated = canonical[rotation:] + canonical[:rotation]
                labels = []
                for offset, candidate in enumerate(rotated):
                    label = chr(ord("A") + offset)
                    labels.append(
                        {
                            "label": label,
                            "text": candidate["text"],
                            "role": candidate.get("role", ""),
                            "evidence_ids": list(candidate.get("evidence_ids") or []),
                        }
                    )
                    position_counts.setdefault(candidate.get("role") or "unknown", {})
                    position_counts[candidate.get("role") or "unknown"][label] = (
                        position_counts[candidate.get("role") or "unknown"].get(label, 0) + 1
                    )
            shown = [{"label": item["label"], "text": item["text"]} for item in labels]
            provenance = [
                {"label": item["label"], "role": item["role"], "evidence_ids": item["evidence_ids"]}
                for item in labels
            ]
            displayed[case["entry_id"]] = {"shown": shown, "provenance": provenance}
        spreads = []
        for role, counts in position_counts.items():
            if counts:
                spreads.append(max(counts.values()) - min(counts.values()))
        audit_groups.append(
            {
                "candidate_count": count,
                "n": len(members),
                "position_counts": position_counts,
                "max_minus_min": max(spreads) if spreads else 0,
            }
        )
    ordered = []
    for case in sorted(cases, key=lambda item: item["entry_id"]):
        extra = displayed[case["entry_id"]]
        ordered.append({**case, "shown": extra["shown"], "provenance": extra["provenance"]})
    audit = {
        "method": "rotation-within-candidate-count-groups",
        "seed": seed,
        "note": "Position is a rotation of canonical role order. It is not a random shuffle.",
        "groups": audit_groups,
        "balanced": all(group["max_minus_min"] <= 1 for group in audit_groups),
    }
    return ordered, audit
