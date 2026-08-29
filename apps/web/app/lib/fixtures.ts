import { FixtureMission } from "./types";

export const fixtureMission: FixtureMission = {
  id: "AR-024",
  repo: "mvilanova/intervals-mcp-server",
  indexedCommit: "cb1fbcac81095cf3e094e995decf04b8b1f259f8",
  dependency: "mcp[cli]",
  baselineVersion: "1.29.1",
  breakingVersion: "2.1.1",
  nodes: [
    {
      id: "release",
      role: "WATCHER",
      label: "MCP SDK v2.1.1 release",
      detail:
        "Bright Data collector retrieved the release. FastMCP moved from mcp.server.fastmcp to mcp.server.mcpserver.",
      status: "pending",
    },
    {
      id: "imports",
      role: "LOCATOR",
      label: "four affected imports",
      detail:
        "Graph import-prefix matching found 4 source files importing the old fastmcp module.",
      status: "pending",
    },
    {
      id: "tests",
      role: "BLASTER",
      label: "two graph-selected test modules",
      detail:
        "CALLS and IMPORTS strategies selected exactly the 2 test modules that reach the changed symbol.",
      status: "pending",
    },
    {
      id: "errors",
      role: "PATCHER",
      label: "two collection errors",
      detail:
        "pytest collected the selected modules and raised ImportError on the moved FastMCP class.",
      status: "pending",
    },
    {
      id: "patch",
      role: "PATCHER",
      label: "four-line import patch",
      detail:
        "Replaced the old FastMCP import with `from mcp.server.mcpserver import MCPServer as FastMCP` in 4 files.",
      status: "pending",
    },
    {
      id: "verify",
      role: "VERIFIER",
      label: "61 tests passed",
      detail:
        "The same 2 selected test modules ran after the patch. All 61 tests passed.",
      status: "pending",
    },
  ],
};
