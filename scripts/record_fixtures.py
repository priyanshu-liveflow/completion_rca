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
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("TRUEFORGE_URL", "http://localhost:8790")

# CLAUDE.md routes all outbound *web* access through Bright Data. This script
# talks to the local TrueForge control plane, which is not web access — but
# `TRUEFORGE_URL` is an env var, and "it is only ever localhost" is a claim
# about how someone runs the script rather than about what the script does.
# The guard turns it into the latter. See docs/decisions.md.
_LOOPBACK_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})


def assert_loopback(url: str) -> None:
    """Refuse any TrueForge base URL that is not loopback.

    The Bright Data rule exists so that no module except
    `adapters/brightdata.py` can quietly become a general-purpose HTTP
    client. Pinning this one to loopback keeps that true no matter what
    `TRUEFORGE_URL` is set to.
    """
    host = urlparse(url).hostname
    if host not in _LOOPBACK_HOSTS:
        raise SystemExit(
            f"TRUEFORGE_URL must point at loopback, got {url!r} (host {host!r}). "
            "All non-local web access goes through Bright Data "
            "(adapters/brightdata.py) — see CLAUDE.md."
        )


SECRET_PREFIXES = ("dtn_", "nvapi-", "sk-", "ghp_")
SENSITIVE_KEYS = frozenset(
    {
        "authorization",
        "api_key",
        "token",
        "bearer",
        "connection_string",
    }
)

# A secret is scrubbed wherever it appears in a string, not only when the
# string *is* the secret. `tool.response.content` arrives as JSON encoded
# into a string, so a `startswith` check walks straight past
# `{"env":{"NVIDIA_API_KEY":"nvapi-..."}}` and writes it to a fixture that
# gets committed. The recursion below never descends into that string, so the
# scan has to.
#
# The leading lookbehind is what keeps this from firing on ordinary prose:
# without it `sk-` matches inside "task-force" and "risk-averse", and a
# committed fixture full of false positives is a fixture nobody trusts.
_SECRET_TOKEN = re.compile(
    r"(?<![A-Za-z0-9_])(?:" + "|".join(re.escape(p) for p in SECRET_PREFIXES) + r")"
    r"[A-Za-z0-9_\-]{3,}"
)


def redact_string(value: str) -> str:
    """Scrub secret tokens anywhere in a string, not just at its start."""
    return _SECRET_TOKEN.sub("[REDACTED]", value)


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


# The event-stream grammar ends a line with CRLF, a lone LF, or a lone CR, and
# any of the three may form the blank line that terminates an event. Searching
# for `b"\n\n"` before `b"\r\n\r\n"` picks whichever appears first in the
# buffer rather than whichever comes first in the stream, so a mixed-ending
# stream splits in the wrong place and two events get concatenated into one
# `json.loads`. Matching a single line-ending alternation removes the ordering
# question entirely.
_LINE_END = re.compile(rb"\r\n|\n|\r")


def parse_sse_fields(lines: list[bytes]) -> dict[str, Any] | None:
    """Parse one SSE block's lines into a JSON event dict, or None if empty."""
    data_lines: list[str] = []
    for raw in lines:
        line = raw.decode("utf-8", errors="replace")
        if line.startswith("data:"):
            data_lines.append(line[5:].strip())
    if not data_lines:
        return None
    return json.loads("\n".join(data_lines))


def iter_sse_events(response: Any) -> Any:
    """Yield ``(event, arrival_monotonic)`` as each SSE block completes.

    Reads with ``read1`` so a chunk is handed over the moment it arrives.
    ``HTTPResponse.read(4096)`` blocks until it has 4096 bytes or the response
    closes, and SSE events here run a couple of hundred bytes each. Measured
    against a local server emitting four events 400ms apart:

        read(4096)   -> one return at 1610ms carrying all 88 bytes
        read1(4096)  -> 0ms, 401ms, 806ms, 1206ms, one event each

    With ``read``, every event is stamped with the same arrival time and
    ``turn.done`` is not acted on until the connection closes. For a recorder
    whose entire output is timing, that is the whole product.
    """
    buffer = b""
    fields: list[bytes] = []
    read = getattr(response, "read1", None) or response.read

    def take_lines() -> Any:
        """Split whole lines off the front of the buffer as they complete."""
        nonlocal buffer
        while True:
            match = _LINE_END.search(buffer)
            if match is None:
                return
            # A trailing lone CR may be the first half of a CRLF still in
            # flight; splitting now would invent a blank line and cut an
            # event in two.
            if match.group() == b"\r" and match.end() == len(buffer):
                return
            line, buffer = buffer[: match.start()], buffer[match.end() :]
            yield line

    while True:
        chunk = read(4096)
        if not chunk:
            break
        buffer += chunk
        for line in take_lines():
            if line:
                fields.append(line)
                continue
            event = parse_sse_fields(fields)
            fields = []
            if event is not None:
                yield event, time.monotonic()

    if buffer:
        fields.append(buffer)
    if fields:
        event = parse_sse_fields(fields)
        if event is not None:
            yield event, time.monotonic()


def api_request(
    method: str,
    path: str,
    body: dict | None = None,
    *,
    accept_sse: bool = False,
    timeout: int = 600,
) -> Any:
    headers = {"Content-Type": "application/json"}
    if accept_sse:
        headers["Accept"] = "text/event-stream"
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method, headers=headers
    )
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
    with api_request(
        "POST", "/api/v1/sessions", {"agent": {"name": agent}}
    ) as response:
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
    t0: float | None = None
    last_t_ms = 0

    def event_t_ms(arrived: float) -> int:
        """Milliseconds since the first event arrived. One clock, never two.

        The previous version read `created_at` when present and fell back to
        the monotonic clock when absent, with the two baselines taken from
        *different* events — only 8 of 38 events in a real capture carry
        `created_at`, so the series interleaved two unrelated origins and
        walked backwards (816ms then 0ms, twice). Arrival time is the only
        clock available for every event, and it is what a replay is
        reconstructing anyway.
        """
        nonlocal t0, last_t_ms
        if t0 is None:
            t0 = arrived
        t_ms = max(0, int((arrived - t0) * 1000))
        # Monotonic by construction above; clamped anyway so a fixture can
        # never carry a backward step to the replayer.
        t_ms = max(t_ms, last_t_ms)
        last_t_ms = t_ms
        return t_ms

    with api_request(
        "POST",
        f"/api/v1/sessions/{session_id}/turns",
        {"input": [{"type": "user.message", "content": prompt}]},
        accept_sse=True,
    ) as stream:
        with out_path.open("w", encoding="utf-8") as handle:
            for event, arrived in iter_sse_events(stream):
                record = {"t_ms": event_t_ms(arrived), **redact_value(event)}
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                event_type = record.get("type", "unknown")
                event_types.append(event_type)
                print(f"  [{record['t_ms']:5d}ms] {event_type}", file=sys.stderr)
                if event_type == "turn.done":
                    break

    return event_types


def main() -> int:
    parser = argparse.ArgumentParser(description="Record a TrueForge turn to JSONL.")
    parser.add_argument(
        "--agent", default="conductor", help="Agent name (default: conductor)"
    )
    parser.add_argument("--prompt", required=True, help="User message for the turn")
    parser.add_argument("--out", type=Path, required=True, help="Output JSONL path")
    args = parser.parse_args()

    assert_loopback(BASE)
    print(f"recording {args.agent!r} -> {args.out}", file=sys.stderr)
    event_types = record_turn(args.agent, args.prompt, args.out)
    print(f"wrote {len(event_types)} events to {args.out}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
