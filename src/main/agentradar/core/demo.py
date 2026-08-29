"""Parse the demo target out of `configs/demo.yaml`.

Pure: takes YAML text, returns a contract. No file reads, no clock, no network.

Exists because the conductor had no way to learn *which repository* it was
working on. `configs/demo.yaml` was read only by a local smoke script, so a
mission that reached the sandbox invented a clone URL, got a 404 from GitHub,
and reported `could not read Username` — which reads like a credentials
problem and is not one.
"""

from __future__ import annotations

from typing import Any

import yaml  # type: ignore[import-untyped]

from ..contracts.dependency import DemoTarget

__all__ = ["ANSWER_KEYS", "load_demo_target"]

# Keys in `configs/demo.yaml` that state the expected result. They are the
# checkable answer, so they must never reach the agent — see `DemoTarget`.
ANSWER_KEYS = frozenset(
    {
        "expected_contact_points",
        "expected_test_selection",
        "expected_selection_strategy",
        "expected_patch_shape",
        "not_selected",
        "red_is_collection_error",
    }
)


def load_demo_target(text: str) -> DemoTarget:
    """Parse `configs/demo.yaml` text into a `DemoTarget`.

    Raises `ValueError` on a missing `demo:` block or a missing required key,
    rather than filling a default. A silently-empty `repo_url` is exactly the
    failure this function exists to stop.
    """
    try:
        parsed: Any = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        raise ValueError(f"configs/demo.yaml is not valid YAML: {exc}") from exc
    if not isinstance(parsed, dict) or not isinstance(parsed.get("demo"), dict):
        raise ValueError("configs/demo.yaml has no `demo:` mapping")

    demo: dict[str, Any] = parsed["demo"]
    fields = DemoTarget.model_fields
    missing = sorted(k for k in fields if not str(demo.get(k, "")).strip())
    if missing:
        raise ValueError(f"configs/demo.yaml `demo:` is missing {', '.join(missing)}")

    return DemoTarget.model_validate({k: str(demo[k]) for k in fields})
