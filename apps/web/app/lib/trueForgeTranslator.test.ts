import { describe, expect, it } from "vitest";
import { TrueForgeTranslator } from "./trueForgeTranslator";
import type { SseMessage } from "./sseParser";

function msg(event: string, data: string): SseMessage {
  return { event, data };
}

function json(data: unknown): string {
  return JSON.stringify(data);
}

describe("TrueForgeTranslator", () => {
  it("emits a turn start event on turn.created", () => {
    const translator = new TrueForgeTranslator();
    const events = translator.translate(
      msg("turn.created", json({ type: "turn.created", turn_id: "t-1" }))
    );
    expect(events).toContainEqual({
      type: "runtime.turn.started",
      turnId: "t-1",
    });
  });

  it("emits a turn completed event on turn.done", () => {
    const translator = new TrueForgeTranslator();
    const events = translator.translate(msg("turn.done", json({ type: "turn.done" })));
    expect(events).toContainEqual({ type: "runtime.turn.completed" });
  });

  it("emits a sandbox connected event on sandbox.created", () => {
    const translator = new TrueForgeTranslator();
    const events = translator.translate(
      msg(
        "sandbox.created",
        json({ type: "sandbox.created", sandbox_id: "sxn-abc", sandbox_type: "daytona" })
      )
    );
    expect(events).toContainEqual({
      type: "sandbox.connected",
      sandboxId: "sxn-abc",
    });
  });

  it("appends generic sandbox output without promoting it to evidence", () => {
    const translator = new TrueForgeTranslator();
    const events = translator.translate(
      msg(
        "tool.response",
        json({
          type: "tool.response",
          success: true,
          response: { exitCode: 0, result: "ok" },
        })
      )
    );
    expect(events.some((e) => e.type === "tests.green_observed")).toBe(false);
    expect(events.some((e) => e.type === "tests.red_observed")).toBe(false);
    expect(events.some((e) => e.type === "sandbox.line.appended")).toBe(true);
  });

  it("ignores unknown event names", () => {
    const translator = new TrueForgeTranslator();
    const events = translator.translate(msg("custom.event", json({ type: "custom.event" })));
    expect(events).toHaveLength(0);
  });
});
