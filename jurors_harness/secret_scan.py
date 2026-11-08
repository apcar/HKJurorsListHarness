"""Scan a tree or git history for credentials and machine-specific paths.

The patterns are assembled so this file does not contain the strings it searches for.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

SKIP_DIRS = {".git", ".venv", "venv", "__pycache__", "runs", "data", "scans", "ledgers", "uploads", ".pytest_cache"}
SKIP_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".pdf", ".pyc", ".tgz", ".gz", ".zip"}
PLACEHOLDERS = {"", "your-key-here", "changeme", "TODO", "not-a-real-key"}


@dataclass
class Finding:
    path: str
    line: int
    pattern: str


def _patterns() -> list[tuple[str, re.Pattern[str]]]:
    users = "/" + "Users" + "/"
    workspace = "/" + "workspace" + "/"
    home = "/" + "home" + "/"
    win = "C:" + "\\" + "Users" + "\\"
    sk_or = "sk-" + "or-"
    sk_ant = "sk-" + "ant-"
    aiza = "AIza" + r"[0-9A-Za-z_\-]{10,}"
    akia = "AKIA" + r"[0-9A-Z]{16}"
    private = "-----BEGIN " + r"(?:RSA |OPENSSH |EC |PRIVATE)"
    bearer = r"Authorization:\s*Bearer\s+[A-Za-z0-9._\-]{8,}"
    goog = "x-goog-api-key:" + r"\s*[A-Za-z0-9_\-]{8,}"
    openrouter = "OPENROUTER_API_KEY" + r"\s*=\s*(\S+)"
    gemini = "GEMINI_API_KEY" + r"\s*=\s*(\S+)"
    compiled = [
        ("personal-path", re.compile(re.escape(users))),
        ("personal-path", re.compile(re.escape(workspace))),
        ("personal-path", re.compile(re.escape(home) + r"[^\s/]+/")),
        ("personal-path", re.compile(re.escape(win))),
        ("credential", re.compile(re.escape(sk_or))),
        ("credential", re.compile(re.escape(sk_ant))),
        ("credential", re.compile(aiza)),
        ("credential", re.compile(akia)),
        ("credential", re.compile(private)),
        ("credential", re.compile(bearer)),
        ("credential", re.compile(goog)),
        ("env-assignment", re.compile(openrouter)),
        ("env-assignment", re.compile(gemini)),
    ]
    return compiled


def scan_tree(root: Path) -> list[Finding]:
    findings: list[Finding] = []
    root = root.resolve()
    for path in sorted(root.rglob("*")):
        if any(part in SKIP_DIRS for part in path.relative_to(root).parts):
            continue
        if not path.is_file() or path.suffix.lower() in SKIP_SUFFIXES:
            continue
        if path.name == ".env":
            findings.append(Finding(str(path.relative_to(root)), 1, "env-file"))
            continue
        if path.stat().st_size > 2_000_000:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        findings.extend(_scan_text(str(path.relative_to(root)), text))
    return findings


def _history_needles() -> list[str]:
    """Fixed strings that this repository's own scanner source does not contain."""
    return [
        "/" + "Users" + "/",
        "/" + "workspace" + "/",
        "sk-" + "or-",
        "sk-" + "ant-",
        "-----BEGIN " + "PRIVATE KEY-----",
    ]


def scan_history(root: Path) -> list[Finding]:
    """Scan committed blobs. A missing git history is reported, not treated as clean."""
    try:
        commits = subprocess.run(
            ["git", "rev-list", "--all"],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        return [Finding("git", 0, "git-not-available")]
    if commits.returncode != 0:
        return [Finding("git", 0, "git-history-unavailable")]
    revisions = [line.strip() for line in commits.stdout.splitlines() if line.strip()]
    if not revisions:
        return []
    findings: list[Finding] = []
    for needle in _history_needles():
        result = subprocess.run(
            ["git", "grep", "-I", "-n", "-F", needle, *revisions],
            cwd=root,
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode not in {0, 1}:
            findings.append(Finding("git", 0, "git-grep-failed"))
            continue
        for line in result.stdout.splitlines():
            findings.append(Finding(line[:240], 0, "history"))
    return findings


def _scan_text(path: str, text: str) -> list[Finding]:
    findings = []
    for lineno, line in enumerate(text.splitlines(), 1):
        for name, pattern in _patterns():
            match = pattern.search(line)
            if not match:
                continue
            if name == "env-assignment":
                value = match.group(1).strip().strip("'\"")
                if value in PLACEHOLDERS:
                    continue
            findings.append(Finding(path, lineno, name))
    return findings
