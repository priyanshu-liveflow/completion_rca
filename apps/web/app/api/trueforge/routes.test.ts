import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import { POST as createSession } from "./sessions/route";
import { POST as startTurn } from "./sessions/[sessionId]/turns/route";

beforeEach(() => {
  vi.stubGlobal(
    "fetch",
    vi.fn()
  );
});

afterEach(() => {
  vi.unstubAllGlobals();
});

function mockFetchReturn(value: unknown): void {
  (fetch as ReturnType<typeof vi.fn>).mockResolvedValue(value);
}

function createJsonRequest(
  url: string,
  method: "POST" | "GET",
  body?: object
): Request {
  return new Request(url, {
    method,
    body: body ? JSON.stringify(body) : undefined,
    headers: { "Content-Type": "application/json" },
  });
}

async function readJson(response: Response): Promise<unknown> {
  return response.json();
}

describe("/api/trueforge/sessions", () => {
  it("defaults missing agent name to conductor", async () => {
    mockFetchReturn(
      new Response(JSON.stringify({ id: "s-1" }), { status: 200 })
    );

    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions",
      "POST",
      {}
    );
    await createSession(request);

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining("/api/v1/sessions"),
      expect.objectContaining({
        body: JSON.stringify({ agent: { name: "conductor" } }),
      })
    );
  });

  it("preserves upstream non-2xx status", async () => {
    mockFetchReturn(
      new Response(JSON.stringify({ error: "unavailable" }), { status: 503 })
    );

    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions",
      "POST",
      { agent: { name: "conductor" } }
    );
    const response = await createSession(request);

    expect(response.status).toBe(503);
    const body = (await readJson(response)) as { error?: string };
    expect(body.error).toBe("Failed to create TrueForge session");
  });

  it("does not leak credentials or stack traces", async () => {
    mockFetchReturn(
      new Response(
        JSON.stringify({
          error: "unavailable",
          stack: "at /super/secret/path",
        }),
        { status: 500 }
      )
    );

    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions",
      "POST",
      {}
    );
    const response = await createSession(request);
    const text = await response.text();

    expect(text).not.toContain("secret");
    expect(text).not.toMatch(/(nvapi-|dtn_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]+/);
    expect(text).not.toContain("stack");
  });
});

describe("/api/trueforge/sessions/[sessionId]/turns", () => {
  it("rejects an empty input array", async () => {
    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions/s-1/turns",
      "POST",
      { input: [] }
    );
    const response = await startTurn(request, {
      params: Promise.resolve({ sessionId: "s-1" }),
    });

    expect(response.status).toBe(400);
    const body = (await readJson(response)) as { error?: string };
    expect(body.error).toMatch(/non-empty input array/);
  });

  it("rejects an invalid input type", async () => {
    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions/s-1/turns",
      "POST",
      { input: [{ type: "unknown.type" }] }
    );
    const response = await startTurn(request, {
      params: Promise.resolve({ sessionId: "s-1" }),
    });

    expect(response.status).toBe(400);
    const body = (await readJson(response)) as { error?: string };
    expect(body.error).toMatch(/non-empty input array/);
  });

  it("preserves upstream non-2xx status", async () => {
    mockFetchReturn(
      new Response(JSON.stringify({ error: "busy" }), { status: 503 })
    );

    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions/s-1/turns",
      "POST",
      { input: [{ type: "user.message", content: "hello" }] }
    );
    const response = await startTurn(request, {
      params: Promise.resolve({ sessionId: "s-1" }),
    });

    expect(response.status).toBe(503);
    const body = (await readJson(response)) as { error?: string };
    expect(body.error).toBe("Failed to start TrueForge turn");
  });

  it("returns SSE headers and no cache on a streaming response", async () => {
    const text = "data: ok\n\n";
    const stream = new ReadableStream({
      start(controller) {
        controller.enqueue(new TextEncoder().encode(text));
        controller.close();
      },
    });
    mockFetchReturn(
      new Response(stream, {
        status: 200,
        headers: { "Content-Type": "text/event-stream" },
      })
    );

    const request = createJsonRequest(
      "http://localhost/api/trueforge/sessions/s-1/turns",
      "POST",
      { input: [{ type: "user.message", content: "hello" }] }
    );
    const response = await startTurn(request, {
      params: Promise.resolve({ sessionId: "s-1" }),
    });

    expect(response.status).toBe(200);
    expect(response.headers.get("Content-Type")).toBe("text/event-stream");
    expect(response.headers.get("Cache-Control")).toBe("no-cache");
    expect(response.headers.get("Connection")).toBe("keep-alive");
    const body = await response.text();
    expect(body).toContain("data: ok");
    expect(body).not.toMatch(/(nvapi-|dtn_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]+/);
  });
});
