#!/usr/bin/env node
/**
 * Seed the AgentRadar conductor into a local TrueForge instance.
 *
 * Idempotent — safe to run any number of times. Concatenates
 * `agents/prompts/*.md` (filename order) into the manifest's `instructions`,
 * compiles `actions/policy.yaml` into `require_approval_for_tools`, registers
 * the three MCP servers, then creates or updates the `conductor` agent.
 *
 * No TrueForge SDK here on purpose. `@truefoundry/trueforge` and
 * `@truefoundry/trueforge-core` are the harness ENGINE — the thing
 * `npx @truefoundry/trueforge` runs — not a client library for talking to a
 * running one. Pulling either in as a dependency of a seed script would drag
 * in postgres, redis, and the Daytona SDK for zero benefit. This is a thin
 * fetch-based client instead, the same shape as `scripts/configure_trueforge.py`.
 *
 *     npx tsx agents/seed.ts
 *
 * Reads TRUEFORGE_URL from the environment, defaulting to localhost:8790.
 */

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { parse as parseYaml } from "yaml";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, "..");
const BASE_URL = process.env.TRUEFORGE_URL ?? "http://localhost:8790";

interface McpServerSpec {
  name: string;
  url: string;
  description: string;
}

interface ConductorManifest {
  name: string;
  model: { name: string };
  mcp_servers: McpServerSpec[];
  skills: unknown[];
  config: Record<string, unknown>;
}

interface PolicyTarget {
  approval: "required" | "none";
  description?: string;
}

interface Policy {
  targets: Record<string, PolicyTarget>;
}

interface ApiResult {
  status: number;
  json: any;
}

async function api(method: string, path: string, body?: unknown): Promise<ApiResult> {
  const res = await fetch(`${BASE_URL}${path}`, {
    method,
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const text = await res.text();
  let json: any = {};
  if (text) {
    try {
      json = JSON.parse(text);
    } catch {
      json = { raw: text };
    }
  }
  return { status: res.status, json };
}

function errorMessage(json: any): string {
  return json?.error?.message ?? JSON.stringify(json);
}

/** Concatenate agents/prompts/*.md in filename order into one instructions string. */
function loadInstructions(): string {
  const dir = join(HERE, "prompts");
  const files = readdirSync(dir)
    .filter((f) => f.endsWith(".md"))
    .sort();
  if (files.length === 0) {
    throw new Error(`no prompt files found in ${dir}`);
  }
  return (
    files.map((f) => readFileSync(join(dir, f), "utf8").trimEnd()).join("\n\n---\n\n") + "\n"
  );
}

const APPROVAL_VALUES = ["required", "none"] as const;

/**
 * Load and validate the approval policy, failing closed.
 *
 * `parseYaml(...) as Policy` is a compile-time cast and checks nothing at
 * runtime, so before this validation a typo (`requried`), a missing
 * `approval` key, or a null value did not throw — it simply was not equal to
 * `"required"`, so the target silently compiled to *ungated* and seeding
 * reported success. The one file in the repo whose whole job is to make a
 * human approve a write would have quietly removed that approval. Anything
 * this loader cannot read as exactly `required` or `none` aborts the seed.
 */
function loadPolicy(): Policy {
  const text = readFileSync(join(ROOT, "actions", "policy.yaml"), "utf8");
  const policy = parseYaml(text) as Policy;
  if (!policy?.targets || typeof policy.targets !== "object") {
    throw new Error("actions/policy.yaml has no `targets` map");
  }

  const entries = Object.entries(policy.targets);
  if (entries.length === 0) {
    throw new Error("actions/policy.yaml `targets` is empty");
  }

  for (const [name, spec] of entries) {
    const approval = spec?.approval;
    if (!APPROVAL_VALUES.includes(approval as (typeof APPROVAL_VALUES)[number])) {
      throw new Error(
        `actions/policy.yaml: target ${JSON.stringify(name)} has approval ` +
          `${JSON.stringify(approval)}; expected one of ` +
          `${APPROVAL_VALUES.map((v) => JSON.stringify(v)).join(" or ")}. ` +
          "Refusing to seed: an unreadable approval value would compile to " +
          "an ungated write.",
      );
    }
  }

  return policy;
}

/** Action targets whose policy says `approval: required`, sorted for determinism. */
function approvalToolNames(policy: Policy): string[] {
  return Object.entries(policy.targets)
    .filter(([, spec]) => spec.approval === "required")
    .map(([name]) => name)
    .sort();
}

/**
 * Register one MCP server. PUT is an upsert keyed by name — confirmed by
 * probing the running instance, calling this twice with the same name is a
 * no-op, not an error or a duplicate.
 */
async function ensureMcpServer(server: McpServerSpec): Promise<void> {
  const { status, json } = await api("PUT", "/api/v1/settings/mcp-servers", {
    manifest: {
      type: "remote",
      name: server.name,
      url: server.url,
      description: server.description,
    },
  });
  if (status >= 300) {
    throw new Error(`mcp-server ${server.name}: ${status} ${errorMessage(json)}`);
  }
  console.log(`mcp server   ${server.name.padEnd(8)} registered @ ${server.url}`);
}

/**
 * Find an existing agent by exact name.
 *
 * `GET /api/v1/agents` ignores `name` and `limit` query parameters in this
 * build — confirmed by probing: passing either returns the same full list
 * regardless. So this fetches everything and matches client-side rather than
 * trusting a server-side filter that does not exist.
 */
async function findExistingAgent(name: string): Promise<{ id: string } | null> {
  const { status, json } = await api("GET", "/api/v1/agents");
  if (status >= 300) {
    throw new Error(`list agents: ${status} ${errorMessage(json)}`);
  }
  const rows: { id: string; name: string }[] = json.data ?? [];
  return rows.find((row) => row.name === name) ?? null;
}

/**
 * Rough token estimate, chars/4. No tokenizer dependency on purpose — the
 * models behind this agent are NIM-hosted (kimi/deepseek/llama), not the
 * family any popular JS tokenizer targets, and pulling in a ~20MB rank table
 * for one approximate number contradicts "keep agents/package.json minimal."
 * Printed labeled as an approximation, never as an exact count.
 */
function estimateTokens(text: string): number {
  return Math.ceil(text.length / 4);
}

async function main(): Promise<void> {
  const manifestPath = join(HERE, "conductor.json");
  const base: ConductorManifest = JSON.parse(readFileSync(manifestPath, "utf8"));

  const instructions = loadInstructions();
  const policy = loadPolicy();
  const approvalTools = approvalToolNames(policy);
  const tokenEstimate = estimateTokens(instructions);

  console.log(`TrueForge    ${BASE_URL}`);
  console.log(
    `instructions ${instructions.length} chars, ~${tokenEstimate} tokens (approx, chars/4)`
  );
  console.log(`approval-gated action targets: ${approvalTools.join(", ") || "(none)"}`);
  console.log();

  for (const server of base.mcp_servers) {
    await ensureMcpServer(server);
  }

  // The agent's own mcp_servers entries are references by name, not full
  // registration payloads — url/description belong only in the settings
  // registration above. require_approval_for_tools is per-server (there is
  // no top-level manifest field for it; a bare top-level key is silently
  // dropped by this build, per agents/README.md), so the compiled policy is
  // applied identically to every server the conductor has.
  const mcpServerRefs = base.mcp_servers.map((server) => {
    const ref: { name: string; require_approval_for_tools?: string[] } = {
      name: server.name,
    };
    if (approvalTools.length > 0) {
      ref.require_approval_for_tools = approvalTools;
    }
    return ref;
  });

  const manifest = {
    model: base.model,
    instructions,
    mcp_servers: mcpServerRefs,
    skills: base.skills,
    config: base.config,
  };

  const existing = await findExistingAgent(base.name);
  if (existing) {
    const { status, json } = await api("PUT", `/api/v1/agents/${existing.id}`, { manifest });
    if (status >= 300) {
      throw new Error(`update agent: ${status} ${errorMessage(json)}`);
    }
    console.log(`agent        ${base.name} updated (${existing.id})`);
  } else {
    const { status, json } = await api("POST", "/api/v1/agents", { name: base.name, manifest });
    if (status >= 300) {
      throw new Error(`create agent: ${status} ${errorMessage(json)}`);
    }
    console.log(`agent        ${base.name} created (${json.data?.id})`);
  }
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exitCode = 1;
});
