import { describe, expect, it } from "vitest";
import { SseParser } from "./sseParser";

describe("SseParser", () => {
  it("parses a single well-formed SSE message", () => {
    const parser = new SseParser();
    parser.append("event: turn.created\ndata: {\"id\": \"t1\"}\n\n");

    const message = parser.nextMessage();
    expect(message).toEqual({
      event: "turn.created",
      data: '{"id": "t1"}',
    });
  });

  it("accumulates partial chunks until a full message is received", () => {
    const parser = new SseParser();
    parser.append("event: tool.response\n");
    parser.append("data: {\"tool\": \"run_tests\"}\n");
    parser.append("\n");

    const message = parser.nextMessage();
    expect(message?.event).toBe("tool.response");
    expect(message?.data).toBe('{"tool": "run_tests"}');
  });

  it("parses multiple messages from one chunk", () => {
    const parser = new SseParser();
    parser.append(
      "event: a\ndata: 1\n\nevent: b\ndata: 2\n\n"
    );

    expect(parser.nextMessage()).toEqual({ event: "a", data: "1" });
    expect(parser.nextMessage()).toEqual({ event: "b", data: "2" });
  });

  it("ignores comments and unknown fields", () => {
    const parser = new SseParser();
    parser.append(": comment\nunknown: value\nevent: x\ndata: y\n\n");

    const message = parser.nextMessage();
    expect(message).toEqual({ event: "x", data: "y" });
  });

  it("reconstructs multi-line data fields", () => {
    const parser = new SseParser();
    parser.append("event: model.message\ndata: line 1\ndata: line 2\n\n");

    const message = parser.nextMessage();
    expect(message?.data).toBe("line 1\nline 2");
  });

  it("flushes a trailing message on end()", () => {
    const parser = new SseParser();
    parser.append("event: turn.done\ndata: {\"status\": \"done\"}\n");

    const remaining = parser.end();
    expect(remaining).toHaveLength(1);
    expect(remaining[0].event).toBe("turn.done");
  });
});
