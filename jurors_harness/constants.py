"""Shared policy constants.

Historical 1940 RC1 figures are acceptance checks for an externally supplied
edition. They are not produced by the synthetic fixtures in this repository.
"""

FIELDS = ("name", "occupation", "abode")

DISPOSITIONS = ("SETTLED", "CORRECTED", "UNCERTAIN", "EXCLUDED")

OPERATIONAL_STATES = (
    "reviewed",
    "pending_budget",
    "billing_stopped",
    "missing_evidence",
    "transport_exhausted",
    "partial",
    "not_applicable",
)

# Design section 3.5 / measurement: uncertainty is a disposition, with a reason.
REASON_UNREAD_BUDGET = "unread-for-budget"
REASON_MODEL_SPLIT = "model-split"
REASON_MISSING_SCAN = "missing-scan-text"
REASON_ILLEGIBLE = "source-illegibility"
REASON_NORMALIZATION = "normalization-conflict"
REASON_OWNERSHIP = "ownership"
REASON_PARSER = "parser-incomplete"
REASON_MISSING_EVIDENCE = "missing-evidence"
REASON_TRANSPORT = "transport-exhausted"

STRATA = (
    "held_or_source_loss",
    "reader_disagreement",
    "agreement_with_risk",
    "other_agreement",
)

INCOMPLETE_COVERAGE = "incomplete_coverage"

ADJUDICATION_OUTCOMES = (
    "confirmed",
    "corrected",
    "unresolved",
    "better_source_needed",
    "neither",
)

# Frozen 1940 RC1 acceptance constants (design section 11, gate 6).
RC1_ROWS = 3505
RC1_CSV_SHA256 = "4641e360bc0fcde8950d9fd737cd11ef363a553356d059d264c611fee7b9dc11"
RC1_BASELINE_SHA256 = "a574726f1d42946bc9e3a503b8a3a5e077692860f4eabf826d7fb5aa268d156f"
RC1_DISPOSITIONS = {"settled": 3058, "corrected": 84, "uncertain": 363}

LEDGER_SCHEMA = "LEDGER-v1"
LEDGER_EXT = "LEDGER-ext-v1"
CONFIG_SCHEMA = "jurors-harness-config-v1"
UNCERTAIN_SCHEMA = "UNCERTAIN-LINES-v1"

FORBIDDEN_PROMPT_TOKENS = (
    "gwulo",
    "anthropic",
    "claude",
    "gemini",
    "openrouter",
    "sonnet",
    "haiku",
    "openai",
    "qwen",
)

BILLING_MARKERS = (
    "billing",
    "insufficient credit",
    "insufficient credits",
    "available credits",
    "payment required",
    "insufficient funds",
)
