import { fixtureMission } from "./fixtures";
import {
  MissionEvent,
  MissionState,
  NodeId,
  NodeStatus,
  TestRunEvidence,
} from "./types";

export interface InitialMissionOptions {
  currentTime?: string;
  mode?: "fixture" | "live";
  seed?: Partial<MissionState>;
}

export function createInitialMissionState(
  options: InitialMissionOptions = {}
): MissionState {
  const mode = options.mode ?? "fixture";
  const currentTime = options.currentTime ?? "—";
  const status: MissionState["runtime"]["status"] =
    mode === "fixture" ? "fixture" : "idle";

  const initial: MissionState = {
    ...fixtureMission,
    nodes: fixtureMission.nodes.map((node) => ({ ...node, status: "pending" })),
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
    currentTime,
    restored: true,
    runtime: {
      mode,
      status,
      sessionId: null,
      turnId: null,
      sandboxId: null,
      error: null,
    },
    pendingApproval: null,
    approvalSubmission: "idle",
    approvalError: null,
    patchEvidence: null,
    ...options.seed,
  };
  return initial;
}

function updateNode(
  state: MissionState,
  nodeId: NodeId,
  status: NodeStatus
): MissionState {
  return {
    ...state,
    nodes: state.nodes.map((node) =>
      node.id === nodeId ? { ...node, status } : node
    ),
  };
}

function evidenceMatches(red: TestRunEvidence, green: TestRunEvidence) {
  return (
    red.missionId === green.missionId &&
    red.sandboxId === green.sandboxId &&
    red.selectionKey === green.selectionKey &&
    red.phase === "reproduce" &&
    green.phase === "verify" &&
    red.exitCode !== 0 &&
    green.exitCode === 0
  );
}

export function canApproveMission(state: MissionState) {
  const hasMatchingEvidence =
    state.redEvidence &&
    state.greenEvidence &&
    evidenceMatches(state.redEvidence, state.greenEvidence);

  const hasPendingApproval =
    state.runtime.mode === "live" ? state.pendingApproval !== null : true;

  return Boolean(
    hasMatchingEvidence &&
      hasPendingApproval &&
      state.approvalSubmission !== "submitting" &&
      state.approved === null
  );
}

export function missionReducer(
  state: MissionState,
  event: MissionEvent
): MissionState {
  switch (event.type) {
    case "mission.reset":
      return createInitialMissionState({
        currentTime: event.currentTime ?? state.currentTime,
        mode: state.runtime.mode,
      });
    case "runtime.connecting":
      return {
        ...state,
        runtime: { ...state.runtime, status: "connecting", error: null },
      };
    case "runtime.connected":
      return {
        ...state,
        runtime: { ...state.runtime, sessionId: event.sessionId, status: "idle" },
      };
    case "runtime.turn.started":
      return {
        ...state,
        runtime: { ...state.runtime, turnId: event.turnId ?? null, status: "streaming" },
      };
    case "runtime.turn.completed":
      return {
        ...state,
        runtime: {
          ...state.runtime,
          status:
            state.pendingApproval !== null ? "awaiting_approval" : "completed",
        },
      };
    case "runtime.failed":
      return {
        ...state,
        runtime: { ...state.runtime, status: "failed", error: event.message },
      };
    case "sandbox.connected":
      return {
        ...state,
        runtime: { ...state.runtime, sandboxId: event.sandboxId },
      };
    case "proof.node.updated":
      return updateNode(state, event.nodeId, event.status);
    case "sandbox.line.appended":
      return state.transcript.some((line) => line.id === event.line.id)
        ? state
        : { ...state, transcript: [...state.transcript, event.line] };
    case "tests.red_observed": {
      const redEvidence = event.evidence ?? null;
      if (redEvidence && redEvidence.phase === "baseline") {
        // Baseline green is not the same as reproduced red; do not unlock.
        return {
          ...updateNode(state, "tests", "green"),
          redTests: 0,
        };
      }
      return {
        ...updateNode(state, "errors", "red"),
        redObserved: true,
        greenObservedAfterRed: false,
        redTests: event.failed,
        greenTests: 0,
        redEvidence,
        greenEvidence: null,
        approved: null,
        approvalSubmission: "idle",
        approvalError: null,
      };
    }
    case "tests.green_observed": {
      const greenEvidence = event.evidence ?? null;
      if (greenEvidence?.phase === "baseline") {
        return {
          ...updateNode(state, "tests", "green"),
          greenTests: greenEvidence.exitCode === 0 ? event.passed : 0,
        };
      }
      if (!state.redObserved) return state;
      return {
        ...updateNode(state, "verify", "green"),
        greenObservedAfterRed: true,
        greenTests: event.passed,
        greenEvidence,
      };
    }
    case "selection.changed":
      return { ...state, selectedNode: event.nodeId };
    case "dock.toggled":
      return { ...state, dockOpen: !state.dockOpen };
    case "inspector.tab.changed":
      return { ...state, activeTab: event.tab };
    case "popout.toggled":
      return { ...state, popOutOpen: !state.popOutOpen };
    case "approval.required":
      return {
        ...state,
        pendingApproval: event.request,
        runtime: { ...state.runtime, status: "awaiting_approval" },
      };
    case "approval.submitting":
      return { ...state, approvalSubmission: "submitting", approvalError: null };
    case "approval.resolved":
      return {
        ...state,
        approvalSubmission: event.decision === "approve" ? "accepted" : "denied",
        approved: event.decision === "approve",
        approvalError: null,
      };
    case "approval.failed":
      return {
        ...state,
        approvalSubmission: "failed",
        approvalError: event.message,
      };
    case "patch.observed":
      return {
        ...updateNode(state, "patch", "static"),
        patchEvidence: event.patch,
      };
    case "approval.approved":
      return canApproveMission(state) ? { ...state, approved: true } : state;
    case "approval.denied":
      return state.approved === null
        ? { ...state, approved: false, approvalSubmission: "denied" }
        : state;
    case "clock.ticked":
      return { ...state, currentTime: event.currentTime };
  }
}
