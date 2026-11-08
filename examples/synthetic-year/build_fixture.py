#!/usr/bin/env python3
"""Write the synthetic year fixture. Output is fake on purpose. No scan and no person."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parent

IDS = {
    "e01": "1939-synthetic-fixture-p0002-e0001",
    "e02": "1939-synthetic-fixture-p0002-e0002",
    "e03": "1939-synthetic-fixture-p0002-e0003",
    "e04": "1939-synthetic-fixture-p0001-e0004",
    "e05": "1939-synthetic-fixture-p0003-e0005",
    "e06": "1939-synthetic-fixture-p0004-e0006",
    "e07": "1939-synthetic-fixture-p0003-e0007",
}


def png(rgb: tuple[int, int, int]) -> bytes:
    width = height = 8

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = b"".join(b"\x00" + bytes(rgb) * width for _ in range(height))
    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(raw))
        + chunk(b"IEND", b"")
    )


def reading(name: str, occupation: str, abode: str, **flags) -> dict:
    return {
        "tokens_in": 80,
        "tokens_out": 40,
        "cost_usd": 0.0002,
        "reading": {
            "name": name,
            "occupation": occupation,
            "abode": abode,
            "ownership_uncertain": flags.get("ownership_uncertain", False),
            "scan_loss": flags.get("scan_loss", False),
            "notes": "",
        },
    }


def field(exact: str, outcome: str, explanation: str, uncertainty: str = "", chosen: str = "") -> dict:
    return {
        "exact": exact,
        "outcome": outcome,
        "uncertainty": uncertainty,
        "explanation": explanation,
        "chosen_candidate": chosen,
    }


def main() -> None:
    crops = ROOT / "crops"
    crops.mkdir(exist_ok=True)
    colors = {
        "e01": (20, 40, 60),
        "e02": (60, 20, 40),
        "e03": (20, 60, 40),
        "e04": (80, 40, 20),
        "e05": (30, 30, 30),
        "e07": (40, 50, 70),
    }
    for key, rgb in colors.items():
        (crops / f"{key}.png").write_bytes(png(rgb))

    header = (
        "entry_id,year,witness,edition,physical_page,printed_page_label,juror_class,slot,"
        "included,exclusion_reason,crop_file,baseline_name,baseline_occupation,baseline_abode,"
        "held,ownership_problem,scan_loss,edge_contact,normalization_hazard,hard_reason"
    )
    rows = [
        (IDS["e01"], 2, "2", "Common", 1, "true", "", "crops/e01.png", "Alfa Example", "clerk", "1 Queen Road", "false", "false", "false", "false", "false", ""),
        (IDS["e02"], 2, "2", "Common", 2, "true", "", "crops/e02.png", "*José Bravo", "Ld.", "Queens Rd.", "false", "false", "false", "true", "true", ""),
        (IDS["e03"], 2, "2", "Common", 3, "true", "", "crops/e03.png", "Mr. Chan", "clerk", "2 Queen Road", "false", "false", "false", "false", "false", ""),
        (IDS["e04"], 1, "1", "Special", 4, "true", "", "crops/e04.png", "Smith", "tailor", "3 Queen Road", "false", "false", "false", "false", "false", ""),
        (IDS["e05"], 3, "3", "Common", 5, "true", "", "crops/e05.png", "", "", "", "true", "false", "true", "false", "false", "faint print"),
        (IDS["e06"], 4, "4", "supplement", 6, "false", "supplement not in this edition", "", "", "", "", "false", "false", "false", "false", "false", ""),
        (IDS["e07"], 3, "3", "Common", 7, "true", "", "crops/e07.png", "Colour", "clerk", "4 Queen Road", "false", "false", "false", "false", "false", ""),
    ]
    lines = [header]
    for entry_id, page, label, klass, slot, included, reason, crop, name, occupation, abode, held, ownership, scan, edge, hazard, hard in rows:
        lines.append(
            ",".join(
                [
                    entry_id,
                    "1939",
                    "synthetic",
                    "fixture",
                    str(page),
                    label,
                    klass,
                    str(slot),
                    included,
                    reason,
                    crop,
                    name,
                    occupation,
                    abode,
                    held,
                    ownership,
                    scan,
                    edge,
                    hazard,
                    hard,
                ]
            )
        )
    (ROOT / "inventory.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (ROOT / "census.json").write_text(
        json.dumps(
            {
                "source_census_established": False,
                "measures": {"detector_count": None, "reference_count": None, "source_derived_count": 7},
                "duplicate_witnesses": [],
                "supplements": ["synthetic supplement row, excluded"],
                "notes": "SYNTHETIC fixture. Not the 1939 jurors list and not a source census.",
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    (ROOT / "reference.csv").write_text(
        "entry_id,name,occupation,abode\n"
        f"{IDS['e01']},Alfa Example,REFONLY-OCCUPATION,1 Queen Road\n",
        encoding="utf-8",
    )
    (ROOT / "priors.csv").write_text(
        "year,witness,field,exact_form,normalized_alias\n"
        "1938,other-year,name,PRIORONLY-SMYTH,smyth\n",
        encoding="utf-8",
    )
    (ROOT / "lexicon.jsonl").write_text(
        json.dumps(
            {
                "lexicon_version": "lexicon-v1",
                "exact_form": "XQZTYPO",
                "normalized_alias": "xqztypo",
                "field": "name",
                "evidence_source": "synthetic",
                "year": 1938,
            },
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    book = {
        "probe": {"text": "{\"ok\": true}", "tokens_in": 8, "tokens_out": 4, "cost_usd": 0.00001},
        "reader_a": {
            IDS["e01"]: reading("Alfa Example", "clerk", "1 Queen Road"),
            IDS["e02"]: reading("*José Bravo", "Ld.", "Queen's Rd."),
            IDS["e03"]: reading("Mr. Chan", "clerk", "2 Queen Road"),
            IDS["e04"]: reading("Smith", "tailor", "3 Queen Road"),
            IDS["e05"]: reading("[illegible]", "[illegible]", "[illegible]", scan_loss=True),
            IDS["e07"]: reading("Colour", "clerk", "4 Queen Road"),
        },
        "reader_b": {
            IDS["e01"]: reading("Alfa Example", "clerk", "1 Queen Road"),
            IDS["e02"]: reading("*José Bravo", "Ld.", "Queen's Rd."),
            IDS["e03"]: reading("Mr Chan", "clerk", "2 Queen Road"),
            IDS["e04"]: reading("Smyth", "tailor", "3 Queen Road"),
            IDS["e05"]: reading("[illegible]", "[illegible]", "[illegible]", scan_loss=True),
            IDS["e07"]: reading("Color", "clerk", "4 Queen Road"),
        },
        "adjudication": {
            IDS["e03"]: {
                "tokens_in": 120,
                "tokens_out": 80,
                "cost_usd": 0.0004,
                "ownership_uncertain": False,
                "notes": "",
                "fields": {
                    "name": field("Mr. Chan", "confirmed", "The abbreviation dot is printed.", chosen="A"),
                    "occupation": field("Clerk", "confirmed", "Case differs from one candidate; ignored by the harness when the field was not queued."),
                    "abode": field("2 Queen Road", "confirmed", "Both candidates agree."),
                },
            },
            IDS["e04"]: {
                "tokens_in": 120,
                "tokens_out": 80,
                "cost_usd": 0.0004,
                "fields": {
                    "name": field("Smyth", "corrected", "The print reads Smyth.", chosen="new"),
                    "occupation": field("tailor", "confirmed", "The occupation is tailor."),
                    "abode": field("3 Queen Road", "confirmed", "The abode matches the print."),
                },
            },
            IDS["e05"]: {
                "tokens_in": 120,
                "tokens_out": 80,
                "cost_usd": 0.0004,
                "fields": {
                    "name": field("[illegible]", "unresolved", "The glyphs are not readable.", "source illegible"),
                    "occupation": field("[illegible]", "unresolved", "The glyphs are not readable.", "source illegible"),
                    "abode": field("[illegible]", "better_source_needed", "The line is too faint.", "clipped scan"),
                },
            },
            IDS["e07"]: {
                "tokens_in": 120,
                "tokens_out": 80,
                "cost_usd": 0.0004,
                "fields": {
                    "name": field("Color", "corrected", "the real word is Colour but I normalized to Color", chosen="B"),
                    "occupation": field("clerk", "confirmed", "The occupation is clerk."),
                    "abode": field("4 Queen Road", "confirmed", "The abode is clear."),
                },
            },
        },
    }
    (ROOT / "scripted_responses.json").write_text(json.dumps(book, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("fixture written", ROOT)


if __name__ == "__main__":
    main()
