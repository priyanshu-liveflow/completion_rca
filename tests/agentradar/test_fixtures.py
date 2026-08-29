"""Tests for fixture recording and committed mission captures."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))

from record_fixtures import SECRET_PREFIXES, redact_value  # noqa: E402

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
    text = fixture_path.read_text(encoding="utf-8")
    for prefix in SECRET_PREFIXES:
        assert prefix not in text, (
            f"{fixture_path.name} contains secret prefix {prefix!r}"
        )


def test_demo_fixture_has_required_events() -> None:
    demo = MISSIONS_DIR / "demo.jsonl"
    if not demo.exists():
        pytest.skip("demo.jsonl not recorded yet")

    lines = [line for line in demo.read_text().splitlines() if line.strip()]
    types = [json.loads(line)["type"] for line in lines]
    assert "sandbox.created" in types, "fixture must include sandbox.created"
    assert "tool.response" in types, "fixture must include tool.response"
    assert types[-1] == "turn.done", "fixture must end on turn.done"
