"""Register the model and sandbox providers in a local TrueForge.

Idempotent. Run it after starting `npx @truefoundry/trueforge@latest`, or any
time `docs/runbook.md`'s fast check reports a provider missing.

    python scripts/configure_trueforge.py

Reads DAYTONA_API_KEY and NIM_KEY from .env. Secrets are sent to localhost and
never written to disk or logged — TrueForge redacts them in its own responses.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BASE = os.getenv("TRUEFORGE_URL", "http://localhost:8790")

# Confirmed by invoking each with a real tool definition and checking for
# tool_calls in the response body, not just a 200. See configs/runtime/nvidia.yaml.
NIM_MODELS = [
    ("moonshotai/kimi-k3", "kimi-k3", 262144),
    ("deepseek-ai/deepseek-v4-flash-0731", "deepseek-v4-flash", 131072),
    ("meta/llama-3.2-11b-vision-instruct", "llama-3-2-11b", 131072),
]

# A second provider so a NIM quota wall is a one-line model swap in
# `agents/conductor.json` rather than a dead demo. NIM's free tier answers an
# exhausted quota with a bare `429` and zero tokens in ~170ms — indistinguishable
# from rate limiting until you notice it never recovers. Optional: the script
# skips this block when OPENAI_API_KEY is absent, so nothing here is required
# to run.
# Aliases carry no dots: the model is referenced as `openai/<name>` and a dot
# reads as a version separator in some of TrueForge's parsing.
#
# `max_output_tokens` is deliberately absent from the gpt-5.x entries. Setting
# it makes TrueForge send `max_tokens`, which these models reject outright
# ("Unsupported parameter: 'max_tokens'"); they want `max_completion_tokens`.
# Omitting it lets the model default to its own 128k output ceiling.
OPENAI_MODELS = [
    # (model_id, alias, context_length, max_output_tokens or None)
    ("gpt-5.6-sol", "gpt-5-6-sol", 1_050_000, None),      # flagship reasoning
    ("gpt-5.6-terra", "gpt-5-6-terra", 1_050_000, None),  # balanced
    ("gpt-5.6-luna", "gpt-5-6-luna", 1_050_000, None),    # high volume
    ("gpt-5.4-mini", "gpt-5-4-mini", 400_000, None),      # text-heavy worker
    ("gpt-4.1", "gpt-4-1", 1_047_576, 8192),              # fallback
]


def load_env() -> dict[str, str]:
    """Parse .env without importing dotenv — this script must run anywhere."""
    env: dict[str, str] = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()
    return {**env, **{k: v for k, v in os.environ.items() if k in env or k.endswith("_KEY")}}


def call(method: str, path: str, body: dict | None = None, timeout: int = 300) -> tuple[int, dict]:
    data = json.dumps(body).encode() if body is not None else None
    request = urllib.request.Request(
        f"{BASE}{path}", data=data, method=method,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        return exc.code, json.loads(exc.read() or b"{}")
    except urllib.error.URLError as exc:
        print(f"cannot reach TrueForge at {BASE}: {exc.reason}")
        print("start it with:  npx @truefoundry/trueforge@latest")
        sys.exit(2)


def configure_models(api_key: str) -> bool:
    status, body = call("POST", "/api/v1/settings/model-providers", {
        "manifest": {
            "type": "custom",  # there is no `nvidia` provider type; custom is the
            "name": "nvidia-nim",  # OpenAI-compatible escape hatch
            "base_url": "https://integrate.api.nvidia.com/v1",
            "auth": {"api_key": api_key},
            "models": [
                {"model_id": mid, "name": name,
                 "properties": {"context_length": ctx, "max_output_tokens": 8192}}
                for mid, name, ctx in NIM_MODELS
            ],
        }
    })
    if status < 300:
        print(f"model provider   ready ({len(NIM_MODELS)} models)")
        return True
    message = body.get("error", {}).get("message", "")
    if "already exists" in message.lower() or status == 409:
        print("model provider   already configured")
        return True
    print(f"model provider   FAILED {status}: {message[:200]}")
    return False


def configure_openai(api_key: str) -> bool:
    """Register OpenAI as a second model provider.

    `type: "openai"`, NOT `type: "custom"`. This is the whole reason the
    gpt-5.6 family works. TrueForge's `buildProviderOptions` branches on the
    provider type: `"openai"` routes through the OpenAI provider, which sets
    `include: ["reasoning.encrypted_content"]` and talks to `/v1/responses`;
    anything else falls through to the openai-*compatible* provider and
    `/v1/chat/completions`. On that path every gpt-5.6 turn 400s with
    "Function tools with reasoning_effort are not supported for gpt-5.6-sol
    in /v1/chat/completions. To use function tools, use /v1/responses" — and
    since the agent always has TrueForge's built-in tools, that is every turn.
    `custom` remains correct for NVIDIA, which really is only OpenAI-shaped.

    The manifest takes no `name` key for this type; the provider is named
    `openai` by TrueForge, so models are referenced as `openai/<alias>`.

    PUT, not POST. POST only *creates* — it answers "already exists" and
    leaves the stored model list untouched, so editing `OPENAI_MODELS` and
    re-running POST would report success while changing nothing.
    """
    status, body = call("PUT", "/api/v1/settings/model-providers", {
        "manifest": {
            "type": "openai",
            "auth": {"api_key": api_key},
            "models": [
                {"model_id": mid, "name": name, "properties": (
                    {"context_length": ctx}
                    if out is None
                    else {"context_length": ctx, "max_output_tokens": out}
                )}
                for mid, name, ctx, out in OPENAI_MODELS
            ],
        }
    })
    if status < 300:
        print(f"openai provider  ready ({len(OPENAI_MODELS)} models)")
        return True
    message = body.get("error", {}).get("message", "")
    print(f"openai provider  FAILED {status}: {message[:200]}")
    return False


def configure_sandbox(api_key: str) -> bool:
    # PUT, not POST. auto_stop defaults to 5 minutes, which is shorter than the
    # wait before a demo slot — set every interval explicitly.
    status, body = call("PUT", "/api/v1/settings/sandbox-providers", {
        "manifest": {
            "type": "daytona",
            "auth": {"api_key": api_key},
            "exec_timeout_ms": 300_000,
            "auto_stop_interval_in_minutes": 120,
            "auto_archive_interval_in_minutes": 10_080,
            "auto_delete_interval_in_minutes": 20_160,
        }
    })
    if status >= 300:
        message = body.get("error", {}).get("message", "")
        print(f"sandbox provider FAILED {status}: {message[:200]}")
        if "rejected the API key" in message:
            print("  TrueForge maps any Daytona 401 OR 403 to that message, so this is")
            print("  usually a missing scope rather than a bad key. Registration calls")
            print("  buildImage(), which needs snapshot WRITE. Reissue with full access.")
        return False

    # buildImage() runs asynchronously; the provider is unusable until it lands.
    for _ in range(60):
        state = body.get("data", {}).get("status")
        if state not in {"pending", "building"}:
            break
        time.sleep(10)
        _, body = call("GET", "/api/v1/settings/sandbox-providers")
    state = body.get("data", {}).get("status")
    print(f"sandbox provider {state}"
          f"{'' if state == 'ready' else ' — ' + str(body.get('data', {}).get('status_reason'))}")
    return state == "ready"


def main() -> int:
    env = load_env()
    missing = [k for k in ("NIM_KEY", "DAYTONA_API_KEY") if not env.get(k)]
    if missing:
        print(f"missing from .env: {', '.join(missing)}")
        return 2
    ok = configure_models(env["NIM_KEY"])
    if env.get("OPENAI_API_KEY"):
        ok = configure_openai(env["OPENAI_API_KEY"]) and ok
    else:
        print("openai provider  skipped (no OPENAI_API_KEY in .env)")
    ok = configure_sandbox(env["DAYTONA_API_KEY"]) and ok
    print("\nproviders ready" if ok else "\nsomething is not ready — see above")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
