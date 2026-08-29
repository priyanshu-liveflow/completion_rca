import { describe, expect, it } from "vitest";
import {
  canApproveMission,
  createInitialMissionState,
  missionReducer,
} from "./missionReducer";

describe("missionReducer approval evidence", () => {
  it("ignores green verification that arrives before reproduced red evidence", () => {
    const state = missionReducer(createInitialMissionState(), {
      type: "tests.green_observed",
      passed: 61,
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
    });
    const green = missionReducer(red, {
      type: "tests.green_observed",
      passed: 61,
    });

    expect(canApproveMission(initial)).toBe(false);
    expect(canApproveMission(red)).toBe(false);
    expect(canApproveMission(green)).toBe(true);
    expect(green.redTests).toBe(2);
    expect(green.greenTests).toBe(61);
  });

  it("relocks approval when a later selected-test run goes red", () => {
    const red = missionReducer(createInitialMissionState(), {
      type: "tests.red_observed",
      failed: 2,
    });
    const green = missionReducer(red, {
      type: "tests.green_observed",
      passed: 61,
    });
    const regressed = missionReducer(green, {
      type: "tests.red_observed",
      failed: 1,
    });

    expect(canApproveMission(green)).toBe(true);
    expect(canApproveMission(regressed)).toBe(false);
    expect(regressed.greenTests).toBe(0);
  });
});
