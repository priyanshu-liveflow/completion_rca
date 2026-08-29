import type { MissionState } from "./types";

export const SANDBOX_SNAPSHOT_KEY = "ar-mission-snapshot-v1";
export const SANDBOX_CHANNEL = "agentradar-sandbox-v1";

type PartialState = Partial<MissionState>;

const VALID_TABS: MissionState["activeTab"][] = [
  "environment",
  "files",
  "processes",
];

function isSandboxSnapshot(value: unknown): value is PartialState {
  if (typeof value !== "object" || value === null) {
    return false;
  }

  const s = value as PartialState;

  if (typeof s.id !== "string" || typeof s.repo !== "string") {
    return false;
  }

  if (!Array.isArray(s.transcript)) {
    return false;
  }

  if (!VALID_TABS.includes(s.activeTab as MissionState["activeTab"])) {
    return false;
  }

  if (typeof s.dockOpen !== "boolean") {
    return false;
  }

  if (typeof s.runtime !== "object" || s.runtime === null) {
    return false;
  }

  const mode = (s.runtime as { mode?: unknown }).mode;
  if (mode !== "fixture" && mode !== "live") {
    return false;
  }

  return true;
}

export function readSandboxSnapshot(storage: Storage): PartialState | null {
  try {
    const raw = storage.getItem(SANDBOX_SNAPSHOT_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as unknown;
    return isSandboxSnapshot(parsed) ? parsed : null;
  } catch {
    return null;
  }
}

function broadcastChannelAvailable(): boolean {
  return (
    typeof globalThis !== "undefined" &&
    typeof (globalThis as { BroadcastChannel?: unknown }).BroadcastChannel ===
      "function"
  );
}

function postSnapshot(snapshot: PartialState): void {
  if (!broadcastChannelAvailable()) return;
  try {
    const channel = new BroadcastChannel(SANDBOX_CHANNEL);
    channel.postMessage(snapshot);
    channel.close();
  } catch {
    // no-op
  }
}

export function writeSandboxSnapshot(
  storage: Storage,
  state: MissionState
): void {
  try {
    const snapshot: PartialState = {
      id: state.id,
      repo: state.repo,
      transcript: state.transcript,
      activeTab: state.activeTab,
      dockOpen: state.dockOpen,
      runtime: state.runtime,
      selectedNode: state.selectedNode,
      nodes: state.nodes,
    };

    if (!isSandboxSnapshot(snapshot)) return;

    storage.setItem(SANDBOX_SNAPSHOT_KEY, JSON.stringify(snapshot));
    postSnapshot(snapshot);
  } catch {
    // no-op
  }
}

export function subscribeSandboxSnapshot(
  onState: (state: PartialState) => void
): () => void {
  if (!broadcastChannelAvailable()) {
    return () => {};
  }

  try {
    const channel = new BroadcastChannel(SANDBOX_CHANNEL);
    channel.onmessage = (event: MessageEvent<unknown>) => {
      const snapshot = event.data;
      if (isSandboxSnapshot(snapshot)) {
        onState(snapshot);
      }
    };
    return () => channel.close();
  } catch {
    return () => {};
  }
}
