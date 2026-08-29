import { MissionAdapter } from "./missionAdapter";
import { MissionEvent, TestRunEvidence } from "./types";

export interface TimedMissionEvent {
  at: number;
  event: MissionEvent;
}

const selectedTests =
  "tests/test_make_intervals_request.py tests/test_server.py";

const sandboxId = "sxn-72a9f0";

const redEvidence: TestRunEvidence = {
  runId: "fixture-red-001",
  missionId: "AR-024",
  sandboxId,
  selectionKey: selectedTests,
  phase: "reproduce",
  exitCode: 2,
};

const greenEvidence: TestRunEvidence = {
  runId: "fixture-green-001",
  missionId: "AR-024",
  sandboxId,
  selectionKey: selectedTests,
  phase: "verify",
  exitCode: 0,
};

export const fixtureMissionEvents: TimedMissionEvent[] = [
  {
    at: 180,
    event: {
      type: "proof.node.updated",
      nodeId: "release",
      status: "amber",
    },
  },
  {
    at: 280,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t1",
        kind: "status",
        text: "sandbox sxn-72a9f0 attached through TrueForge",
      },
    },
  },
  {
    at: 420,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t2",
        kind: "command",
        text: "git clone --depth 1 https://github.com/mvilanova/intervals-mcp-server",
      },
    },
  },
  {
    at: 560,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t3", kind: "stdout", text: "checked out cb1fbcac" },
    },
  },
  {
    at: 700,
    event: {
      type: "proof.node.updated",
      nodeId: "imports",
      status: "static",
    },
  },
  {
    at: 840,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t4",
        kind: "command",
        text: "uv pip install 'mcp[cli]==1.29.1'",
      },
    },
  },
  {
    at: 980,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t5", kind: "stdout", text: "baseline installed in 3.1s" },
    },
  },
  {
    at: 1120,
    event: {
      type: "proof.node.updated",
      nodeId: "tests",
      status: "static",
    },
  },
  {
    at: 1260,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t6", kind: "command", text: `pytest ${selectedTests}` },
    },
  },
  {
    at: 1400,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t7", kind: "stdout", text: "61 passed" },
    },
  },
  {
    at: 1540,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t8",
        kind: "status",
        text: "baseline exit 0",
        nodeId: "tests",
      },
    },
  },
  {
    at: 1720,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t9",
        kind: "command",
        text: "uv pip install 'mcp[cli]==2.1.1'",
      },
    },
  },
  {
    at: 1860,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t10", kind: "stdout", text: "mcp[cli] 2.1.1 installed" },
    },
  },
  {
    at: 2000,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t11", kind: "command", text: `pytest ${selectedTests}` },
    },
  },
  {
    at: 2140,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t12",
        kind: "stderr",
        text: "ModuleNotFoundError: No module named 'mcp.server.fastmcp'",
        nodeId: "errors",
      },
    },
  },
  {
    at: 2280,
    event: { type: "tests.red_observed", failed: 2, evidence: redEvidence },
  },
  {
    at: 2290,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t13",
        kind: "status",
        text: "2 collection errors · exit 2",
        nodeId: "errors",
      },
    },
  },
  {
    at: 2560,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t14",
        kind: "command",
        text: "git apply /tmp/agentradar-fastmcp.patch",
      },
    },
  },
  {
    at: 2700,
    event: {
      type: "proof.node.updated",
      nodeId: "patch",
      status: "static",
    },
  },
  {
    at: 2701,
    event: {
      type: "patch.observed",
      patch: {
        diff: "@@ -1 +1 @@\n-import mcp.server.fastmcp\n+from mcp.server.fastmcp import FastMCP",
        files: [
          "src/intervals/mcp.py",
          "src/intervals/server.py",
          "tests/test_mcp.py",
          "tests/test_server.py",
        ],
        rationale: "Update FastMCP import path for mcp[cli] 2.1.1",
      },
    },
  },
  {
    at: 2710,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t15", kind: "stdout", text: "patched 4 import sites" },
    },
  },
  {
    at: 2980,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t16", kind: "command", text: `pytest ${selectedTests}` },
    },
  },
  {
    at: 3260,
    event: { type: "tests.green_observed", passed: 61, evidence: greenEvidence },
  },
  {
    at: 3270,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t17", kind: "stdout", text: "61 passed", nodeId: "verify" },
    },
  },
  {
    at: 3410,
    event: {
      type: "sandbox.line.appended",
      line: { id: "t18", kind: "status", text: "exit 0", nodeId: "verify" },
    },
  },
  {
    at: 3550,
    event: {
      type: "sandbox.line.appended",
      line: {
        id: "t19",
        kind: "timing",
        text: "live red-to-green 6.1s",
        nodeId: "verify",
      },
    },
  },
];

export function createFixtureMissionAdapter(
  events: TimedMissionEvent[] = fixtureMissionEvents
): MissionAdapter {
  return {
    mode: "fixture",
    subscribe(dispatch) {
      const timers = events.map(({ at, event }) =>
        window.setTimeout(() => dispatch(event), at)
      );
      return () => timers.forEach((timer) => window.clearTimeout(timer));
    },
  };
}

export const fixtureMissionAdapter = createFixtureMissionAdapter();

export const noOpAdapter: MissionAdapter = {
  mode: "fixture",
  subscribe: () => () => {},
};
