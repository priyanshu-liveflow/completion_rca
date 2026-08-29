"""Collector health evaluation. Pure: rows plus a spec become a verdict.

`HealthVerdict.symptom` is fed verbatim to `bdata scraper heal`, so heal
quality is a direct function of what this module writes. Keep it specific.
"""

from __future__ import annotations

from typing import Any

from src.main.agentradar.contracts.collector import CollectorSpec, HealthVerdict


def is_missing(value: Any) -> bool:
    """True when a scraped cell carries no content.

    `0`, `0.0` and `False` are content — a release page legitimately reports
    zero downloads, and a falsy check would call that a broken selector.
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    if isinstance(value, (list, dict, tuple, set)):
        return len(value) == 0
    return False


def missing_counts(rows: list[dict[str, Any]], spec: CollectorSpec) -> dict[str, int]:
    """Rows lacking each required field, keyed in `required_fields` order."""
    return {
        field: sum(1 for row in rows if is_missing(row.get(field)))
        for field in spec.required_fields
    }


def evaluate(rows: list[dict[str, Any]], spec: CollectorSpec) -> HealthVerdict:
    """Rows + spec to verdict. No I/O.

    Unhealthy on either count: too few rows, or one required field absent from
    more than `max_missing_field_ratio` of the rows that did come back.
    """
    rows_returned = len(rows)
    counts = missing_counts(rows, spec)

    # The worst single field, not the average across the grid. A scraper that
    # loses one selector loses that field in *every* row; dividing by the field
    # count buries exactly the signal we need. Three required fields and a
    # totally dead column averages to 0.33 -- under a 0.2 threshold it would
    # take four required fields to notice a column that returns nothing at all.
    ratios = [
        (count / rows_returned if rows_returned else 0.0) for count in counts.values()
    ]
    missing_field_ratio = max(ratios, default=0.0)

    too_few_rows = rows_returned < spec.min_rows
    field_breach = missing_field_ratio > spec.max_missing_field_ratio
    healthy = not (too_few_rows or field_breach)

    return HealthVerdict(
        healthy=healthy,
        rows_returned=rows_returned,
        missing_field_ratio=missing_field_ratio,
        missing_fields=[f for f in spec.required_fields if counts[f]],
        symptom=None if healthy else describe(counts, rows_returned, spec),
    )


def describe(counts: dict[str, int], rows_returned: int, spec: CollectorSpec) -> str:
    """Render the heal prompt: what is missing, how much, and what was expected.

    `"3 of 5 rows missing 'tag'; 1 row returned, expected >= 5"`, never
    `"scraper broken"`. Unhealthy always yields at least one clause -- a
    verdict is only unhealthy because of a row shortfall or a field that is
    missing somewhere, and each of those writes its own clause below.
    """
    noun = "row" if rows_returned == 1 else "rows"
    clauses = [
        f"{count} of {rows_returned} {noun} missing {field!r}"
        for field, count in counts.items()
        if count
    ]
    if rows_returned < spec.min_rows:
        clauses.append(f"{rows_returned} {noun} returned, expected >= {spec.min_rows}")
    return "; ".join(clauses)
