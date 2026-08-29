# TrueForge — the real API surface

Probed against `npx @truefoundry/trueforge@latest` running locally on
`localhost:8790`. Everything here was observed, not read from docs. Where it
contradicts `PLAN.md` or an earlier draft, this file wins.

Zod validation errors leak the schema, so `POST` with `{}` and read the
complaint. That is how every shape below was recovered.

## Routes

| Route | Methods | Notes |
|---|---|---|
| `/api/v1/agents` | GET, POST | the agent manifest |
| `/api/v1/models` | GET | **read-only** — models come from provider config |
| `/api/v1/mcp-servers` | GET, … | |
| `/api/v1/skills` | GET, … | |
| `/api/v1/sessions` | GET, … | paginated, `limit` 25 |
| `/api/v1/catalogs/model-providers` | GET | what provider types exist, and their models |
| `/api/v1/catalogs/sandbox-providers` | GET | daytona only, **with the defaults** |
| `/api/v1/settings/model-providers` | GET, POST | register a provider |
| `/api/v1/settings/sandbox-providers` | GET, **PUT** | not POST — PUT |

There is no `/sandboxes` route. Sandbox config is global, under settings, and
the agent opts in through `manifest.config`.

## Agent manifest

```jsonc
POST /api/v1/agents
{
  "name": "conductor",
  "manifest": {
    "model": { "name": "provider/model" },   // OBJECT, not a string
    "instructions": "...",
    "mcp_servers": [],
    "skills": [],
    "config": {}
  }
}
```

**`manifest.model` is an object, and `model.name` must be fully qualified as
`provider/model`.** Earlier drafts of the plan had `model` as a bare string —
that is wrong and `seed.ts` must not do it. A short name fails with
`Model name must be a fully qualified "provider/model"`.

## Model providers

```jsonc
POST /api/v1/settings/model-providers
{ "manifest": { "type": "...", "name": "...", "base_url": "...", "models": [] } }
```

`type` is one of `openai · anthropic · google-gemini · fireworks · zai ·
moonshot · together · alibaba · custom`.

**There is no `nvidia` type.** NVIDIA NIM goes in as `custom` with
`base_url: https://integrate.api.nvidia.com/v1`, which is the OpenAI-compatible
escape hatch.

Worth knowing: **`zai` carries `glm-5.2` natively**, and `fireworks` carries
`glm-5p2`. If NIM credits run dry, either is a one-line provider swap rather
than a code change.

## Sandbox provider

```jsonc
PUT /api/v1/settings/sandbox-providers
{
  "manifest": {
    "type": "daytona",
    "auth": { "api_key": "dtn_..." },
    "exec_timeout_ms": 300000,
    "auto_stop_interval_in_minutes": 120,
    "auto_archive_interval_in_minutes": 10080,
    "auto_delete_interval_in_minutes": 20160
  }
}
```

Confirms the plan's read: Daytona only, and **no image or snapshot field**. A
pre-baked image is not expressible here, which is why `sandbox/Dockerfile` was
cut in favour of the measured 10.1s cold path.

### The default that would have bitten us

`/api/v1/catalogs/sandbox-providers` reports the defaults:

```json
{"type":"daytona","exec_timeout_ms":60000,
 "auto_stop_interval_in_minutes":5,
 "auto_archive_interval_in_minutes":60,
 "auto_delete_interval_in_minutes":7200}
```

**`auto_stop_interval_in_minutes` defaults to 5.** A "prewarmed" sandbox dies
after five idle minutes — shorter than the wait before a demo slot. Set it
explicitly, as above. Cold recovery is 10.1s, so this is survivable rather than
fatal, but there is no reason to eat it.

`exec_timeout_ms` also defaults to 60s. Our cold path is 10s and our live path
is 6s, so the default would hold — but `pip install` on a colder day would not.
300000 gives room.

## The misleading error worth remembering

TrueForge validates the Daytona key by calling the API, and:

```js
isDaytonaAuthError(error) {
  return error instanceof DaytonaError && (error.statusCode === 401 || error.statusCode === 403)
}
```

Any **401 or 403** surfaces as `Daytona rejected the API key — check the
credentials`. A 403 from a *missing scope* is indistinguishable from a wrong
key.

Observed on our key: `sandbox.create` and `snapshot.list` succeed,
`volume.list` returns **403**. The credential is valid; it is under-scoped.
**Regenerate the Daytona key with all scopes enabled** rather than hunting a
credential problem that does not exist.

## What this means for PR10

1. `seed.ts` writes `model: { name: "provider/model" }`, never a bare string.
2. Provider registration is a prerequisite, not part of the agent manifest — an
   agent referencing an unconfigured provider is rejected at create time with
   `Unknown model "..." — provider not configured`.
3. Sandbox settings are global and use **PUT**. Set `auto_stop` to 120 there,
   not in the agent.
4. NVIDIA NIM is `type: custom`. Keep `zai` in your back pocket for glm-5.2.
