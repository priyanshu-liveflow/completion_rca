export type MissionMode = "fixture" | "live";

export type RuntimeStatus =
  | "fixture"
  | "idle"
  | "connecting"
  | "streaming"
  | "awaiting_approval"
  | "completed"
  | "failed";

export interface MissionRuntimeState {
  mode: MissionMode;
  status: RuntimeStatus;
  sessionId: string | null;
  turnId: string | null;
  sandboxId: string | null;
  error: string | null;
}

export type TestRunPhase = "baseline" | "reproduce" | "verify";

export interface TestRunEvidence {
  runId: string;
  missionId: string;
  sandboxId: string;
  selectionKey: string;
  phase: TestRunPhase;
  exitCode: number;
}

export interface PatchEvidence {
  diff: string;
  files: string[];
  rationale: string;
}

export interface ApprovalRequest {
  requestId: string;
  toolName: string;
  summary: string;
  raw: unknown;
}

export type ApprovalSubmission =
  | "idle"
  | "submitting"
  | "accepted"
  | "denied"
  | "failed";

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
  redEvidence: TestRunEvidence | null;
  greenEvidence: TestRunEvidence | null;
  selectedNode: NodeId | null;
  dockOpen: boolean;
  activeTab: "environment" | "files" | "processes";
  popOutOpen: boolean;
  approved: boolean | null;
  currentTime: string;
  restored: boolean;
  runtime: MissionRuntimeState;
  pendingApproval: ApprovalRequest | null;
  approvalSubmission: ApprovalSubmission;
  approvalError: string | null;
  patchEvidence: PatchEvidence | null;
}

export type MissionEvent =
  | { type: "mission.reset"; currentTime?: string }
  | { type: "runtime.connecting" }
  | { type: "runtime.connected"; sessionId: string }
  | { type: "runtime.turn.started"; turnId: string | null }
  | { type: "runtime.turn.completed" }
  | { type: "runtime.failed"; message: string }
  | { type: "sandbox.connected"; sandboxId: string }
  | { type: "proof.node.updated"; nodeId: NodeId; status: NodeStatus }
  | { type: "sandbox.line.appended"; line: TestLine }
  | { type: "tests.red_observed"; failed: number; evidence?: TestRunEvidence }
  | { type: "tests.green_observed"; passed: number; evidence?: TestRunEvidence }
  | { type: "patch.observed"; patch: PatchEvidence }
  | { type: "selection.changed"; nodeId: NodeId | null }
  | { type: "dock.toggled" }
  | { type: "inspector.tab.changed"; tab: MissionState["activeTab"] }
  | { type: "popout.toggled" }
  | { type: "approval.required"; request: ApprovalRequest }
  | { type: "approval.approved" }
  | { type: "approval.denied" }
  | { type: "approval.submitting" }
  | { type: "approval.resolved"; decision: "approve" | "deny" }
  | { type: "approval.failed"; message: string }
  | { type: "clock.ticked"; currentTime: string };
