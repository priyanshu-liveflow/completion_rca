"""Tests for the review-source adapter. No network, no `gh` — recorded JSON."""

from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from src.main.agentradar.adapters.github import GhError
from src.main.agentradar.adapters.review import (
    GhReviewSource,
    parse_review_comments,
)


def _comment(
    cid: int,
    path: str,
    line: int | None,
    body: str,
    login: str = "qodo-code-review[bot]",
) -> dict[str, object]:
    return {
        "id": cid,
        "path": path,
        "line": line,
        "body": body,
        "user": {"login": login},
        "html_url": f"https://github.com/o/r/pull/1#discussion_r{cid}",
    }


def test_parses_a_single_page_of_comments() -> None:
    payload = json.dumps([_comment(1, "src/a.py", 10, "**Bug:** boom\nmore text")])
    findings = parse_review_comments(payload)
    assert len(findings) == 1
    assert findings[0].file_path == "src/a.py"
    assert findings[0].line == 10
    assert findings[0].title == "Bug: boom"


def test_paginated_output_is_parsed_not_rejected() -> None:
    """`gh api --paginate` concatenates one JSON array per page.

    Two pages arrive as `[{...}][{...}]`, which is not a valid JSON document.
    Treating that as a parse error loses every finding past the first page on
    any PR large enough to paginate — silently, because the failure looks
    like a broken reviewer rather than a broken reader.
    """
    page1 = json.dumps([_comment(1, "src/a.py", 10, "first")])
    page2 = json.dumps([_comment(2, "src/b.py", 20, "second")])

    findings = parse_review_comments(page1 + page2)

    assert [f.file_path for f in findings] == ["src/a.py", "src/b.py"]


def test_paginated_output_with_whitespace_between_pages() -> None:
    """Real `gh` output separates pages with a newline."""
    page1 = json.dumps([_comment(1, "src/a.py", 10, "first")])
    page2 = json.dumps([_comment(2, "src/b.py", 20, "second")])

    findings = parse_review_comments(f"{page1}\n{page2}\n")

    assert len(findings) == 2


def test_comments_from_other_authors_are_ignored() -> None:
    payload = json.dumps(
        [
            _comment(1, "src/a.py", 1, "bot finding"),
            _comment(2, "src/b.py", 2, "nice work", login="a-human"),
        ]
    )
    findings = parse_review_comments(payload)
    assert [f.file_path for f in findings] == ["src/a.py"]


def test_missing_line_falls_back_to_original_line() -> None:
    row = _comment(1, "src/a.py", None, "moved hunk")
    row["original_line"] = 42
    findings = parse_review_comments(json.dumps([row]))
    assert findings[0].line == 42


def test_line_stays_none_when_github_reports_neither() -> None:
    findings = parse_review_comments(json.dumps([_comment(1, "src/a.py", None, "x")]))
    assert findings[0].line is None


def test_html_badges_do_not_become_the_title() -> None:
    body = (
        '<img src="https://img.shields.io/badge/High-634FD1" height="20px">\n'
        "\n___\n\n**Agent proxy lacks access control**\n\ndetail"
    )
    findings = parse_review_comments(json.dumps([_comment(1, "src/a.py", 1, body)]))
    assert findings[0].title == "Agent proxy lacks access control"


def test_empty_body_is_not_a_finding() -> None:
    assert parse_review_comments(json.dumps([_comment(1, "src/a.py", 1, "   ")])) == []


def test_malformed_json_raises_rather_than_returning_nothing() -> None:
    """ "The reviewer found nothing" and "we failed to ask" must not look alike."""
    with pytest.raises(GhError):
        parse_review_comments("{not json at all")


def test_non_array_payload_raises() -> None:
    with pytest.raises(GhError):
        parse_review_comments(json.dumps({"message": "Not Found"}))


def test_empty_payload_is_an_empty_review() -> None:
    assert parse_review_comments("") == []


@dataclass
class _Proc:
    returncode: int
    stdout: str
    stderr: str


class _FakeRunner:
    def __init__(self, proc: _Proc) -> None:
        self.proc = proc
        self.args: list[str] = []

    def run(self, args: list[str], *, timeout_s: float) -> _Proc:
        self.args = list(args)
        return self.proc


def test_source_raises_typed_error_on_gh_failure() -> None:
    runner = _FakeRunner(_Proc(1, "", "gh: Not Found"))
    source = GhReviewSource("o/r", runner=runner)  # type: ignore[arg-type]
    with pytest.raises(GhError) as excinfo:
        source.findings(7)
    assert excinfo.value.exit_code == 1


def test_source_returns_findings_on_success() -> None:
    payload = json.dumps([_comment(1, "src/a.py", 3, "**Bug:** x")])
    runner = _FakeRunner(_Proc(0, payload, ""))
    source = GhReviewSource("o/r", runner=runner)  # type: ignore[arg-type]
    findings = source.findings(7)
    assert len(findings) == 1
    assert "repos/o/r/pulls/7/comments" in runner.args
