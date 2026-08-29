import { describe, expect, it, vi, beforeEach, afterEach } from "vitest";
import {
  readSandboxSnapshot,
  writeSandboxSnapshot,
  subscribeSandboxSnapshot,
  SANDBOX_SNAPSHOT_KEY,
} from "./sandboxSnapshot";
import { MissionState } from "./types";

function createStorage(): Storage {
  const store = new Map<string, string>();
  return {
    getItem: (key: string) => store.get(key) ?? null,
    setItem: (key: string, value: string) => store.set(key, value),
    removeItem: (key: string) => store.delete(key),
    clear: () => store.clear(),
    key: (index: number) => Array.from(store.keys())[index] ?? null,
    get length() {
      return store.size;
    },
  } as Storage;
}

function validState(): MissionState {
  return {
    id: "AR-024",
    repo: "mvilanova/intervals-mcp-server",
    indexedCommit: "cb1fbcac8109",
    dependency: "mcp[cli]",
    baselineVersion: "1.29.1",
    breakingVersion: "2.1.1",
    nodes: [],
    transcript: [],
    redObserved: false,
    greenObservedAfterRed: false,
    redTests: 0,
    greenTests: 0,
    redEvidence: null,
    greenEvidence: null,
    selectedNode: null,
    dockOpen: true,
    activeTab: "environment",
    popOutOpen: false,
    approved: null,
    currentTime: "—",
    restored: true,
    runtime: {
      mode: "fixture",
      status: "fixture",
      sessionId: null,
      turnId: null,
      sandboxId: null,
      error: null,
    },
    pendingApproval: null,
    approvalSubmission: "idle",
    approvalError: null,
    patchEvidence: null,
  };
}

describe("sandboxSnapshot", () => {
  let storage: Storage;

  beforeEach(() => {
    storage = createStorage();
  });

  it("reads a valid snapshot from storage", () => {
    storage.setItem(SANDBOX_SNAPSHOT_KEY, JSON.stringify(validState()));
    const snapshot = readSandboxSnapshot(storage);
    expect(snapshot).toBeDefined();
    expect(snapshot?.id).toBe("AR-024");
    expect(snapshot?.activeTab).toBe("environment");
  });

  it("returns null for missing storage", () => {
    expect(readSandboxSnapshot(storage)).toBeNull();
  });

  it("returns null for malformed storage data", () => {
    storage.setItem(SANDBOX_SNAPSHOT_KEY, JSON.stringify({ bad: true }));
    expect(readSandboxSnapshot(storage)).toBeNull();
    storage.setItem(SANDBOX_SNAPSHOT_KEY, "not-json");
    expect(readSandboxSnapshot(storage)).toBeNull();
  });

  it("writes and validates a snapshot", () => {
    writeSandboxSnapshot(storage, validState());
    const raw = storage.getItem(SANDBOX_SNAPSHOT_KEY);
    expect(raw).toBeTruthy();
    const parsed = JSON.parse(raw as string) as Partial<MissionState>;
    expect(parsed.id).toBe("AR-024");
    expect(parsed.dockOpen).toBe(true);
  });

  it("no-ops on storage write errors", () => {
    const badStorage = {
      ...storage,
      setItem: () => {
        throw new Error("quota");
      },
    } as Storage;
    expect(() => writeSandboxSnapshot(badStorage, validState())).not.toThrow();
  });

  it("no-ops on storage read errors", () => {
    const badStorage = {
      getItem: () => {
        throw new Error("denied");
      },
    } as unknown as Storage;
    expect(readSandboxSnapshot(badStorage)).toBeNull();
  });
});

describe("subscribeSandboxSnapshot", () => {
  beforeEach(() => {
    const listeners: ((event: MessageEvent<unknown>) => void)[] = [];
    vi.stubGlobal(
      "BroadcastChannel",
      class {
        name: string;
        onmessage: ((event: MessageEvent<unknown>) => void) | null = null;
        constructor(name: string) {
          this.name = name;
          listeners.push(
            (event: MessageEvent<unknown>) => {
              if (this.onmessage) this.onmessage(event);
            }
          );
        }
        postMessage(message: unknown) {
          listeners.forEach((listener) =>
            listener(new MessageEvent("message", { data: message }))
          );
        }
        close() {}
      }
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("receives a valid snapshot over the channel", () => {
    const received: unknown[] = [];
    const unsubscribe = subscribeSandboxSnapshot((state) =>
      received.push(state)
    );

    const channel = new BroadcastChannel("agentradar-sandbox-v1");
    channel.postMessage(validState());
    channel.close();

    expect(received.length).toBe(1);
    unsubscribe();
  });

  it("ignores an invalid channel message", () => {
    const received: unknown[] = [];
    const unsubscribe = subscribeSandboxSnapshot((state) =>
      received.push(state)
    );

    const channel = new BroadcastChannel("agentradar-sandbox-v1");
    channel.postMessage({ bad: true });
    channel.close();

    expect(received.length).toBe(0);
    unsubscribe();
  });

  it("returns a no-op when BroadcastChannel is not available", () => {
    vi.unstubAllGlobals();
    const unsubscribe = subscribeSandboxSnapshot(() => {});
    expect(unsubscribe()).toBeUndefined();
  });
});
