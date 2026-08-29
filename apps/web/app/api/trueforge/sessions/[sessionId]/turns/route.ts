import {
  TRUEFORGE_ORIGIN,
  normalizeTurnPayload,
} from "../../../_shared";

interface RouteParams {
  params: Promise<{ sessionId: string }>;
}

export async function POST(
  request: Request,
  { params }: RouteParams
): Promise<Response> {
  const { sessionId } = await params;
  const body = await request.json().catch(() => ({}));
  const normalized = normalizeTurnPayload(body);

  if (!normalized.ok) {
    return new Response(JSON.stringify({ error: normalized.message }), {
      status: 400,
      headers: { "Content-Type": "application/json" },
    });
  }

  const response = await fetch(
    `${TRUEFORGE_ORIGIN}/api/v1/sessions/${encodeURIComponent(sessionId)}/turns`,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(normalized.value),
    }
  );

  if (!response.ok) {
    return new Response(
      JSON.stringify({ error: "Failed to start TrueForge turn" }),
      {
        status: response.status,
        headers: { "Content-Type": "application/json" },
      }
    );
  }

  if (!response.body) {
    return new Response(JSON.stringify({ error: "No response body" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  return new Response(response.body, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache",
      Connection: "keep-alive",
    },
  });
}
