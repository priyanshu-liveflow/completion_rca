import { describe, expect, it } from "vitest";
import {
  canApproveMission,
  createInitialMissionState,
  missionReducer,
} from "./missionReducer";

const redEvidence = {
  runId: "r-red",
  missionId: "AR-024",
  sandboxId: "sxn-72a9f0",
  selectionKey: "tests/test_make_intervals_request.py tests/test_server.py",
  phase: "reproduce" as const,
  exitCode: 2,
};

const greenEvidence = {
  runId: "r-green",
  missionId: "AR-024",
  sandboxId: "sxn-72a9f0",
  selectionKey: "tests/test_make_intervals_request.py tests/test_server.py",
  phase: "verify" as const,
  exitCode: 0,
};

const regressEvidence = {
  runId: "r-regress",
  missionId: "AR-024",
  sandboxId: "sxn-72a9f0",
  selectionKey: "tests/test_make_intervals_request.py tests/test_server.py",
  phase: "reproduce" as const,
  exitCode: 1,
};

describe("createInitialMissionState", () => {
  it("initializes fixture mode by default", () => {
    const state = createInitialMissionState();
    expect(state.runtime.mode).toBe("fixture");
    expect(state.runtime.status).toBe("fixture");
  });

  it("initializes live mode to idle", () => {
    const state = createInitialMissionState({ mode: "live" });
    expect(state.runtime.mode).toBe("live");
    expect(state.runtime.status).toBe("idle");
  });
});

describe("missionReducer approval evidence", () => {
  it("ignores green verification that arrives before reproduced red evidence", () => {
    const state = missionReducer(createInitialMissionState(), {
      type: "tests.green_observed",
      passed: 61,
      evidence: greenEvidence,
    });

    expect(state.nodes.find((node) => node.id === "verify")?.status).toBe(
      "pending"
    );
    expect(state.greenTests).toBe(0);
    expect(canApproveMission(state)).toBe(false);
  });

  it("unlocks approval only after a red run is followed by a green run", () => {
    const initial = createInitialMissionState();
    const red = missionReducer(initial, {
      type: "tests.red_observed",
      failed: 2,
      evidence: redEvidence,
    });
    const green = missionReducer(red, {
      type: "tests.green_observed",
      passed: 61,
      evidence: greenEvidence,
    });

    expect(canApproveMission(initial)).toBe(false);
    expect(canApproveMission(red)).toBe(false);
    expect(canApproveMission(green)).toBe(true);
    expect(green.redTests).toBe(2);
    expect(green.greenTests).toBe(61);
  });

  it("relocks approval and clears green evidence when a later run goes red", () => {
    const red = missionReducer(createInitialMissionState(), {
      type: "tests.red_observed",
      failed: 2,
      evidence: redEvidence,
    });
    const green = missionReducer(red, {
      type: "tests.green_observed",
      passed: 61,
      evidence: greenEvidence,
    });
    const regressed = missionReducer(green, {
      type: "tests.red_observed",
      failed: 1,
      evidence: regressEvidence,
    });

    expect(canApproveMission(green)).toBe(true);
    expect(canApproveMission(regressed)).toBe(false);
    expect(regressed.greenTests).toBe(0);
    expect(regressed.greenEvidence).toBeNull();
    expect(regressed.greenObservedAfterRed).toBe(false);
    expect(regressed.approved).toBeNull();
    expect(regressed.approvalSubmission).toBe("idle");
  });

  it("keeps turn completed from overwriting awaiting_approval", () => {
    const pending = missionReducer(createInitialMissionState({ mode: "live" }), {
      type: "approval.required",
      request: {
        requestId: "req-1",
        toolName: "github_open_pr",
        summary: "Open PR",
        raw: null,
      },
    });
    const afterTurn = missionReducer(pending, {
      type: "runtime.turn.completed",
    });
    expect(afterTurn.runtime.status).toBe("awaiting_approval");
  });

  it("clears approval failure on a new red observation", () => {
    const green = missionReducer(
      missionReducer(createInitialMissionState(), {
        type: "tests.red_observed",
        failed: 2,
        evidence: redEvidence,
      }),
      {
        type: "tests.green_observed",
        passed: 61,
        evidence: greenEvidence,
      }
    );
    const failed = missionReducer(green, {
      type: "approval.failed",
      message: "Live approval is not available in this build",
    });
    const regressed = missionReducer(failed, {
      type: "tests.red_observed",
      failed: 1,
      evidence: regressEvidence,
    });
    expect(regressed.approvalError).toBeNull();
    expect(regressed.approvalSubmission).toBe("idle");
    expect(regressed.approved).toBeNull();
  });
});
