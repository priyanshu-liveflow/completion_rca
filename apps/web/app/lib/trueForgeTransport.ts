import { demoMissionInput } from "./demoMission";
import { isTrueForgeSessionResponse } from "./trueForgeTypes";

export interface TrueForgeTurnInput {
  type: string;
  content?: string;
  tool_approval?: { request_id: string; decision: "approve" | "deny" };
}

/**
 * Browser transport for the TrueForge demo session.
 *
 * All live calls are proxied through `/api/trueforge/...` to avoid exposing
 * harness credentials to the frontend.
 */
export class TrueForgeTransport {
  private sessionId: string | null = null;

  constructor(private apiBase = "/api/trueforge") {}

  async createSession(signal?: AbortSignal): Promise<string> {
    const response = await fetch(`${this.apiBase}/sessions`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ agent: { name: "conductor" } }),
      signal,
    });

    if (!response.ok) {
      throw new Error(
        `Failed to create session: ${response.status} ${response.statusText}`
      );
    }

    const body = (await response.json()) as unknown;
    if (!isTrueForgeSessionResponse(body)) {
      throw new Error("Invalid session response from TrueForge");
    }

    this.sessionId = body.id;
    return body.id;
  }

  getSessionId(): string | null {
    return this.sessionId;
  }

  async startTurn(
    input: TrueForgeTurnInput[] = demoMissionInput,
    onChunk: (chunk: string) => void,
    signal?: AbortSignal
  ): Promise<void> {
    if (!this.sessionId) {
      throw new Error("No active session; call createSession() first");
    }

    const response = await fetch(
      `${this.apiBase}/sessions/${this.sessionId}/turns`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ input }),
        signal,
      }
    );

    if (!response.ok) {
      throw new Error(
        `Failed to start turn: ${response.status} ${response.statusText}`
      );
    }

    if (!response.body) {
      throw new Error("No response body");
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();

    try {
      while (true) {
        const { done, value } = await reader.read();
        if (done) {
          const trailing = decoder.decode();
          if (trailing) onChunk(trailing);
          break;
        }
        onChunk(decoder.decode(value, { stream: true }));
      }
    } finally {
      reader.releaseLock();
    }
  }
}
