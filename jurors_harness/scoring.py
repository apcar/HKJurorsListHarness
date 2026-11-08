"""Finite-population intervals and same-sample scoring.

Intervals invert the hypergeometric distribution with an equal 2.5% tail on
each side. Unresolved labels widen the upper bound only. They do not correct
model-label error, and they are not a pooled accuracy rate.
"""

from __future__ import annotations

import math
from functools import lru_cache

from jurors_harness.compare import levenshtein, practical_class, strict_equal


@lru_cache(maxsize=100_000)
def _comb(n: int, k: int) -> int:
    if k < 0 or n < 0 or k > n:
        return 0
    return math.comb(n, k)


def _pmf_numerators(N: int, K: int, n: int) -> list[int]:
    """Unnormalized P(X=x) numerators for x in 0..n. Denominator is C(N, n)."""
    lo = max(0, n - (N - K))
    hi = min(n, K)
    nums = [0] * (n + 1)
    for x in range(lo, hi + 1):
        nums[x] = _comb(K, x) * _comb(N - K, n - x)
    return nums


def _tail_ge(N: int, K: int, n: int, errors: int) -> bool:
    """True when P(X >= errors) >= 0.025, compared in integers (0.025 = 1/40)."""
    if errors <= 0:
        return True
    denom = _comb(N, n)
    if denom == 0:
        return False
    numer = sum(_pmf_numerators(N, K, n)[errors:])
    return 40 * numer >= denom


def _cdf_le(N: int, K: int, n: int, limit: int) -> bool:
    """True when P(X <= limit) >= 0.025."""
    denom = _comb(N, n)
    if denom == 0:
        return False
    numer = sum(_pmf_numerators(N, K, n)[: limit + 1])
    return 40 * numer >= denom


def defect_interval(N: int, n: int, errors: int, unresolved: int) -> list[float] | None:
    """Return [lower, upper] population defect fractions, or None if undefined."""
    if N <= 0 or n <= 0 or n > N:
        return None
    if errors < 0 or unresolved < 0 or errors + unresolved > n:
        raise ValueError("sample error counts exceed the sample")
    if errors == 0:
        lower_k = 0
    else:
        lower_k = 0
        for K in range(N + 1):
            if _tail_ge(N, K, n, errors):
                lower_k = K
                break
        else:
            lower_k = N
    upper_limit = errors + unresolved
    upper_k = 0
    for K in range(N, -1, -1):
        if _cdf_le(N, K, n, upper_limit):
            upper_k = K
            break
    return [lower_k / N, upper_k / N]


def score_entry(
    *,
    values: dict[str, str],
    labels: dict[str, str | None],
    fields: tuple[str, ...] | list[str],
) -> dict:
    """Score one edition of one entry against model labels. Missing labels stay unresolved."""
    correct = error = unresolved = 0
    characters = 0
    mark_diffs = 0
    classes: list[str] = []
    field_rows: list[dict] = []
    for field in fields:
        reference = labels.get(field)
        text = values.get(field, "")
        if reference is None:
            status = "unresolved"
            practical = "unresolved"
            distance: int | None = None
            marks: int | None = None
            unresolved += 1
        else:
            status = "correct" if strict_equal(text, reference) else "error"
            practical = practical_class(text, reference) if status == "error" else "correct"
            distance = levenshtein(text, reference)
            marks = abs(text.count("*") - reference.count("*")) + abs(text.count("†") - reference.count("†"))
            characters += distance
            mark_diffs += marks
            if status == "correct":
                correct += 1
            else:
                error += 1
        classes.append(practical)
        field_rows.append(
            {
                "field": field,
                "literal_status": status,
                "practical_class": practical,
                "character_discrepancies": distance if distance is not None else "",
                "meaningful_mark_discrepancies": marks if marks is not None else "",
            }
        )
    if error:
        entry_status = "error"
    elif unresolved:
        entry_status = "unresolved"
    else:
        entry_status = "correct"
    if "meaningful" in classes:
        entry_practical = "meaningful"
    elif unresolved:
        entry_practical = "unresolved"
    elif error:
        entry_practical = "literal-only"
    else:
        entry_practical = "correct"
    return {
        "literal_status": entry_status,
        "practical_class": entry_practical,
        "correct_fields": correct,
        "error_fields": error,
        "unresolved_fields": unresolved,
        "character_discrepancies_on_labeled_fields": characters,
        "meaningful_mark_discrepancies": mark_diffs,
        "fields": field_rows,
    }
