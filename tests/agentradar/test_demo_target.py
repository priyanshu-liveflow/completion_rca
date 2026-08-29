"""`get_demo_target` — the agent cannot guess a clone URL.

A recorded mission tried three times to clone and got
`could not read Username for 'https://github.com'`. That reads like a
credentials failure; it is GitHub 404ing a repository that does not exist,
because nothing told the agent which repository to clone. The sandbox had
full egress the whole time (`pypi:200`, `github:200`, `pip download` fine).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.main.agentradar.contracts.dependency import DemoTarget
from src.main.agentradar.core.demo import ANSWER_KEYS, load_demo_target
from src.main.agentradar.mcp import store_server
from src.main.agentradar.mcp._server import dispatch

ROOT = Path(__file__).resolve().parents[2]
DEMO_YAML = (ROOT / "configs" / "demo.yaml").read_text(encoding="utf-8")


def test_parses_the_real_demo_config() -> None:
    target = load_demo_target(DEMO_YAML)
    assert target.repo_url == "https://github.com/mvilanova/intervals-mcp-server"
    assert target.commit == "cb1fbcac81095cf3e094e995decf04b8b1f259f8"
    assert target.symbol == "FastMCP"
    assert (target.from_version, target.to_version) == ("1.29.1", "2.1.1")


def test_the_answer_key_is_never_exposed() -> None:
    """`demo.yaml` holds the expected result. Handing it over voids the demo.

    The impact table is only evidence if the graph produced it. An agent that
    can read `expected_contact_points` can report them without the graph
    running at all, and nothing downstream would notice.
    """
    exposed = set(DemoTarget.model_fields)
    assert exposed.isdisjoint(ANSWER_KEYS)
    payload = dispatch("get_demo_target", {})
    assert "error" not in payload
    assert set(payload).isdisjoint(ANSWER_KEYS)
    # The values, not just the key names, must be absent.
    blob = repr(payload)
    assert "mcp_instance.py" not in blob, "leaked an expected contact point"
    assert "test_server.py" not in blob, "leaked an expected test selection"


def test_missing_demo_block_raises_rather_than_defaulting() -> None:
    with pytest.raises(ValueError, match="no `demo:` mapping"):
        load_demo_target("something_else:\n  a: 1\n")


@pytest.mark.parametrize("field", ["repo_url", "commit", "symbol"])
def test_a_blank_required_field_raises(field: str) -> None:
    """A silently-empty `repo_url` is the failure this parser exists to stop."""
    import yaml

    parsed = yaml.safe_load(DEMO_YAML)
    parsed["demo"][field] = "   "
    with pytest.raises(ValueError, match=field):
        load_demo_target(yaml.safe_dump(parsed))


def test_tool_is_registered_on_the_store_server() -> None:
    assert store_server.get_demo_target is not None
    payload = dispatch("get_demo_target", {})
    assert payload["repo_url"].startswith("https://github.com/")
