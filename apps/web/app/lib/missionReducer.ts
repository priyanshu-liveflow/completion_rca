import { fixtureMission } from "./fixtures";
import {
  MissionEvent,
  MissionState,
  NodeId,
  NodeStatus,
} from "./types";

export function createInitialMissionState(
  currentTime = "—",
  seed: Partial<MissionState> = {}
): MissionState {
  return {
    ...fixtureMission,
    nodes: fixtureMission.nodes.map((node) => ({ ...node, status: "pending" })),
    transcript: [],
    redObserved: false,
    greenObservedAfterRed: false,
    redTests: 0,
    greenTests: 0,
    selectedNode: null,
    dockOpen: true,
    activeTab: "environment",
    popOutOpen: false,
    approved: null,
    currentTime,
    restored: true,
    ...seed,
  };
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

export function canApproveMission(state: MissionState) {
  return (
    state.redObserved &&
    state.greenObservedAfterRed &&
    state.approved === null
  );
}

export function missionReducer(
  state: MissionState,
  event: MissionEvent
): MissionState {
  switch (event.type) {
    case "mission.reset":
      return createInitialMissionState(event.currentTime ?? state.currentTime);
    case "proof.node.updated":
      return updateNode(state, event.nodeId, event.status);
    case "sandbox.line.appended":
      return state.transcript.some((line) => line.id === event.line.id)
        ? state
        : { ...state, transcript: [...state.transcript, event.line] };
    case "tests.red_observed":
      return {
        ...updateNode(state, "errors", "red"),
        redObserved: true,
        greenObservedAfterRed: false,
        redTests: event.failed,
        greenTests: 0,
      };
    case "tests.green_observed":
      if (!state.redObserved) return state;
      return {
        ...updateNode(state, "verify", "green"),
        greenObservedAfterRed: true,
        greenTests: event.passed,
      };
    case "selection.changed":
      return { ...state, selectedNode: event.nodeId };
    case "dock.toggled":
      return { ...state, dockOpen: !state.dockOpen };
    case "inspector.tab.changed":
      return { ...state, activeTab: event.tab };
    case "popout.toggled":
      return { ...state, popOutOpen: !state.popOutOpen };
    case "approval.approved":
      return canApproveMission(state) ? { ...state, approved: true } : state;
    case "approval.denied":
      return state.approved === null ? { ...state, approved: false } : state;
    case "clock.ticked":
      return { ...state, currentTime: event.currentTime };
  }
}
