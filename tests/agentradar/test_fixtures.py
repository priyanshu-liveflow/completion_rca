"""Tests for fixture recording and committed mission captures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from record_fixtures import (  # noqa: E402
    _SECRET_TOKEN,
    assert_loopback,
    iter_sse_events,
    redact_value,
)

MISSIONS_DIR = ROOT / "fixtures" / "missions"


def test_redact_scrubs_secret_prefixes() -> None:
    assert redact_value("dtn_abc123secret") == "[REDACTED]"
    assert redact_value("nvapi-xyz") == "[REDACTED]"
    assert redact_value("sk-live-foo") == "[REDACTED]"
    assert redact_value("ghp_abcdefghijklmnop") == "[REDACTED]"
    assert redact_value("safe-value") == "safe-value"


def test_redact_scrubs_sensitive_keys() -> None:
    payload = {
        "headers": {"Authorization": "Bearer secret-token"},
        "auth": {"api_key": "dtn_should_be_redacted"},
        "connection_string": "postgres://user:pass@host/db",
    }
    redacted = redact_value(payload)
    assert redacted["headers"]["Authorization"] == "[REDACTED]"
    assert redacted["auth"]["api_key"] == "[REDACTED]"
    assert redacted["connection_string"] == "[REDACTED]"


@pytest.mark.parametrize("fixture_path", sorted(MISSIONS_DIR.glob("*.jsonl")))
def test_committed_fixtures_contain_no_secrets(fixture_path: Path) -> None:
    """No secret token survives into a committed fixture.

    Matched as a token, not a bare substring: `"sk-" in text` is true of
    "task-force" and "risk-averse", and a scan that cries wolf on ordinary
    prose is one someone eventually deletes.
    """
    text = fixture_path.read_text(encoding="utf-8")
    hits = _SECRET_TOKEN.findall(text)
    assert not hits, f"{fixture_path.name} contains secret token(s): {hits[:3]}"


@pytest.mark.parametrize("fixture_path", sorted(MISSIONS_DIR.glob("*.jsonl")))
def test_committed_fixtures_have_monotonic_timing(fixture_path: Path) -> None:
    """`t_ms` never goes backwards, so replay honours the recorded gaps.

    The first committed capture dropped 816 -> 0 and 6664 -> 0, because the
    recorder mixed a server `created_at` clock with the local monotonic one
    and only 8 of 38 events carried `created_at`. A fixture is the offline
    demo; timing that runs backwards on stage is the failure this catches.
    """
    events = [
        json.loads(line)
        for line in fixture_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    times = [event["t_ms"] for event in events]
    assert all(t >= 0 for t in times), f"{fixture_path.name} has negative t_ms"
    backward = [
        (i, times[i - 1], times[i])
        for i in range(1, len(times))
        if times[i] < times[i - 1]
    ]
    assert not backward, f"{fixture_path.name} t_ms runs backwards at {backward[:3]}"


def test_demo_fixture_has_required_events() -> None:
    demo = MISSIONS_DIR / "demo.jsonl"
    if not demo.exists():
        pytest.skip("demo.jsonl not recorded yet")

    lines = [line for line in demo.read_text().splitlines() if line.strip()]
    types = [json.loads(line)["type"] for line in lines]
    assert "sandbox.created" in types, "fixture must include sandbox.created"
    assert "tool.response" in types, "fixture must include tool.response"
    assert types[-1] == "turn.done", "fixture must end on turn.done"


# -- redaction reaches inside strings ---------------------------------------


def test_redact_scrubs_secrets_nested_in_json_encoded_content() -> None:
    """`tool.response.content` is a JSON *string*, so recursion never enters it.

    A `startswith` check treats the whole blob as one opaque non-secret and
    writes the key straight to a fixture that gets committed.
    """
    event = {
        "type": "tool.response",
        "content": '{"stdout": "NVIDIA_API_KEY=nvapi-abc123def456 exported"}',
    }
    redacted = redact_value(event)
    assert "nvapi-abc123def456" not in redacted["content"]
    assert "[REDACTED]" in redacted["content"]


def test_redact_leaves_ordinary_prose_alone() -> None:
    """`sk-` is a substring of "task-force"; a scan that fires there is noise."""
    text = "a task-force reviewing risk-averse plans"
    assert redact_value(text) == text


# -- SSE parsing: timing and line endings -----------------------------------


class _ChunkedResponse:
    """A stream that hands over exactly one chunk per read, then stops.

    Stands in for `HTTPResponse`, whose `read(4096)` blocks until it has 4096
    bytes or the response closes. Each chunk here is a separate `read1`, so a
    reader that batches shows up as events arriving together.
    """

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = list(chunks)
        self.reads = 0

    def read1(self, _size: int = -1) -> bytes:
        self.reads += 1
        return self._chunks.pop(0) if self._chunks else b""


def _sse(payload: dict[str, object], sep: bytes = b"\n\n") -> bytes:
    return b"data: " + json.dumps(payload).encode() + sep


def test_events_are_yielded_as_each_arrives_not_in_one_batch() -> None:
    """One event out per chunk in, so `t_ms` records arrival, not parse time."""
    stream = _ChunkedResponse([_sse({"type": "a"}), _sse({"type": "b"})])
    events = iter_sse_events(stream)

    first, _ = next(events)
    assert first["type"] == "a"
    assert stream.reads == 1, "second chunk was consumed before the first yielded"

    second, _ = next(events)
    assert second["type"] == "b"


@pytest.mark.parametrize(
    "sep", [b"\n\n", b"\r\n\r\n", b"\r\r"], ids=["lf", "crlf", "cr"]
)
def test_every_valid_line_ending_terminates_an_event(sep: bytes) -> None:
    """CRLF, lone LF and lone CR are all valid event-stream line endings."""
    stream = _ChunkedResponse([_sse({"type": "a"}, sep) + _sse({"type": "b"}, sep)])
    assert [e["type"] for e, _ in iter_sse_events(stream)] == ["a", "b"]


def test_mixed_line_endings_do_not_merge_adjacent_events() -> None:
    """The bug: searching for LF-LF first splits at the later delimiter.

    With a CRLF event ahead of an LF event, taking the first `b"\\n\\n"` found
    anywhere in the buffer cuts past the CRLF boundary and hands two
    concatenated JSON objects to one `json.loads`.
    """
    stream = _ChunkedResponse(
        [_sse({"type": "a"}, b"\r\n\r\n") + _sse({"type": "b"}, b"\n\n")]
    )
    assert [e["type"] for e, _ in iter_sse_events(stream)] == ["a", "b"]


def test_crlf_split_across_chunks_does_not_invent_a_blank_line() -> None:
    """A trailing CR may be half of a CRLF still in flight."""
    stream = _ChunkedResponse([b'data: {"type": "a"}\r', b"\n\r\n"])
    assert [e["type"] for e, _ in iter_sse_events(stream)] == ["a"]


# -- network boundary --------------------------------------------------------


def test_loopback_guard_rejects_a_remote_trueforge_url() -> None:
    """`TRUEFORGE_URL` is an env var; the localhost exception must be enforced."""
    with pytest.raises(SystemExit) as excinfo:
        assert_loopback("https://trueforge.example.com")
    assert "Bright Data" in str(excinfo.value)


@pytest.mark.parametrize(
    "url", ["http://localhost:8790", "http://127.0.0.1:8790", "http://[::1]:8790"]
)
def test_loopback_guard_allows_local_urls(url: str) -> None:
    assert_loopback(url)
