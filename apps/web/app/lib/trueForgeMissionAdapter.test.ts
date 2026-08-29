import { describe, expect, it } from "vitest";
import {
  createTrueForgeMissionAdapter,
  TrueForgeMissionAdapter,
} from "./trueForgeMissionAdapter";
import { TrueForgeTransport, TrueForgeTurnInput } from "./trueForgeTransport";
import { MissionEvent } from "./types";

function createFakeTransport(
  chunks: string[] = []
): TrueForgeTransport & { chunks: string[] } {
  const sessionId = "session-1";
  return {
    chunks,
    createSession: () => Promise.resolve(sessionId),
    getSessionId: () => sessionId,
    startTurn: async (
      _input: TrueForgeTurnInput[] | undefined,
      onChunk: (chunk: string) => void
    ) => {
      for (const chunk of chunks) {
        onChunk(chunk);
      }
    },
    resolveApproval: () => Promise.resolve(),
  } as unknown as TrueForgeTransport & { chunks: string[] };
}

function missionSnapshot(
  id: string,
  reports: unknown[],
  verify: unknown
): string {
  return JSON.stringify({
    id,
    state: "running",
    release: { dependency: "mcp[cli]", version: "2.1.1" },
    impact_rows: [],
    selection: {
      tests: ["tests/test_x.py"],
      strategy: "import",
      reached_from: [],
    },
    reports,
    verify,
  });
}

const brokenReport = {
  id: "r-red",
  package: "mcp",
  version: "2.1.1",
  cases: [{ node_id: "tests/test_x.py::test_1", outcome: "error" }],
  passed: 0,
  failed: 0,
  errors: 1,
  duration_s: 0.1,
  raw_tail: "ImportError: cannot import name FastMCP",
};

const greenReport = {
  id: "r-green",
  package: "mcp",
  version: "2.1.1",
  cases: [{ node_id: "tests/test_x.py::test_1", outcome: "passed" }],
  passed: 1,
  failed: 0,
  errors: 0,
  duration_s: 0.2,
  raw_tail: "ok",
};

describe("TrueForgeMissionAdapter", () => {
  it("emits a connected runtime lifecycle for a no-event turn", async () => {
    const transport = createFakeTransport([]);
    const adapter = createTrueForgeMissionAdapter(transport);
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));

    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(events.some((e) => e.type === "runtime.connecting")).toBe(true);
    expect(events.some((e) => e.type === "runtime.connected")).toBe(true);
  });

  it("emits a sandbox connected event when sandbox.created is streamed", async () => {
    const chunk = `event: sandbox.created\ndata: {"sandbox_id": "sxn-live"}\n\nevent: turn.done\ndata: done\n\n`;
    const transport = createFakeTransport([chunk]);
    const adapter = createTrueForgeMissionAdapter(transport);
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));

    await new Promise((resolve) => setTimeout(resolve, 10));

    expect(events.some((e) => e.type === "sandbox.connected")).toBe(true);
    expect(
      events.find((e) => e.type === "sandbox.connected")
    ).toMatchObject({
      sandboxId: "sxn-live",
    });
    expect(events.some((e) => e.type === "runtime.turn.completed")).toBe(true);
  });

  it("emits red and green test events from structured mission snapshots", async () => {
    const broken = missionSnapshot("m-1", [brokenReport], null);
    const green = missionSnapshot(
      "m-1",
      [brokenReport, greenReport],
      {
        patch: { diff: "...", files: ["src/mcp.py"], rationale: "..." },
        before: brokenReport,
        after: greenReport,
        verified: true,
      }
    );
    const chunk = `event: sandbox.created\ndata: {"sandbox_id": "sxn-live"}\n\nevent: tool.response\ndata: ${broken}\n\nevent: tool.response\ndata: ${green}\n\n`;
    const transport = createFakeTransport([chunk]);
    const adapter = createTrueForgeMissionAdapter(transport);
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));

    await new Promise((resolve) => setTimeout(resolve, 10));

    const red = events.find((e) => e.type === "tests.red_observed");
    const greenEvent = events.find((e) => e.type === "tests.green_observed");
    expect(red).toBeDefined();
    expect(greenEvent).toBeDefined();
  });

  it("exposes mode: live", () => {
    const transport = createFakeTransport([]);
    const adapter = new TrueForgeMissionAdapter(transport);
    expect(adapter.mode).toBe("live");
  });
});
