export type NodeId =
  | "release"
  | "imports"
  | "tests"
  | "errors"
  | "patch"
  | "verify";

export type AgentRole =
  | "WATCHER"
  | "LOCATOR"
  | "BLASTER"
  | "PATCHER"
  | "VERIFIER";

export type NodeStatus = "pending" | "static" | "red" | "green" | "amber";

export interface ProofNode {
  id: NodeId;
  role: AgentRole;
  label: string;
  detail: string;
  status: NodeStatus;
}

export interface TestLine {
  id: string;
  nodeId?: NodeId;
  command?: string;
  text: string;
  kind: "command" | "stdout" | "stderr" | "status" | "timing";
}

export interface FixtureMission {
  id: string;
  repo: string;
  indexedCommit: string;
  dependency: string;
  baselineVersion: string;
  breakingVersion: string;
  nodes: ProofNode[];
}

export interface MissionState extends FixtureMission {
  transcript: TestLine[];
  redObserved: boolean;
  greenObservedAfterRed: boolean;
  redTests: number;
  greenTests: number;
  selectedNode: NodeId | null;
  dockOpen: boolean;
  activeTab: "environment" | "files" | "processes";
  popOutOpen: boolean;
  approved: boolean | null;
  currentTime: string;
  restored: boolean;
}

export type MissionEvent =
  | { type: "mission.reset"; currentTime?: string }
  | { type: "proof.node.updated"; nodeId: NodeId; status: NodeStatus }
  | { type: "sandbox.line.appended"; line: TestLine }
  | { type: "tests.red_observed"; failed: number }
  | { type: "tests.green_observed"; passed: number }
  | { type: "selection.changed"; nodeId: NodeId | null }
  | { type: "dock.toggled" }
  | { type: "inspector.tab.changed"; tab: MissionState["activeTab"] }
  | { type: "popout.toggled" }
  | { type: "approval.approved" }
  | { type: "approval.denied" }
  | { type: "clock.ticked"; currentTime: string };
