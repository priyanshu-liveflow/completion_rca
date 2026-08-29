export interface SseMessage {
  event: string;
  data: string;
  id?: string;
  retry?: number;
}

/**
 * Incremental Server-Sent Events (SSE) parser following the WHATWG HTML spec:
 * messages are separated by a blank line (two consecutive line terminators).
 * Field names and values are split at the first colon; unknown fields are ignored.
 */
export class SseParser {
  private buffer = "";
  private messages: SseMessage[] = [];

  append(chunk: string): void {
    this.buffer += chunk;
    this.drain();
  }

  private drain(): void {
    while (true) {
      const boundary = this.findBoundary();
      if (boundary === -1) break;

      const raw = this.buffer.slice(0, boundary);
      this.buffer = this.buffer.slice(boundary + 1);

      const message = this.parseMessage(raw);
      if (message) {
        this.messages.push(message);
      }
    }
  }

  private findBoundary(): number {
    const crlf = this.buffer.indexOf("\r\n\r\n");
    const lf = this.buffer.indexOf("\n\n");

    if (crlf === -1) return lf === -1 ? -1 : lf + 1;
    if (lf === -1) return crlf + 3;
    return Math.min(crlf + 3, lf + 1);
  }

  private parseMessage(raw: string): SseMessage | null {
    const lines = raw.split(/\r\n|\r|\n/);
    const fields: Record<string, string> = {};
    const dataLines: string[] = [];

    for (const line of lines) {
      if (line.length === 0) continue;
      if (line.startsWith(":")) continue; // comment

      const colon = line.indexOf(":");
      const name = colon === -1 ? line : line.slice(0, colon);
      const value =
        colon === -1 ? "" : line.slice(colon + 1).replace(/^ /, "");

      if (name === "data") {
        dataLines.push(value);
      } else {
        fields[name] = value;
      }
    }

    if (dataLines.length === 0 && !fields.event && !fields.id) return null;

    return {
      event: fields.event ?? "message",
      data: dataLines.join("\n"),
      id: fields.id,
      retry: fields.retry ? parseInt(fields.retry, 10) : undefined,
    };
  }

  nextMessage(): SseMessage | null {
    return this.messages.shift() ?? null;
  }

  hasPending(): boolean {
    return this.messages.length > 0;
  }

  end(): SseMessage[] {
    const trailing = this.parseMessage(this.buffer);
    if (trailing) this.messages.push(trailing);
    this.buffer = "";
    const remaining = this.messages;
    this.messages = [];
    return remaining;
  }
}
