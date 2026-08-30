/**
 * Narrow type guards for TrueForge JSON envelopes observed and documented for
 * the conductor agent. These are the only event names, tool names, and session
 * shapes the live translator treats as valid.
 */

export const TRUEFORGE_EVENTS = [
  "turn.created",
  "turn.done",
  "thread.created",
  "thread.done",
  "model.message",
  "model.message.delta",
  "model.message.done",
  "tool.response",
  "tool.approval_required",
  "sandbox.created",
] as const;

export type TrueForgeEventName = (typeof TRUEFORGE_EVENTS)[number];

export function isTrueForgeEventName(value: string): value is TrueForgeEventName {
  return (TRUEFORGE_EVENTS as readonly string[]).includes(value);
}

export const TRUEFORGE_TOOLS = [
  "save_impact",
  "save_selection",
  "save_report",
  "save_verify",
  "save_patch",
  "run_collector",
  "run_tests",
  "apply_patch",
  "set_package_version",
  "github_open_pr",
  "github_open_issue",
] as const;

export type TrueForgeToolName = (typeof TRUEFORGE_TOOLS)[number];

export function isKnownTrueForgeTool(value: string): value is TrueForgeToolName {
  return (TRUEFORGE_TOOLS as readonly string[]).includes(value);
}

export interface TrueForgeSessionResponse {
  id: string;
  agent?: { name: string };
  created_at?: string;
}

export interface TrueForgeToolCall {
  id?: string;
  name: string;
  input?: Record<string, unknown>;
}

export interface TrueForgeToolResponse {
  tool: string;
  success: boolean;
  response?: unknown;
  error?: string;
}

export interface TrueForgeApprovalRequired {
  request_id: string;
  tool: string;
  summary: string;
  args: unknown;
}

export interface TrueForgeSandboxCreated {
  sandbox_id: string;
  type: string;
}

/**
 * TrueForge wraps every REST payload in `{ data: ... }`, so a session create
 * answers `{"data":{"id":"01m18..."}}` — the id is never at the top level.
 * The proxy passes the body through verbatim, so this guard sees the envelope
 * and `createSession` threw "Invalid session response" on every well-formed
 * response. Both shapes are accepted: unwrapped in case a future proxy strips
 * the envelope, wrapped because that is what the harness actually sends.
 */
export function isTrueForgeSessionResponse(value: unknown): value is TrueForgeSessionResponse {
  return readSessionId(value) !== null;
}

export function readSessionId(value: unknown): string | null {
  if (typeof value !== "object" || value === null) {
    return null;
  }
  const direct = (value as { id?: unknown }).id;
  if (typeof direct === "string" && direct.length > 0) {
    return direct;
  }
  const wrapped = (value as { data?: { id?: unknown } }).data;
  if (typeof wrapped === "object" && wrapped !== null) {
    const nested = (wrapped as { id?: unknown }).id;
    if (typeof nested === "string" && nested.length > 0) {
      return nested;
    }
  }
  return null;
}

export function isTrueForgeToolResponse(value: unknown): value is TrueForgeToolResponse {
  return (
    typeof value === "object" &&
    value !== null &&
    "tool" in value &&
    typeof (value as { tool: unknown }).tool === "string"
  );
}

export function isTrueForgeApprovalRequired(value: unknown): value is TrueForgeApprovalRequired {
  return (
    typeof value === "object" &&
    value !== null &&
    "request_id" in value &&
    typeof (value as { request_id: unknown }).request_id === "string" &&
    "tool" in value &&
    typeof (value as { tool: unknown }).tool === "string"
  );
}

export function isTrueForgeSandboxCreated(value: unknown): value is TrueForgeSandboxCreated {
  return (
    typeof value === "object" &&
    value !== null &&
    "sandbox_id" in value &&
    typeof (value as { sandbox_id: unknown }).sandbox_id === "string"
  );
}

export interface TrueForgeTestReport {
  id: string;
  package: string;
  version: string;
  cases: Array<{
    node_id: string;
    outcome: "passed" | "failed" | "error" | "skipped";
  }>;
  passed: number;
  failed: number;
  errors: number;
  duration_s: number;
  raw_tail: string;
}

export interface TrueForgeMissionSnapshot {
  id: string;
  state: string;
  release: { dependency: string; version: string };
  impact_rows: unknown[];
  selection: { tests: string[]; strategy: string; reached_from: string[] } | null;
  reports: TrueForgeTestReport[];
  verify: {
    patch: { diff: string; files: string[]; rationale: string };
    before: TrueForgeTestReport;
    after: TrueForgeTestReport;
    verified: boolean;
  } | null;
}

export function isTrueForgeMissionSnapshot(value: unknown): value is TrueForgeMissionSnapshot {
  const v = value as TrueForgeMissionSnapshot | null;
  return (
    typeof v === "object" &&
    v !== null &&
    typeof (v as { id: unknown }).id === "string" &&
    Array.isArray((v as { reports: unknown }).reports) &&
    (v as { verify: unknown }).verify !== undefined
  );
}
