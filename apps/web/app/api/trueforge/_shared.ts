/**
 * Shared origin, validation, and normalization for the TrueForge API proxy.
 */

export const TRUEFORGE_ORIGIN = "http://[::1]:8790";

export interface SessionPayload {
  agent: { name?: string };
}

export interface TurnPayload {
  input?: unknown[];
}

type Normalized<T> =
  | { ok: true; value: T }
  | { ok: false; message: string };

const TURN_INPUT_TYPES = ["user.message", "user.tool_approval", "user.tool_response"];

export function normalizeSessionPayload(raw: unknown): { agent: { name: string } } {
  const body = raw as SessionPayload | undefined;
  const name = body?.agent?.name ?? "conductor";
  return { agent: { name } };
}

export function normalizeTurnPayload(raw: unknown): Normalized<{ input: unknown[] }> {
  const body = raw as TurnPayload | undefined;
  const input = body?.input;

  if (!Array.isArray(input) || input.length === 0) {
    return {
      ok: false,
      message: "TrueForge turn input must be a non-empty input array",
    };
  }

  if (
    input.some(
      (entry) =>
        typeof entry !== "object" ||
        entry === null ||
        !("type" in entry) ||
        typeof (entry as { type?: unknown }).type !== "string" ||
        !TURN_INPUT_TYPES.includes((entry as { type: string }).type)
    )
  ) {
    return {
      ok: false,
      message: "TrueForge turn input must be a non-empty input array",
    };
  }

  return { ok: true, value: { input } };
}

export function trueForgeJsonResponse(
  data: unknown,
  status = 200
): Response {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
