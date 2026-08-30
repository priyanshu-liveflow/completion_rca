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

    def import_edges(self, repo: str) -> list[dict[str, Any]]: ...

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, Any]]: ...

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


def _relative_to_repo(path: str, repo: str) -> str:
    """Trim an indexed absolute path down to repo-relative.

    The graph stores absolute paths from index time, but every consumer wants
    repo-relative: `configs/demo.yaml` lists contact points that way, and PR4's
    `module_name_for(file_path, source_root)` strips a source root off the
    front, which an absolute path defeats. `repo` is the last path segment,
    which is the same convention `queries.py` uses.
    """
    parts = path.replace("\\", "/").split("/")
    if repo in parts:
        return "/".join(parts[len(parts) - 1 - parts[::-1].index(repo) + 1 :])
    return path


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
                    file_path=_relative_to_repo(_path_from_read(blob), repo),
                    line=None,
                )
            )
        return points

    def callers_of(self, fid: int, repo: str, limit: int = 25) -> list[dict[str, Any]]:
        """Functions that call `fid`, each with a repo-relative `file_path`.

        The path is what lets `core.selection` tell a test caller from a source
        caller. Without it every real caller fails `is_test_node` and the CALLS
        strategy silently selects nothing.
        """
        rows = queries.get_callers("", repo, limit=limit, fid=fid)
        return [
            {
                "name": row.get("name"),
                "fid": row.get("fid"),
                "file_path": _relative_to_repo(str(row.get("path") or ""), repo),
                "class_name": row.get("class_name"),
            }
            for row in rows
        ]

    def import_edges(self, repo: str) -> list[dict[str, Any]]:
        """Every IMPORTS edge as `{file_path, imported}`, paths repo-relative."""
        return [
            {
                "file_path": _relative_to_repo(str(row.get("file_path") or ""), repo),
                "imported": str(row.get("imported") or ""),
            }
            for row in queries.get_import_edges(repo)
        ]

    def functions_in(self, file_path: str, repo: str) -> list[dict[str, Any]]:
        """Function nodes declared in one file. `file_path` is repo-relative."""
        return [
            {
                "name": row.get("name"),
                "fid": row.get("fid"),
                "file_path": _relative_to_repo(str(row.get("path") or ""), repo),
                "class_name": row.get("class_name"),
                "start_line": row.get("start_line"),
                "end_line": row.get("end_line"),
            }
            for row in queries.get_functions_in_file(file_path, repo)
        ]

    def call_chain(
        self, frm: str, to: str, repo: str, max_hops: int = 4
    ) -> list[dict[str, Any]]:
        """Shortest CALLS path from `frm` to `to`, or an empty list."""
        chain = queries.get_call_chain(frm, to, repo, max_hops=max_hops)
        return list(chain) if chain else []

    def read_source(self, fid: int, repo: str, max_chars: int = 1500) -> str:
        """Function source for patch context. `fid` is unambiguous."""
        return str(queries.read_source("", repo, max_chars=max_chars, fid=fid))
