import {
  TRUEFORGE_ORIGIN,
  normalizeSessionPayload,
  trueForgeJsonResponse,
} from "../_shared";

export async function POST(request: Request): Promise<Response> {
  const body = await request.json().catch(() => ({}));
  const payload = normalizeSessionPayload(body);

  const response = await fetch(`${TRUEFORGE_ORIGIN}/api/v1/sessions`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    return trueForgeJsonResponse(
      { error: "Failed to create TrueForge session" },
      response.status
    );
  }

  const data = (await response.json()) as unknown;
  return trueForgeJsonResponse(data);
}
