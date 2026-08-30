"""Read a bot reviewer's findings off a pull request, via `gh`.

Consumers type-hint :class:`ReviewSource`, never :class:`GhReviewSource`
(spine rule 3).

**Pull, not push.** A GitHub webhook would need a public tunnel to this
machine; polling the PR needs nothing but the `gh` auth already on it. The
verification logic lives in `core/finding.py` and takes plain contracts, so a
webhook handler is a thin wrapper over the same code whenever a public
endpoint exists — the transport is the only thing this module decides.

Errors are typed and never swallowed into an empty list: "the reviewer found
nothing" and "we failed to ask" must not look identical, because the first
is a clean bill of health and the second is a broken pipeline.
"""

from __future__ import annotations

import json
import re
from typing import Any, Protocol

from src.main.agentradar.contracts.finding import ReviewFinding

from .github import CommandRunner, GhError, SubprocessRunner

DEFAULT_TIMEOUT_S = 60.0

# Bots that review code. A PR carries human chatter too, and a human saying
# "nice" is not a finding to verify.
DEFAULT_REVIEWERS = (
    "qodo-code-review[bot]",
    "qodo-merge-pro",
    "qodo-merge-pro[bot]",
    "codiumai-pr-agent",
)

_MARKDOWN_NOISE = re.compile(r"[*_`#]+")
_HTML_TAG = re.compile(r"<[^>]*>")
# Qodo opens each comment with a severity badge rendered as an <img> tag and a
# horizontal rule. Neither is the claim, and a title reading
# `<img src="https://img.shields.io/badge/High-...">` is useless on a report.
_RULE = re.compile(r"^[-=_\s]*$")
_TITLE_MAX = 120


class ReviewSource(Protocol):
    """Somewhere review findings can be read from."""

    def findings(self, pr: int) -> list[ReviewFinding]: ...


def _clean_title(body: str) -> str:
    """First meaningful line of a comment, stripped of markdown decoration.

    Qodo leads with a bolded label such as `**Possible issue:**`, so the first
    non-empty line is the claim in miniature. Falls back to the whole body
    when the comment is a single unbroken paragraph.
    """
    for raw in body.splitlines():
        line = _HTML_TAG.sub("", raw)
        line = _MARKDOWN_NOISE.sub("", line).strip()
        if line and not _RULE.match(line):
            return line[:_TITLE_MAX]
    stripped = _HTML_TAG.sub("", body).strip()
    return stripped[:_TITLE_MAX] or "untitled finding"


def parse_review_comments(
    payload: str, *, reviewers: tuple[str, ...] = DEFAULT_REVIEWERS
) -> list[ReviewFinding]:
    """Parse `gh api .../pulls/N/comments` JSON into findings.

    Split out from the subprocess call so it is testable against a recorded
    fixture with no network and no `gh` — the same discipline
    `adapters/brightdata.py` follows.

    A comment whose line GitHub reports as null (the diff hunk moved) keeps
    its file and loses its line. `core.finding.locate_finding` degrades to a
    whole-file blast radius in that case rather than discarding the finding.
    """
    try:
        rows: Any = json.loads(payload or "[]")
    except json.JSONDecodeError as exc:
        raise GhError(f"review comments were not valid JSON: {exc}") from exc

    if not isinstance(rows, list):
        raise GhError(f"expected a JSON array of comments, got {type(rows).__name__}")

    wanted = {name.lower() for name in reviewers}
    findings: list[ReviewFinding] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        user = row.get("user")
        login = str(user.get("login") or "") if isinstance(user, dict) else ""
        if wanted and login.lower() not in wanted:
            continue

        body = str(row.get("body") or "")
        if not body.strip():
            continue

        line = row.get("line")
        if not isinstance(line, int):
            line = row.get("original_line")
        findings.append(
            ReviewFinding(
                id=str(row.get("id") or ""),
                reviewer=login or "unknown",
                file_path=str(row.get("path") or ""),
                line=line if isinstance(line, int) else None,
                title=_clean_title(body),
                body=body,
                url=str(row.get("html_url") or "") or None,
            )
        )
    return findings


class GhReviewSource:
    """ReviewSource backed by `gh api`. Auth is whatever `gh auth` already has."""

    def __init__(
        self,
        repo: str,
        *,
        runner: CommandRunner | None = None,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        binary: str = "gh",
        reviewers: tuple[str, ...] = DEFAULT_REVIEWERS,
    ) -> None:
        self._repo = repo
        self._runner: CommandRunner = (
            runner if runner is not None else SubprocessRunner()
        )
        self._timeout_s = timeout_s
        self._binary = binary
        self._reviewers = reviewers

    def findings(self, pr: int) -> list[ReviewFinding]:
        """Every review finding a known bot left on `pr`, oldest first."""
        args = [
            self._binary,
            "api",
            f"repos/{self._repo}/pulls/{pr}/comments",
            "--paginate",
        ]
        proc = self._runner.run(args, timeout_s=self._timeout_s)
        if proc.returncode != 0:
            raise GhError(
                f"gh api failed for {self._repo} PR #{pr}",
                exit_code=proc.returncode,
                stderr=proc.stderr,
            )
        return parse_review_comments(proc.stdout, reviewers=self._reviewers)
