"""Code-graph adapter. Protocol plus one FalkorDB implementation.

Delegates to `code_tools.queries`. Does not write Cypher.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.main.agentradar.contracts.impact import ContactPoint
from src.main.code_tools import queries


@runtime_checkable
class CodeGraph(Protocol):
    """Call-graph access used by locate, blast, and test selection."""

    def find_contact_points(
        self, symbol: str, repo: str, limit: int = 15
    ) -> list[ContactPoint]: ...

    def callers_of(
        self, fid: int, repo: str, limit: int = 25
    ) -> list[dict[str, Any]]: ...

    def call_chain(
        self, frm: str, to: str, repo: str, max_hops: int = 4
    ) -> list[dict[str, Any]]: ...

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str: ...


def _path_from_read(blob: str) -> str:
    """Parse the `File:` header that `queries.read_source` prefixes onto source."""
    for line in blob.splitlines():
        if line.startswith("File: "):
            return line.split("|", 1)[0].removeprefix("File: ").strip()
    return ""


class FalkorCodeGraph:
    """FalkorDB-backed graph. Talks to the unix socket via `code_tools.queries`."""

    def find_contact_points(
        self, symbol: str, repo: str, limit: int = 15
    ) -> list[ContactPoint]:
        """Map `find_by_pattern` hits (name or source text) into contact points."""
        rows = queries.find_by_pattern(symbol, repo, limit)
        points: list[ContactPoint] = []
        for row in rows:
            raw_fid = row.get("fid")
            if raw_fid is None:
                continue
            fid = int(raw_fid)
            name = str(row["name"])
            blob = queries.read_source(name, repo, max_chars=1, fid=fid)
            points.append(
                ContactPoint(
                    symbol=symbol,
                    function_name=name,
                    fid=fid,
                    file_path=_path_from_read(blob),
                    line=None,
                )
            )
        return points

    def callers_of(self, fid: int, repo: str, limit: int = 25) -> list[dict[str, Any]]:
        """Functions that call `fid`. BFS callers live in core/selection (PR4)."""
        return list(queries.get_callers("", repo, limit=limit, fid=fid))

    def call_chain(
        self, frm: str, to: str, repo: str, max_hops: int = 4
    ) -> list[dict[str, Any]]:
        """Shortest CALLS path from `frm` to `to`, or an empty list."""
        chain = queries.get_call_chain(frm, to, repo, max_hops=max_hops)
        return list(chain) if chain else []

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str:
        """Function source for patch context. `fid` is unambiguous."""
        return str(queries.read_source("", repo, max_chars=max_chars, fid=fid))
