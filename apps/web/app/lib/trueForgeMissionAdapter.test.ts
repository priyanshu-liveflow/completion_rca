import { describe, expect, it } from "vitest";
import {
  createTrueForgeMissionAdapter,
  TrueForgeMissionAdapter,
} from "./trueForgeMissionAdapter";
import { TrueForgeTransport, TrueForgeTurnInput } from "./trueForgeTransport";
import { MissionEvent } from "./types";

function createDeferred<T>(): {
  promise: Promise<T>;
  resolve: (value: T) => void;
  reject: (reason?: unknown) => void;
} {
  let resolve: (value: T) => void = () => {};
  let reject: (reason?: unknown) => void = () => {};
  const promise = new Promise<T>((res, rej) => {
    resolve = res;
    reject = rej;
  });
  return { promise, resolve, reject };
}

interface FakeTransportOptions {
  sessionId?: string;
  createSessionDelay?: boolean;
  createSessionError?: Error;
  chunks?: string[];
  turnError?: Error;
}

function createFakeTransport(
  options: FakeTransportOptions = {}
): TrueForgeTransport & { chunks: string[] } {
  const sessionId = options.sessionId ?? "session-1";
  const createSessionDeferred = createDeferred<string>();

  const transport = {
    chunks: options.chunks ?? [],
    createSession: () => {
      if (options.createSessionError) {
        return Promise.reject(options.createSessionError);
      }
      if (options.createSessionDelay) {
        return createSessionDeferred.promise;
      }
      return Promise.resolve(sessionId);
    },
    getSessionId: () => sessionId,
    startTurn: async (
      _input: TrueForgeTurnInput[] | undefined,
      onChunk: (chunk: string) => void,
      _signal?: AbortSignal
    ) => {
      if (options.turnError) {
        throw options.turnError;
      }
      for (const chunk of options.chunks ?? []) {
        if (_signal?.aborted) throw new DOMException("Aborted", "AbortError");
        onChunk(chunk);
      }
    },
  } as unknown as TrueForgeTransport & { chunks: string[] };

  return Object.assign(transport, {
    resolveSession: createSessionDeferred.resolve,
  });
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

async function flushMicrotasks(): Promise<void> {
  await Promise.resolve();
  await Promise.resolve();
}

describe("TrueForgeMissionAdapter", () => {
  it("exposes mode: live and no resolveApproval", () => {
    const adapter = new TrueForgeMissionAdapter(
      createFakeTransport() as unknown as TrueForgeTransport
    );
    expect(adapter.mode).toBe("live");
    expect("resolveApproval" in adapter).toBe(false);
  });

  it("emits a connected runtime lifecycle for a no-event turn", async () => {
    const transport = createFakeTransport();
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();

    expect(events.some((e) => e.type === "runtime.connecting")).toBe(true);
    expect(events.some((e) => e.type === "runtime.connected")).toBe(true);
  });

  it("emits a sandbox connected event when sandbox.created is streamed", async () => {
    const chunk = `event: sandbox.created\ndata: {"sandbox_id": "sxn-live"}\n\nevent: turn.done\ndata: done\n\n`;
    const transport = createFakeTransport({ chunks: [chunk] });
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();

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
    const transport = createFakeTransport({ chunks: [chunk] });
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();

    const red = events.find((e) => e.type === "tests.red_observed");
    const greenEvent = events.find((e) => e.type === "tests.green_observed");
    expect(red).toBeDefined();
    expect(greenEvent).toBeDefined();
  });

  it("aborts before createSession resolves and emits no later event", async () => {
    const transport = createFakeTransport({ createSessionDelay: true });
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    const unsubscribe = adapter.subscribe((event) => events.push(event));
    unsubscribe();
    (
      transport as unknown as { resolveSession: (id: string) => void }
    ).resolveSession("session-2");
    await flushMicrotasks();

    expect(events.some((e) => e.type === "runtime.connected")).toBe(false);
  });

  it("starts only the final session after rapid subscribe/unsubscribe/subscribe", async () => {
    const transport = createFakeTransport();
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    const unsub1 = adapter.subscribe((event) => events.push(event));
    const unsub2 = adapter.subscribe((event) => events.push(event));
    unsub1();
    const unsub3 = adapter.subscribe((event) => events.push(event));
    unsub2();
    await flushMicrotasks();

    expect(events.filter((e) => e.type === "runtime.connected").length).toBe(
      1
    );
    unsub3();
  });

  it("does not emit runtime.failed for a cleanup AbortError", async () => {
    const transport = createFakeTransport();
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    const unsubscribe = adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();
    unsubscribe();
    await flushMicrotasks();

    expect(events.some((e) => e.type === "runtime.failed")).toBe(false);
  });

  it("emits trailing SSE data through parser.end()", async () => {
    const partial = `event: sandbox.created\ndata: {"sandbox_id": "sxn-tail"}`;
    const transport = createFakeTransport({ chunks: [partial] });
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();

    expect(events.some((e) => e.type === "sandbox.connected")).toBe(true);
  });

  it("surfaces a 503 as a failed runtime with the upstream message", async () => {
    const transport = createFakeTransport({
      createSessionError: new Error(
        "Failed to create session: 503 Service Unavailable"
      ),
    });
    const adapter = createTrueForgeMissionAdapter(
      transport as unknown as TrueForgeTransport
    );
    const events: MissionEvent[] = [];

    adapter.subscribe((event) => events.push(event));
    await flushMicrotasks();

    const failed = events.find((e) => e.type === "runtime.failed");
    expect(failed).toBeDefined();
    expect((failed as { message: string }).message).toMatch(/503/);
  });
});
