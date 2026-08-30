export const DEMO_REPO = "mvilanova/intervals-mcp-server";
export const DEMO_INDEXED_COMMIT =
  "cb1fbcac81095cf3e094e995decf04b8b1f259f8";
export const DEMO_DEPENDENCY = "mcp[cli]";
export const DEMO_BASELINE_VERSION = "1.29.1";
export const DEMO_BREAKING_VERSION = "2.1.1";

export const DEMO_MISSION_PROMPT = [
  `Reproduce and fix the dependency upgrade for ${DEMO_REPO} at commit ${DEMO_INDEXED_COMMIT.slice(0, 12)}.`,
  `The dependency ${DEMO_DEPENDENCY} breaks between ${DEMO_BASELINE_VERSION} and ${DEMO_BREAKING_VERSION}.`,
  `Use the graph-selected test modules, run them under the new version, apply a minimal import patch, and verify that the same tests pass.`,
  `Do not open any PR or issue; wait for explicit human approval before writing to GitHub.`,
].join("\n");

export const demoMissionInput = [
  { type: "user.message" as const, content: DEMO_MISSION_PROMPT },
];
