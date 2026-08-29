import type { MissionEvent } from "./types";

export type MissionMode = "fixture" | "live";
export type MissionDispatch = (event: MissionEvent) => void;
export type ApprovalDecision = "approve" | "deny";

export interface ApprovalRequest {
  requestId: string;
  toolName: string;
  summary: string;
  raw: unknown;
}

export interface MissionAdapter {
  readonly mode: MissionMode;

  subscribe(dispatch: MissionDispatch): () => void;

  resolveApproval?(
    request: ApprovalRequest,
    decision: ApprovalDecision
  ): Promise<void>;
}
