"""Replay a recorded mission fixture with no network.

    python scripts/replay_fixture.py fixtures/missions/demo.jsonl [--speed 2.0]

Honors recorded ``t_ms`` gaps so output resembles a live run. ``--speed 0``
dumps instantly.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def format_event(event: dict[str, Any], t_ms: int | None = None) -> str:
    """Render one recorded event for demo output.

    `t_ms` overrides the event's own value so the printed clock is the same
    one the replay sleeps on. They diverge only for a fixture recorded before
    the recorder's timing was fixed, and a demo that prints times running
    backwards is worse than one that prints nothing.
    """
    if t_ms is None:
        t_ms = int(event.get("t_ms", 0))
    event_type = event.get("type", "unknown")
    parts = [f"[{t_ms:5d}ms] {event_type}"]

    if event_type == "model.message.delta":
        text = event.get("content") or event.get("reasoning_content") or ""
        if text:
            parts.append(text.rstrip("\n"))
    elif event_type == "model.message":
        parts.append(f"thread={event.get('thread_id', '?')}")
    elif event_type == "tool.response":
        content = event.get("content", "")
        if len(content) > 120:
            content = content[:117] + "..."
        parts.append(content)
    elif event_type == "sandbox.created":
        parts.append(f"sandbox_id={event.get('sandbox_id', '?')}")
    elif event_type == "turn.done":
        state = event.get("state", {})
        status = state.get("status", "?")
        metrics = state.get("metrics", {})
        tokens = metrics.get("total_tokens")
        suffix = f"status={status}"
        if tokens is not None:
            suffix += f" tokens={tokens}"
        parts.append(suffix)
        output = state.get("output", {})
        if isinstance(output, dict) and output.get("content"):
            parts.append("")
            parts.append(str(output["content"]).rstrip())
    elif event_type == "turn.created":
        user_input = event.get("input", [])
        if user_input:
            content = user_input[0].get("content", "")
            if content:
                parts.append(
                    f"prompt: {content[:80]}{'...' if len(content) > 80 else ''}"
                )

    return (
        "  ".join(parts)
        if len(parts) == 2 and "\n" not in parts[1]
        else "\n".join(parts)
    )


def replay(path: Path, *, speed: float) -> int:
    lines = path.read_text(encoding="utf-8").splitlines()
    if not lines:
        print(f"empty fixture: {path}", file=sys.stderr)
        return 1

    prev_t = 0
    count = 0
    for line in lines:
        if not line.strip():
            continue
        event = json.loads(line)
        t_ms = max(prev_t, int(event.get("t_ms", 0)))
        if speed > 0 and count > 0:
            delay = max(0.0, (t_ms - prev_t) / 1000.0 / speed)
            time.sleep(delay)
        print(format_event(event, t_ms))
        sys.stdout.flush()
        prev_t = t_ms
        count += 1

    print(f"\n--- replay complete ({count} events) ---", file=sys.stderr)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Replay a recorded mission fixture.")
    parser.add_argument("fixture", type=Path, help="JSONL fixture path")
    parser.add_argument(
        "--speed",
        type=float,
        default=1.0,
        help="Playback speed multiplier (0 = instant)",
    )
    args = parser.parse_args()
    if not args.fixture.exists():
        print(f"fixture not found: {args.fixture}", file=sys.stderr)
        return 1
    return replay(args.fixture, speed=args.speed)


if __name__ == "__main__":
    sys.exit(main())
