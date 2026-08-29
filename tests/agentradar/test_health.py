"""Collector health evaluation and the validate-then-heal MCP flow.

The symptom string is the product here: it is handed verbatim to
`bdata scraper heal`, so these tests assert its text, not just a boolean.
No live calls -- rows come from recorded fixtures.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.main.agentradar.adapters.brightdata import BdataError, WebClient
from src.main.agentradar.contracts.collector import CollectorSpec
from src.main.agentradar.core.health import evaluate, is_missing
from src.main.agentradar.mcp import web_server
from src.main.agentradar.mcp._server import (
    ToolError,
    dispatch,
    is_error_envelope,
    list_tools,
)

ROOT = Path(__file__).resolve().parents[2]
RELEASES_URL = "https://github.com/modelcontextprotocol/python-sdk/releases"

DEGRADED_SYMPTOM = (
    "2 of 3 rows missing 'tag'; "
    "3 of 3 rows missing 'date'; "
    "3 of 3 rows missing 'body'; "
    "3 rows returned, expected >= 5"
)


def _rows(name: str) -> list[dict[str, Any]]:
    payload = json.loads((ROOT / "fixtures" / name).read_text(encoding="utf-8"))
    return [dict(row) for row in payload["data"]]


def _spec(**overrides: Any) -> CollectorSpec:
    base: dict[str, Any] = {
        "id": "c_test",
        "url": "https://example.invalid/releases",
        "description": "Extract releases: tag, date, body",
        "required_fields": ["tag", "date", "body"],
        "min_rows": 5,
        "max_missing_field_ratio": 0.2,
    }
    base.update(overrides)
    return CollectorSpec(**base)


def _row(**overrides: Any) -> dict[str, Any]:
    row: dict[str, Any] = {"tag": "v1.0.0", "date": "2026-01-01", "body": "notes"}
    row.update(overrides)
    return row


@dataclass
class ScriptedWebClient:
    """WebClient double. Each `run_collector` pops the next scripted result."""

    runs: list[list[dict[str, Any]] | BdataError]
    heal_result: bool | BdataError = True
    run_calls: list[str] = field(default_factory=list)
    heal_calls: list[tuple[str, str, str]] = field(default_factory=list)

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        raise AssertionError("run_collector must not reach SERP")

    def scrape(self, url: str) -> str:
        raise AssertionError("run_collector must not reach Web Unlocker")

    def run_collector(self, spec: CollectorSpec) -> list[dict[str, Any]]:
        self.run_calls.append(spec.id)
        if not self.runs:
            raise AssertionError(f"unscripted extra collector run: {spec.id}")
        step = self.runs.pop(0)
        if isinstance(step, BdataError):
            raise step
        return step

    def heal_collector(self, spec_id: str, symptom: str, url: str) -> bool:
        self.heal_calls.append((spec_id, symptom, url))
        if isinstance(self.heal_result, BdataError):
            raise self.heal_result
        return self.heal_result


@pytest.fixture
def restore_client() -> Iterator[None]:
    """Put the module-level client back so test ordering cannot leak a double."""
    yield
    web_server.set_client(ScriptedWebClient(runs=[]))


def _inject(client: ScriptedWebClient) -> ScriptedWebClient:
    typed: WebClient = client
    web_server.set_client(typed)
    return client


# --- core/health.py -------------------------------------------------------


def test_symptom_names_the_field_and_the_count() -> None:
    rows = [_row(), _row(), _row(tag=""), _row(tag=""), _row(tag="")]
    verdict = evaluate(rows, _spec())
    assert verdict.healthy is False
    assert verdict.symptom == "3 of 5 rows missing 'tag'"


def test_symptom_names_the_row_shortfall() -> None:
    verdict = evaluate([_row()], _spec())
    assert verdict.symptom == "1 row returned, expected >= 5"


def test_symptom_joins_every_clause_it_has() -> None:
    verdict = evaluate(_rows("collector_mcp_releases_degraded.json"), _spec())
    assert verdict.symptom == DEGRADED_SYMPTOM
    assert verdict.missing_fields == ["tag", "date", "body"]


def test_healthy_run_has_no_symptom() -> None:
    verdict = evaluate([_row() for _ in range(5)], _spec())
    assert verdict.healthy is True
    assert verdict.symptom is None
    assert verdict.missing_fields == []
    assert verdict.missing_field_ratio == 0.0


def test_empty_result_reads_as_a_row_shortfall() -> None:
    verdict = evaluate([], _spec())
    assert verdict.healthy is False
    assert verdict.rows_returned == 0
    assert verdict.missing_field_ratio == 0.0
    assert verdict.symptom == "0 rows returned, expected >= 5"


@pytest.mark.parametrize("blank", [None, "", "   ", "\n\t", [], {}])
def test_blank_cells_count_as_missing(blank: Any) -> None:
    assert is_missing(blank) is True


@pytest.mark.parametrize("value", [0, 0.0, False, "0", ["x"], {"a": 1}])
def test_content_is_not_absence(value: Any) -> None:
    """A release with zero downloads is data, not a dead selector."""
    assert is_missing(value) is False


def test_absent_key_counts_as_missing() -> None:
    rows = [{"tag": "v1", "date": "d"} for _ in range(5)]
    verdict = evaluate(rows, _spec())
    assert verdict.missing_fields == ["body"]
    assert verdict.missing_field_ratio == 1.0
    assert verdict.symptom == "5 of 5 rows missing 'body'"


def test_ratio_is_the_worst_field_not_the_grid_average() -> None:
    """One dead column must not be diluted by the fields that still work."""
    rows = [_row(body="") for _ in range(5)]
    spec = _spec(max_missing_field_ratio=0.4)
    verdict = evaluate(rows, spec)
    # Averaged over the 3x5 grid this is 0.33 and would pass the 0.4 threshold
    # while 'body' returns nothing at all.
    assert verdict.missing_field_ratio == 1.0
    assert verdict.healthy is False


def test_threshold_is_exclusive() -> None:
    at_limit = [_row(), _row(), _row(), _row(), _row(tag="")]
    assert evaluate(at_limit, _spec()).healthy is True
    over_limit = [_row(), _row(), _row(), _row(tag=""), _row(tag="")]
    assert evaluate(over_limit, _spec()).healthy is False


def test_missing_fields_follow_spec_order() -> None:
    rows = [{"body": "notes"} for _ in range(5)]
    spec = _spec(required_fields=["date", "tag", "body"])
    assert evaluate(rows, spec).missing_fields == ["date", "tag"]


def test_unrequired_fields_are_ignored() -> None:
    rows = [_row(breaking_change_flag=None) for _ in range(5)]
    assert evaluate(rows, _spec()).healthy is True


def test_evaluate_does_not_mutate_its_input() -> None:
    rows = [_row()]
    before = json.dumps(rows, sort_keys=True)
    evaluate(rows, _spec())
    assert json.dumps(rows, sort_keys=True) == before


# --- mcp/web_server.py run_collector --------------------------------------


def test_manifest_loads_with_thresholds_nested_under_health() -> None:
    spec = web_server.load_spec("mcp-releases")
    assert spec.id == "c_mcp_releases"
    assert spec.url == RELEASES_URL
    assert spec.required_fields == ["tag", "date", "body"]
    assert spec.min_rows == 5
    assert spec.max_missing_field_ratio == 0.2


def test_every_committed_manifest_is_a_valid_spec() -> None:
    paths = sorted(web_server.COLLECTOR_DIR.glob("*.json"))
    assert paths, "no collector manifests committed"
    ids = [web_server.load_spec(path.stem).id for path in paths]
    assert all(cid.startswith("c_") for cid in ids)
    assert len(set(ids)) == len(ids)


def test_manifest_resolves_by_collector_id() -> None:
    assert web_server.load_spec("c_mcp_changelog").url.endswith("/migration/")


@pytest.mark.parametrize(
    "name", ["../pyproject", "collectors/mcp-releases", "/etc/passwd", "", ".."]
)
def test_collector_name_cannot_leave_the_directory(name: str) -> None:
    with pytest.raises(ToolError) as excinfo:
        web_server.load_spec(name)
    assert excinfo.value.type == "invalid_input"


def test_unknown_collector_is_a_typed_error() -> None:
    with pytest.raises(ToolError) as excinfo:
        web_server.load_spec("nope")
    assert excinfo.value.type == "unknown_collector"


def test_healthy_collector_is_never_healed(restore_client: None) -> None:
    client = _inject(ScriptedWebClient(runs=[_rows("collector_mcp_releases.json")]))
    run = web_server.run_collector("mcp-releases")
    assert run.health.healthy is True
    assert run.healed is False
    assert run.health_after_heal is None
    assert client.heal_calls == []
    assert client.run_calls == ["c_mcp_releases"]


def test_degradation_heals_and_the_rerun_restores_coverage(
    restore_client: None,
) -> None:
    """The demo beat: degraded -> heal -> re-run, before and after in one run."""
    client = _inject(
        ScriptedWebClient(
            runs=[
                _rows("collector_mcp_releases_degraded.json"),
                _rows("collector_mcp_releases.json"),
            ]
        )
    )
    run = web_server.run_collector("mcp-releases")

    assert run.health.healthy is False
    assert run.health.rows_returned == 3
    assert run.healed is True
    assert run.health_after_heal is not None
    assert run.health_after_heal.healthy is True
    assert run.health_after_heal.rows_returned == 6
    assert [row["tag"] for row in run.rows][:2] == ["v2.1.1", "v2.0.0"]
    assert client.run_calls == ["c_mcp_releases", "c_mcp_releases"]


def test_heal_is_given_the_symptom_verbatim(restore_client: None) -> None:
    client = _inject(
        ScriptedWebClient(
            runs=[
                _rows("collector_mcp_releases_degraded.json"),
                _rows("collector_mcp_releases.json"),
            ]
        )
    )
    run = web_server.run_collector("mcp-releases")
    assert run.health.symptom == DEGRADED_SYMPTOM
    assert client.heal_calls == [("c_mcp_releases", DEGRADED_SYMPTOM, RELEASES_URL)]


def test_collector_id_survives_healing(restore_client: None) -> None:
    """`c_*` ids are the durable artifact. Heal repairs one; it never mints one."""
    client = _inject(
        ScriptedWebClient(
            runs=[
                _rows("collector_mcp_releases_degraded.json"),
                _rows("collector_mcp_releases.json"),
            ]
        )
    )
    run = web_server.run_collector("mcp-releases")
    assert run.spec_id == "c_mcp_releases"
    assert {call[0] for call in client.heal_calls} == {"c_mcp_releases"}
    assert set(client.run_calls) == {"c_mcp_releases"}


def test_refused_heal_reports_degradation_without_a_second_run(
    restore_client: None,
) -> None:
    client = _inject(
        ScriptedWebClient(
            runs=[_rows("collector_mcp_releases_degraded.json")], heal_result=False
        )
    )
    run = web_server.run_collector("mcp-releases")
    assert run.healed is False
    assert run.health_after_heal is None
    assert run.health.symptom == DEGRADED_SYMPTOM
    assert len(client.run_calls) == 1


def test_still_degraded_after_heal_is_reported_honestly(
    restore_client: None,
) -> None:
    degraded = _rows("collector_mcp_releases_degraded.json")
    _inject(ScriptedWebClient(runs=[degraded, list(degraded)]))
    run = web_server.run_collector("mcp-releases")
    assert run.healed is True
    assert run.health_after_heal is not None
    assert run.health_after_heal.healthy is False
    assert run.health_after_heal.symptom == DEGRADED_SYMPTOM


def test_cli_failure_is_a_typed_error_not_an_empty_run(restore_client: None) -> None:
    _inject(ScriptedWebClient(runs=[BdataError("bdata exited 3", exit_code=3)]))
    payload = dispatch("run_collector", {"collector": "mcp-releases"})
    assert is_error_envelope(payload)
    assert payload["error"]["type"] == "bdata"


def test_failed_heal_error_carries_the_symptom(restore_client: None) -> None:
    _inject(
        ScriptedWebClient(
            runs=[_rows("collector_mcp_releases_degraded.json")],
            heal_result=BdataError("bdata timed out after 600s"),
        )
    )
    payload = dispatch("run_collector", {"collector": "mcp-releases"})
    assert is_error_envelope(payload)
    assert DEGRADED_SYMPTOM in payload["error"]["message"]


def test_dispatch_returns_the_collector_run_contract(restore_client: None) -> None:
    _inject(
        ScriptedWebClient(
            runs=[
                _rows("collector_mcp_releases_degraded.json"),
                _rows("collector_mcp_releases.json"),
            ]
        )
    )
    payload = dispatch("run_collector", {"collector": "mcp-releases"})
    assert not is_error_envelope(payload)
    assert payload["spec_id"] == "c_mcp_releases"
    assert payload["healed"] is True
    assert payload["health"]["healthy"] is False
    assert payload["health"]["symptom"] == DEGRADED_SYMPTOM
    assert payload["health_after_heal"]["healthy"] is True


def test_run_collector_is_registered_with_a_schema() -> None:
    spec = next(t for t in list_tools() if t.name == "run_collector")
    assert spec.schema["required"] == ["collector"]
    assert spec.schema["properties"]["collector"]["type"] == "string"
