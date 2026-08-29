"""Bright Data adapter and web MCP tools, offline via recorded fixtures."""

from __future__ import annotations

import json
import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from src.main.agentradar.adapters.brightdata import BdataClient, BdataError
from src.main.agentradar.contracts.collector import CollectorSpec
from src.main.agentradar.mcp import web_server
from src.main.agentradar.mcp._server import dispatch

ROOT = Path(__file__).resolve().parents[2]
SEARCH_FIXTURE = ROOT / "fixtures" / "bdata_search.json"
SCRAPE_FIXTURE = ROOT / "fixtures" / "bdata_scrape.json"


@dataclass
class FakeProc:
    """Stand-in for subprocess.CompletedProcess."""

    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


@dataclass
class ScriptedRunner:
    """Returns canned CLI output. No process, no network."""

    script: list[FakeProc | BaseException]
    calls: list[list[str]] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)
    _i: int = 0

    def run(self, args: Sequence[str], *, timeout_s: float) -> FakeProc:
        self.calls.append(list(args))
        self.timeouts.append(timeout_s)
        if self._i >= len(self.script):
            raise AssertionError(f"unexpected extra bdata call: {args}")
        step = self.script[self._i]
        self._i += 1
        if isinstance(step, BaseException):
            raise step
        return step


class FakeWebClient:
    """In-memory WebClient. MCP tests inject this."""

    def __init__(
        self,
        *,
        hits: list[dict[str, Any]] | None = None,
        text: str = "",
        rows: list[dict[str, Any]] | None = None,
        healed: bool = True,
        error: BdataError | None = None,
    ) -> None:
        self.hits = hits or []
        self.text = text
        self.rows = rows or []
        self.healed = healed
        self.error = error
        self.search_calls: list[tuple[str, int]] = []
        self.scrape_calls: list[str] = []

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        self.search_calls.append((query, limit))
        return self.hits[:limit]

    def scrape(self, url: str) -> str:
        if self.error is not None:
            raise self.error
        self.scrape_calls.append(url)
        return self.text

    def run_collector(self, spec: CollectorSpec) -> list[dict[str, Any]]:
        if self.error is not None:
            raise self.error
        return list(self.rows)

    def heal_collector(self, spec_id: str, symptom: str, url: str) -> bool:
        if self.error is not None:
            raise self.error
        return self.healed


def _search_stdout() -> str:
    return SEARCH_FIXTURE.read_text(encoding="utf-8")


def _scrape_markdown() -> str:
    payload = json.loads(SCRAPE_FIXTURE.read_text(encoding="utf-8"))
    return str(payload["markdown"])


def _spec() -> CollectorSpec:
    return CollectorSpec(
        id="c_mcp_releases",
        url="https://github.com/modelcontextprotocol/python-sdk/releases",
        description="Extract releases: tag, date, body",
        required_fields=["tag", "date", "body"],
    )


@pytest.fixture(autouse=True)
def _inject_fake() -> Iterator[None]:
    hits = json.loads(_search_stdout())["organic"]
    mapped = [
        {
            "title": row["title"],
            "url": row["link"],
            "snippet": row["description"],
        }
        for row in hits
    ]
    web_server.set_client(FakeWebClient(hits=mapped, text=_scrape_markdown()))
    yield
    web_server.set_client(FakeWebClient())


def test_search_parses_recorded_organic_hits() -> None:
    runner = ScriptedRunner([FakeProc(stdout=_search_stdout())])
    hits = BdataClient(runner=runner).search("mcp python sdk v2 migration", limit=10)
    assert len(hits) == 3
    assert hits[0]["url"].endswith("docs/migration.md")
    assert "FastMCP" in hits[0]["snippet"]
    assert runner.calls[0][:3] == ["bdata", "search", "mcp python sdk v2 migration"]
    assert "--json" in runner.calls[0]


def test_search_respects_limit() -> None:
    runner = ScriptedRunner([FakeProc(stdout=_search_stdout())])
    hits = BdataClient(runner=runner).search("mcp", limit=1)
    assert len(hits) == 1


def test_scrape_returns_recorded_markdown() -> None:
    markdown = _scrape_markdown()
    runner = ScriptedRunner([FakeProc(stdout=markdown)])
    url = (
        "https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md"
    )
    text = BdataClient(runner=runner).scrape(url)
    assert "FastMCP" in text
    assert "MCPServer" in text
    assert runner.calls[0] == ["bdata", "scrape", url]


def test_scrape_json_envelope_extracts_markdown() -> None:
    runner = ScriptedRunner(
        [FakeProc(stdout=SCRAPE_FIXTURE.read_text(encoding="utf-8"))]
    )
    text = BdataClient(runner=runner).scrape("https://example.com/migration")
    assert text.startswith("# Migration")


def test_nonzero_exit_raises_not_empty_list() -> None:
    runner = ScriptedRunner(
        [FakeProc(returncode=1, stdout="", stderr="zone not found")]
    )
    with pytest.raises(BdataError, match="exited 1") as exc_info:
        BdataClient(runner=runner).search("anything")
    assert exc_info.value.exit_code == 1
    assert "zone not found" in exc_info.value.stderr


def test_timeout_raises_typed_error() -> None:
    runner = ScriptedRunner(
        [subprocess.TimeoutExpired(cmd=["bdata", "search"], timeout=120)]
    )
    with pytest.raises(BdataError, match="timed out"):
        BdataClient(runner=runner).search("anything")


def test_missing_binary_raises_typed_error() -> None:
    runner = ScriptedRunner([FileNotFoundError("bdata")])
    with pytest.raises(BdataError, match="not found"):
        BdataClient(runner=runner).scrape("https://example.com")


def test_malformed_search_json_raises() -> None:
    runner = ScriptedRunner([FakeProc(stdout="not-json")])
    with pytest.raises(BdataError, match="not JSON"):
        BdataClient(runner=runner).search("anything")


def test_run_collector_parses_pretty_rows() -> None:
    rows = [
        {"tag": "v2.1.1", "date": "2026-01-15", "body": "rename FastMCP"},
        {"tag": "v2.1.0", "date": "2026-01-08", "body": "beta"},
    ]
    runner = ScriptedRunner([FakeProc(stdout=json.dumps(rows, indent=2))])
    got = BdataClient(runner=runner).run_collector(_spec())
    assert got == rows
    assert runner.calls[0][1:4] == ["scraper", "run", "c_mcp_releases"]
    assert "--pretty" in runner.calls[0]


def test_heal_collector_true_on_done() -> None:
    runner = ScriptedRunner(
        [
            FakeProc(
                stdout=json.dumps({"status": "done", "collector_id": "c_mcp_releases"})
            )
        ]
    )
    ok = BdataClient(runner=runner).heal_collector(
        "c_mcp_releases",
        "3 of 5 rows missing 'tag'",
        "https://github.com/modelcontextprotocol/python-sdk/releases",
    )
    assert ok is True
    call = runner.calls[0]
    assert call[1:4] == ["scraper", "heal", "c_mcp_releases"]
    assert "--auto-approve" in call
    assert "--url" in call


def test_heal_collector_false_on_failed() -> None:
    runner = ScriptedRunner([FakeProc(stdout=json.dumps({"status": "failed"}))])
    ok = BdataClient(runner=runner).heal_collector(
        "c_x", "broken", "https://example.com"
    )
    assert ok is False


def test_dispatch_web_search_returns_search_results() -> None:
    result = dispatch(
        "web_search", {"query": "mcp python sdk v2 migration", "limit": 2}
    )
    assert "error" not in result
    assert result["query"] == "mcp python sdk v2 migration"
    assert len(result["hits"]) == 2
    assert result["hits"][0]["url"].endswith("docs/migration.md")


def test_dispatch_scrape_page_returns_page_content() -> None:
    url = (
        "https://github.com/modelcontextprotocol/python-sdk/blob/main/docs/migration.md"
    )
    result = dispatch("scrape_page", {"url": url})
    assert "error" not in result
    assert result["url"] == url
    assert "FastMCP" in result["text"]


def test_dispatch_rejects_missing_query() -> None:
    result = dispatch("web_search", {})
    assert result["error"]["type"] == "invalid_input"
    assert "query" in result["error"]["message"]


def test_dispatch_bdata_error_is_typed_envelope() -> None:
    web_server.set_client(FakeWebClient(error=BdataError("zone missing", exit_code=1)))
    result = dispatch("web_search", {"query": "x"})
    assert result["error"]["type"] == "bdata"
    assert "zone missing" in result["error"]["message"]
