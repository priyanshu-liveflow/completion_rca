"""Bright Data CLI adapter. The only module allowed to reach the network."""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Sequence
from typing import Any, Protocol

from src.main.agentradar.contracts.collector import CollectorSpec

DEFAULT_TIMEOUT_S = 120.0
COLLECTOR_TIMEOUT_S = 600.0


class BdataError(Exception):
    """Typed failure from a `bdata` invocation. Never swallowed into []."""

    def __init__(
        self, message: str, *, exit_code: int | None = None, stderr: str = ""
    ) -> None:
        super().__init__(message)
        self.exit_code = exit_code
        self.stderr = stderr


class CompletedCli(Protocol):
    """Subset of `subprocess.CompletedProcess` the adapter reads."""

    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    """Injectable process runner. Tests pass a fixture-backed fake."""

    def run(self, args: Sequence[str], *, timeout_s: float) -> CompletedCli: ...


class WebClient(Protocol):
    """Outbound web access: SERP, Web Unlocker, Scraper Studio."""

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]: ...

    def scrape(self, url: str) -> str: ...

    def run_collector(self, spec: CollectorSpec) -> list[dict[str, Any]]: ...

    def heal_collector(self, spec_id: str, symptom: str, url: str) -> bool: ...


class SubprocessRunner:
    """Shell out to a binary. Timeouts and output capture are explicit."""

    def run(self, args: Sequence[str], *, timeout_s: float) -> CompletedCli:
        return subprocess.run(
            list(args),
            capture_output=True,
            text=True,
            timeout=timeout_s,
            check=False,
        )


class BdataClient:
    """WebClient that shells out to the `bdata` CLI. Auth via BRIGHTDATA_API_KEY."""

    def __init__(
        self,
        *,
        runner: CommandRunner | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        collector_timeout_s: float = COLLECTOR_TIMEOUT_S,
        binary: str = "bdata",
    ) -> None:
        self._runner: CommandRunner = (
            runner if runner is not None else SubprocessRunner()
        )
        self._timeout_s = timeout_s
        self._collector_timeout_s = collector_timeout_s
        self._binary = binary
        self._serp_zone = os.getenv("BRIGHTDATA_SERP_ZONE", "")
        self._unlocker_zone = os.getenv("BRIGHTDATA_UNLOCKER_ZONE", "")

    def search(self, query: str, *, limit: int = 10) -> list[dict[str, Any]]:
        """SERP via `bdata search`. Returns organic hits as `{title, url, snippet}`."""
        argv = ["search", query]
        if self._serp_zone:
            argv.extend(["--zone", self._serp_zone])
        argv.append("--json")
        stdout = self._invoke(argv, timeout_s=self._timeout_s)
        hits = [_normalize_hit(row) for row in _organic_rows(stdout)]
        return hits[:limit]

    def scrape(self, url: str) -> str:
        """Web Unlocker via `bdata scrape`. Markdown by default."""
        argv = ["scrape", url]
        if self._unlocker_zone:
            argv.extend(["--zone", self._unlocker_zone])
        stdout = self._invoke(argv, timeout_s=self._timeout_s)
        return _scrape_text(stdout)

    def run_collector(self, spec: CollectorSpec) -> list[dict[str, Any]]:
        """Scraper Studio via `bdata scraper run <id> <url> --pretty`."""
        stdout = self._invoke(
            ["scraper", "run", spec.id, spec.url, "--pretty"],
            timeout_s=self._collector_timeout_s,
        )
        return _collector_rows(stdout)

    def heal_collector(self, spec_id: str, symptom: str, url: str) -> bool:
        """`bdata scraper heal` with `--auto-approve`. True iff status is `done`."""
        stdout = self._invoke(
            [
                "scraper",
                "heal",
                spec_id,
                symptom,
                "--url",
                url,
                "--auto-approve",
                "--json",
            ],
            timeout_s=self._collector_timeout_s,
        )
        return _heal_succeeded(stdout)

    def _invoke(self, argv: list[str], *, timeout_s: float) -> str:
        args = [self._binary, *argv]
        try:
            proc = self._runner.run(args, timeout_s=timeout_s)
        except subprocess.TimeoutExpired as exc:
            raise BdataError(
                f"bdata timed out after {timeout_s:.0f}s: {' '.join(argv[:3])}",
                stderr=str(exc),
            ) from exc
        except FileNotFoundError as exc:
            raise BdataError(
                f"{self._binary!r} not found on PATH",
                stderr=str(exc),
            ) from exc
        if proc.returncode != 0:
            err = (proc.stderr or proc.stdout or "").strip()
            raise BdataError(
                f"bdata exited {proc.returncode}: {err or ' '.join(argv[:3])}",
                exit_code=proc.returncode,
                stderr=proc.stderr,
            )
        return proc.stdout


def _parse_json(stdout: str) -> Any:
    """Parse CLI JSON, or raise BdataError. Does not invent an empty payload."""
    text = stdout.strip()
    if not text:
        raise BdataError("bdata returned empty stdout")
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    start_obj, start_arr = text.find("{"), text.find("[")
    starts = [i for i in (start_obj, start_arr) if i >= 0]
    if not starts:
        raise BdataError("bdata stdout was not JSON")
    try:
        return json.loads(text[min(starts) :])
    except json.JSONDecodeError as exc:
        raise BdataError("bdata stdout was not JSON") from exc


def _organic_rows(stdout: str) -> list[dict[str, Any]]:
    payload = _parse_json(stdout)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("organic", "organic_results", "results"):
            if key not in payload:
                continue
            rows = payload[key]
            if not isinstance(rows, list):
                raise BdataError(f"bdata search {key!r} was not a list")
            return [row for row in rows if isinstance(row, dict)]
    raise BdataError("bdata search returned no organic result list")


def _normalize_hit(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "title": str(row.get("title") or ""),
        "url": str(row.get("link") or row.get("url") or ""),
        "snippet": str(row.get("description") or row.get("snippet") or ""),
    }


def _scrape_text(stdout: str) -> str:
    text = stdout.strip()
    if not text:
        raise BdataError("bdata scrape returned empty stdout")
    if text[:1] not in "{[":
        return stdout if stdout.endswith("\n") else text
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return stdout
    if isinstance(payload, str):
        return payload
    if isinstance(payload, dict):
        for key in ("markdown", "content", "text", "body", "html"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
    return stdout


def _collector_rows(stdout: str) -> list[dict[str, Any]]:
    payload = _parse_json(stdout)
    if isinstance(payload, list):
        return [row for row in payload if isinstance(row, dict)]
    if isinstance(payload, dict):
        for key in ("data", "rows", "results"):
            if key not in payload:
                continue
            rows = payload[key]
            if not isinstance(rows, list):
                raise BdataError(f"bdata scraper run {key!r} was not a list")
            return [row for row in rows if isinstance(row, dict)]
        return [payload]
    raise BdataError("bdata scraper run returned no rows")


def _heal_succeeded(stdout: str) -> bool:
    try:
        payload = _parse_json(stdout)
    except BdataError:
        return True
    if not isinstance(payload, dict):
        return True
    status = str(payload.get("status") or "").lower()
    if status == "done":
        return True
    if status in {"failed", "rejected", "error"}:
        return False
    if status == "awaiting_approval":
        return False
    return True
