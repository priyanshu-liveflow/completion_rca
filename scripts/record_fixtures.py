"""Record a TrueForge turn to JSONL for offline replay.

    python scripts/record_fixtures.py --agent conductor --prompt "..." \\
        --out fixtures/missions/demo.jsonl

Stdlib only. Subscribes to the SSE stream from POST /api/v1/sessions/{id}/turns,
writes every event in arrival order with relative ``t_ms``, stops on ``turn.done``.
Secrets are redacted before anything hits disk.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("TRUEFORGE_URL", "http://localhost:8790")

SECRET_PREFIXES = ("dtn_", "nvapi-", "sk-", "ghp_")
SENSITIVE_KEYS = frozenset({
    "authorization", "api_key", "token", "bearer", "connection_string",
})


def redact_string(value: str) -> str:
    """Scrub secret prefixes from a string value."""
    for prefix in SECRET_PREFIXES:
        if value.startswith(prefix):
            return "[REDACTED]"
    return value


def redact_value(value: Any, *, key: str | None = None) -> Any:
    """Recursively redact secrets from a JSON-serializable value."""
    if key is not None and key.lower() in SENSITIVE_KEYS:
        return "[REDACTED]"
    if isinstance(value, str):
        return redact_string(value)
    if isinstance(value, dict):
        return {k: redact_value(v, key=k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(item) for item in value]
    return value


def parse_sse_block(raw: bytes) -> dict[str, Any] | None:
    """Parse one SSE block into a JSON event dict, or None if empty."""
    data_lines: list[str] = []
    for line in raw.decode("utf-8", errors="replace").splitlines():
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    return json.loads("\n".join(data_lines))


def iter_sse_events(response: Any):
    """Yield parsed event dicts from an open SSE response."""
    buffer = b""
    while True:
        chunk = response.read(4096)
        if not chunk:
            break
        buffer += chunk
        while True:
            for sep in (b"\n\n", b"\r\n\r\n"):
                if sep in buffer:
                    raw, buffer = buffer.split(sep, 1)
                    event = parse_sse_block(raw)
                    if event is not None:
                        yield event
                    break
            else:
                break


def api_request(
    method: str, path: str, body: dict | None = None, *, accept_sse: bool = False,
    timeout: int = 600,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if accept_sse:
        headers["Accept"] = "text/event-stream"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(f"{BASE}{path}", data=data, method=method, headers=headers)
    try:
        return urllib.request.urlopen(request, timeout=timeout)
    except urllib.error.HTTPError as exc:
        payload = exc.read().decode("utf-8", errors="replace")
        print(f"HTTP {exc.code} {method} {path}: {payload[:500]}", file=sys.stderr)
        raise SystemExit(1) from exc
    except urllib.error.URLError as exc:
        print(f"cannot reach TrueForge at {BASE}: {exc.reason}", file=sys.stderr)
        print("start it with:  npx @truefoundry/trueforge@latest", file=sys.stderr)
        raise SystemExit(2) from exc


def create_session(agent: str) -> str:
    with api_request("POST", "/api/v1/sessions", {"agent": {"name": agent}}) as response:
        body = json.loads(response.read() or b"{}")
    session_id = body.get("data", {}).get("id")
    if not session_id:
        print(f"session create returned no id: {body}", file=sys.stderr)
        raise SystemExit(1)
    return session_id


def record_turn(agent: str, prompt: str, out_path: Path) -> list[str]:
    """Record one turn to *out_path*. Returns observed event type names."""
    session_id = create_session(agent)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    event_types: list[str] = []
    t0_mono: float | None = None
    t0_created: float | None = None
    last_t_ms = -1

    def event_t_ms(event: dict[str, Any]) -> int:
        nonlocal t0_mono, t0_created, last_t_ms
        now = time.monotonic()
        if t0_mono is None:
            t0_mono = now
        created = event.get("created_at")
        if isinstance(created, str):
            ts = datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()
            if t0_created is None:
                t0_created = ts
            t_ms = max(0, int((ts - t0_created) * 1000))
        else:
            t_ms = int((now - t0_mono) * 1000)
        if t_ms <= last_t_ms:
            t_ms = last_t_ms + 1
        last_t_ms = t_ms
        return t_ms

    with api_request(
        "POST",
        f"/api/v1/sessions/{session_id}/turns",
        {"input": [{"type": "user.message", "content": prompt}]},
        accept_sse=True,
    ) as stream:
        with out_path.open("w", encoding="utf-8") as handle:
            for event in iter_sse_events(stream):
                record = {"t_ms": event_t_ms(event), **redact_value(event)}
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                event_type = record.get("type", "unknown")
                event_types.append(event_type)
                print(f"  [{record['t_ms']:5d}ms] {event_type}", file=sys.stderr)
                if event_type == "turn.done":
                    break

    return event_types


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a TrueForge turn to JSONL.")
    parser.add_argument("--agent", default="conductor", help="Agent name (default: conductor)")
    parser.add_argument("--prompt", required=True, help="User message for the turn")
    parser.add_argument("--out", type=Path, required=True, help="Output JSONL path")
    args = parser.parse_args()

    print(f"recording {args.agent!r} -> {args.out}", file=sys.stderr)
    event_types = record_turn(args.agent, args.prompt, args.out)
    print(f"wrote {len(event_types)} events to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
