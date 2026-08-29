"""Bright Data collector specs, health verdicts, and heal-aware runs."""

from typing import Any

from pydantic import BaseModel, ConfigDict


class CollectorSpec(BaseModel):
    """Version-controlled scraper definition. Collector IDs survive healing."""

    model_config = ConfigDict(frozen=True)

    id: str
    url: str
    description: str
    required_fields: list[str]
    min_rows: int = 5
    max_missing_field_ratio: float = 0.2


class HealthVerdict(BaseModel):
    """Coverage check against a spec. `symptom` is fed verbatim to heal."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    rows_returned: int
    missing_field_ratio: float
    missing_fields: list[str]
    symptom: str | None


class CollectorRun(BaseModel):
    """One collector invocation, including a heal-and-rerun if it degraded."""

    model_config = ConfigDict(frozen=True)

    spec_id: str
    rows: list[dict[str, Any]]
    health: HealthVerdict
    healed: bool = False
    health_after_heal: HealthVerdict | None = None
