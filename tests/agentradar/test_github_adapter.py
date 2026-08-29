"""GitHub adapter and action gate. Subprocess is faked. No network, no real PR."""

from __future__ import annotations

import subprocess
from collections.abc import Iterator, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import pytest

from src.main.agentradar.adapters.github import (
    DEFAULT_TIMEOUT_S,
    ActionDenied,
    GateClosed,
    GhClient,
    GhError,
    execute,
    pr_writer,
    reachable_tools,
)
from src.main.agentradar.adapters.store import SqliteStore
from src.main.agentradar.contracts.dependency import ReleaseEvent
from src.main.agentradar.contracts.evidence import TestReport
from src.main.agentradar.contracts.patch import Patch, VerifyResult
from src.main.agentradar.core.patch import build_verify_result
from src.main.agentradar.core.policy import load_policy, plan_action, pr_body
from src.main.agentradar.core.testreport import parse_pytest
from src.main.agentradar.mcp import github_server
from src.main.agentradar.mcp._server import dispatch

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "fixtures"
POLICY_TEXT = (ROOT / "actions" / "policy.yaml").read_text(encoding="utf-8")

_PATCH = Patch(
    diff="--- a/src/x.py\n+++ b/src/x.py\n@@ -1 +1 @@\n-old\n+new\n",
    files=["src/x.py"],
    rationale="bump mcp 1.x -> 2.x",
)
_PR_URL = "https://github.com/example/repo/pull/7"
_ISSUE_URL = "https://github.com/example/repo/issues/3"


# -- fakes -------------------------------------------------------------------


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
            raise AssertionError(f"unexpected extra gh call: {args}")
        step = self.script[self._i]
        self._i += 1
        if isinstance(step, BaseException):
            raise step
        return step


@dataclass
class RecordingHost:
    """CodeHost that records calls and never reaches GitHub."""

    pr_calls: list[tuple[str, str, str, str]] = field(default_factory=list)
    issue_calls: list[tuple[str, str]] = field(default_factory=list)
    pr_url: str = _PR_URL
    issue_url: str = _ISSUE_URL

    def open_pr(self, branch: str, title: str, body: str, diff: str) -> str:
        self.pr_calls.append((branch, title, body, diff))
        return self.pr_url

    def open_issue(self, title: str, body: str) -> str:
        self.issue_calls.append((title, body))
        return self.issue_url


def _policy() -> dict[str, bool]:
    return load_policy(POLICY_TEXT)


def _fixture(name: str) -> str:
    return (FIXTURES / f"pytest_output_{name}.txt").read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def red_report() -> TestReport:
    return parse_pytest(_fixture("red"), "mcp", "2.1.1", "r_red")


@pytest.fixture(scope="module")
def green_report() -> TestReport:
    return parse_pytest(_fixture("green"), "mcp", "2.1.1", "r_green")


@pytest.fixture
def verified(red_report: TestReport, green_report: TestReport) -> VerifyResult:
    return build_verify_result(_PATCH, before=red_report, after=green_report)


@pytest.fixture
def host() -> RecordingHost:
    return RecordingHost()


@pytest.fixture
def store() -> SqliteStore:
    return SqliteStore(":memory:")


def _seed_mission(store: SqliteStore, verify: VerifyResult | None = None) -> str:
    mission = store.create_mission(
        ReleaseEvent(
            dependency="mcp",
            version="2.1.1",
            published_at="2026-01-15T00:00:00Z",
            title="MCP Python SDK 2.1.1",
            body="FastMCP was renamed.",
            url="https://github.com/modelcontextprotocol/python-sdk/releases/tag/v2.1.1",
            breaking_hint=True,
            source_collector="c_mcp_releases",
        )
    )
    if verify is not None:
        store.save_verify(mission.id, verify)
    return mission.id


@pytest.fixture(autouse=True)
def _inject_host(host: RecordingHost, store: SqliteStore) -> Iterator[None]:
    github_server.set_host(host)
    github_server.set_store(store)
    github_server.set_policy(_policy())
    yield
    github_server.set_host(host)
    github_server.set_store(store)
    github_server.set_policy(_policy())


# -- gate: unreachability, not a false return --------------------------------


def test_can_act_none_makes_pr_tool_unreachable(host: RecordingHost) -> None:
    """`can_act(None)` is false; the assertion that matters is unreachability."""
    assert pr_writer(host, None) is None
    assert "github_pr" not in reachable_tools(None)
    plan = plan_action(
        "github_pr",
        "open it",
        {"branch": "fix/x", "title": "fix", "diff": _PATCH.diff},
        _policy(),
    )
    with pytest.raises(GateClosed, match="unreachable"):
        execute(host, plan, approved=True, verify=None)
    assert host.pr_calls == []
    assert host.issue_calls == []


def test_verified_from_real_fixtures_makes_pr_tool_reachable(
    host: RecordingHost,
    verified: VerifyResult,
    red_report: TestReport,
    green_report: TestReport,
) -> None:
    """Reports come from parse_pytest on the captured fixtures, not hand-built.

    The red fixture is a collection error (passed=0, failed=0, errors=2). A
    hand-built `failed=2` report would hide exactly the bug this gate exists
    to survive.
    """
    assert red_report.passed == 0
    assert red_report.failed == 0
    assert red_report.errors == 2
    assert red_report.is_broken is True
    assert green_report.is_green is True
    assert verified.verified is True

    writer = pr_writer(host, verified)
    assert writer is not None
    assert "github_pr" in reachable_tools(verified)

    url = writer("fix/mcp-v2", "rename FastMCP", "body", _PATCH.diff)
    assert url == _PR_URL
    assert host.pr_calls == [("fix/mcp-v2", "rename FastMCP", "body", _PATCH.diff)]


def test_red_verification_keeps_pr_tool_unreachable(
    host: RecordingHost, red_report: TestReport
) -> None:
    still_red = build_verify_result(_PATCH, before=red_report, after=red_report)
    assert still_red.verified is False
    assert pr_writer(host, still_red) is None
    assert "github_pr" not in reachable_tools(still_red)
    assert host.pr_calls == []


# -- deny / approve ----------------------------------------------------------


def test_deny_reaches_zero_github_writes(
    host: RecordingHost, verified: VerifyResult
) -> None:
    plan = plan_action(
        "github_pr",
        "open it",
        {"branch": "fix/x", "title": "fix", "diff": _PATCH.diff},
        _policy(),
    )
    with pytest.raises(ActionDenied):
        execute(host, plan, approved=False, verify=verified)
    assert host.pr_calls == []
    assert host.issue_calls == []


def test_approve_open_pr_returns_url(
    host: RecordingHost, verified: VerifyResult, red_report: TestReport
) -> None:
    plan = plan_action(
        "github_pr",
        "Open a PR with the verified FastMCP rename.",
        {"branch": "fix/mcp-v2", "title": "fix FastMCP import", "diff": _PATCH.diff},
        _policy(),
    )
    url = execute(host, plan, approved=True, verify=verified)
    assert url == _PR_URL
    assert len(host.pr_calls) == 1
    body = host.pr_calls[0][2]
    assert f"passed={red_report.passed}" in body
    assert f"failed={red_report.failed}" in body
    assert f"errors={red_report.errors}" in body
    assert "is_broken=True" in body
    assert "verified=True" in body


def test_approve_open_issue_returns_url(host: RecordingHost) -> None:
    plan = plan_action(
        "github_issue",
        "file it",
        {"title": "FastMCP moved", "body": "import broke two tests"},
        _policy(),
    )
    url = execute(host, plan, approved=True)
    assert url == _ISSUE_URL
    assert host.issue_calls == [("FastMCP moved", "import broke two tests")]
    assert host.pr_calls == []


def test_mismatched_payload_diff_is_unreachable(
    host: RecordingHost, verified: VerifyResult
) -> None:
    plan = plan_action(
        "github_pr",
        "open it",
        {
            "branch": "fix/x",
            "title": "fix",
            "diff": "not the verified patch",
        },
        _policy(),
    )
    with pytest.raises(GateClosed, match="does not match"):
        execute(host, plan, approved=True, verify=verified)
    assert host.pr_calls == []


def test_execute_pr_uses_verified_patch_not_payload(
    host: RecordingHost, verified: VerifyResult
) -> None:
    plan = plan_action(
        "github_pr",
        "open it",
        {"branch": "fix/x", "title": "fix"},
        _policy(),
    )
    execute(host, plan, approved=True, verify=verified)
    assert host.pr_calls[0][3] == verified.patch.diff


def test_pr_body_embeds_fixture_reports(
    verified: VerifyResult, red_report: TestReport, green_report: TestReport
) -> None:
    body = pr_body("ask", verified)
    assert f"passed={red_report.passed}" in body
    assert f"errors={red_report.errors}" in body
    assert f"passed={green_report.passed}" in body
    assert _PATCH.diff.strip() in body


# -- GhClient: fake the subprocess -------------------------------------------


def test_gh_client_open_pr_returns_url() -> None:
    runner = ScriptedRunner([FakeProc(stdout=f"{_PR_URL}\n")])
    url = GhClient(runner=runner).open_pr("fix/x", "title", "body", _PATCH.diff)
    assert url == _PR_URL
    call = runner.calls[0]
    assert call[0] == "gh"
    assert call[1:3] == ["pr", "create"]
    assert "--head" in call and "fix/x" in call
    assert "--title" in call and "title" in call
    assert "--body" in call
    assert runner.timeouts == [DEFAULT_TIMEOUT_S]


def test_gh_client_open_issue_returns_url() -> None:
    runner = ScriptedRunner([FakeProc(stdout=_ISSUE_URL)])
    url = GhClient(runner=runner).open_issue("title", "body")
    assert url == _ISSUE_URL
    assert runner.calls[0][1:3] == ["issue", "create"]


def test_gh_client_raises_on_nonzero_exit_never_empty_string() -> None:
    runner = ScriptedRunner([FakeProc(returncode=1, stderr="Protected branch")])
    client = GhClient(runner=runner)
    with pytest.raises(GhError, match="exited 1") as exc_info:
        returned = client.open_issue("t", "b")
        assert returned != ""
    assert exc_info.value.exit_code == 1
    assert "Protected branch" in str(exc_info.value)


def test_gh_client_raises_on_timeout_never_empty_string() -> None:
    runner = ScriptedRunner(
        [subprocess.TimeoutExpired(cmd="gh", timeout=DEFAULT_TIMEOUT_S)]
    )
    client = GhClient(runner=runner)
    with pytest.raises(GhError, match="timed out") as exc_info:
        returned = client.open_pr("b", "t", "body", "diff")
        assert returned != ""
    assert exc_info.value.exit_code is None


def test_gh_client_raises_on_empty_stdout() -> None:
    runner = ScriptedRunner([FakeProc(returncode=0, stdout="   \n")])
    with pytest.raises(GhError, match="empty stdout"):
        GhClient(runner=runner).open_issue("t", "b")


# -- MCP call boundary -------------------------------------------------------


def test_dispatch_github_pr_unreachable_when_not_verified(
    host: RecordingHost,
    store: SqliteStore,
    red_report: TestReport,
) -> None:
    still_red = build_verify_result(_PATCH, before=red_report, after=red_report)
    mission_id = _seed_mission(store, still_red)
    result = dispatch(
        "github_pr",
        {"mission_id": mission_id, "branch": "fix/x", "title": "fix"},
    )
    assert result["error"]["type"] == "gate_closed"
    assert "unreachable" in result["error"]["message"]
    assert host.pr_calls == []


def test_dispatch_github_pr_unreachable_without_saved_verify(
    host: RecordingHost, store: SqliteStore
) -> None:
    mission_id = _seed_mission(store)
    result = dispatch(
        "github_pr",
        {"mission_id": mission_id, "branch": "fix/x", "title": "fix"},
    )
    assert result["error"]["type"] == "gate_closed"
    assert host.pr_calls == []


def test_dispatch_github_pr_rejects_caller_authored_verify() -> None:
    result = dispatch(
        "github_pr",
        {
            "mission_id": "m1",
            "branch": "fix/x",
            "title": "fix",
            "verify": {"verified": True},
        },
    )
    assert result["error"]["type"] == "invalid_input"
    assert "unexpected field" in result["error"]["message"]


def test_dispatch_github_pr_returns_action_plan(
    host: RecordingHost, store: SqliteStore, verified: VerifyResult
) -> None:
    mission_id = _seed_mission(store, verified)
    result = dispatch(
        "github_pr",
        {
            "mission_id": mission_id,
            "branch": "fix/mcp-v2",
            "title": "fix FastMCP",
            "summary": "Open the PR",
        },
    )
    assert "error" not in result
    assert result["target"] == "github_pr"
    assert result["requires_approval"] is True
    assert result["payload"]["url"] == _PR_URL
    assert len(host.pr_calls) == 1
    assert "errors=2" in host.pr_calls[0][2]
    assert host.pr_calls[0][3] == verified.patch.diff


def test_dispatch_github_issue_returns_action_plan(host: RecordingHost) -> None:
    result = dispatch(
        "github_issue",
        {"title": "FastMCP moved", "body": "two modules failed to import"},
    )
    assert "error" not in result
    assert result["target"] == "github_issue"
    assert result["payload"]["url"] == _ISSUE_URL
    assert host.issue_calls == [("FastMCP moved", "two modules failed to import")]
