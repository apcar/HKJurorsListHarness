#!/usr/bin/env python3
"""Scan the working tree, and optionally git history, before any public push."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Allow `python scripts/secret_scan.py` from a checkout without an editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from jurors_harness.secret_scan import scan_history, scan_tree


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Scan for credentials and machine-specific paths")
    parser.add_argument("--root", type=Path, default=Path("."))
    parser.add_argument("--history", action="store_true", help="also scan reachable Git objects")
    args = parser.parse_args(argv)
    findings = scan_tree(args.root)
    if args.history:
        findings.extend(scan_history(args.root))
    if findings:
        for finding in findings:
            print(f"{finding.path}:{finding.line}: {finding.pattern}")
        return 1
    print("secret-scan: no findings")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
