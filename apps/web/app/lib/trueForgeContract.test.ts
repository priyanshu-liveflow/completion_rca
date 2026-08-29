import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { SseParser } from "./sseParser";

const fixturePath = resolve(
  import.meta.dirname,
  "fixtures/trueforge/conductor-red-green.sse",
);

function capturedMessages() {
  const parser = new SseParser();
  parser.append(readFileSync(fixturePath, "utf8"));
  return parser.end();
}

describe("captured TrueForge conductor contract", () => {
  it("contains the lifecycle events observed in the no-write turn", () => {
    const messages = capturedMessages();
    const names = messages.map((message) => {
      try {
        return JSON.parse(message.data).type as string;
      } catch {
        return message.event;
      }
    });
    expect(names).toContain("turn.created");
    expect(names).toContain("model.message");
    expect(names).toContain("model.message.delta");
    expect(names).toContain("tool.response_required");
    expect(names).toContain("turn.done");
  });

  it("contains no credential-shaped value", () => {
    const raw = readFileSync(fixturePath, "utf8");
    expect(raw).not.toMatch(
      /(nvapi-|dtn_|ghp_|github_pat_|sk-)[A-Za-z0-9_-]+/,
    );
    expect(raw).not.toContain("api_key");
  });
});
