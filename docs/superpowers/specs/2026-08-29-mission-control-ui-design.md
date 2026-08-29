# AgentRadar Mission Control UI Design

## Goal

Build the first production-shaped AgentRadar frontend in `apps/web`. The screen must let a viewer understand one dependency-upgrade mission without reading a chat transcript: the graph finds the affected code, selected tests prove the break in a TrueForge-native Daytona sandbox, an agent prepares a patch, the same test suite proves the fix, and a human decides whether the verified change may leave the sandbox.

This frontend starts with deterministic fixtures and performs no external write. Its data boundary must allow fixture events to be replaced later by TrueForge session events without redesigning the interface.

## Approved Visual Target

The approved direction is option **1b — Paper Schematic** from [`docs/design/agentradar-visual-options.html`](../../design/agentradar-visual-options.html#1b), preserved from the user-supplied visual exploration, with the subsequent layout revision approved in chat.

The interface should resemble a printed engineering report or patent drawing rather than a conventional SaaS dashboard:

- Warm paper ground `#f2ede2` with near-black ink `#211d16`.
- Secondary ink `#5a5346`; quiet metadata `#8a8271`.
- Oxide red `#a5453d` only for reproduced failures.
- Mineral green `#3f6b46` only for verified or connected states.
- Amber-brown `#8a5a1c` only for human attention and blocked approval.
- Hairline black rules, dashed evidence nodes, square geometry, and no gradients, glass, decorative shadows, or generic AI imagery.
- IBM Plex Sans for interface language and IBM Plex Mono for commands, paths, commits, metrics, and timestamps. Fonts are installed locally through `@fontsource`; no font CDN is required.
- Maintained line icons from one library. Do not handcraft SVG or CSS icons.

## Primary Layout

The reference viewport is `1440 × 1024`. The desktop shell contains these regions:

1. **Global header** — AgentRadar identity, repository, mission ID, restored-session status, current time, documentation, and settings.
2. **Left navigation** — Mission Control selected, followed by Graph, Events, Agents, Sandbox, Commits, Tests, Artifacts, and Settings. Mission state and auto-refresh status remain pinned at the bottom.
3. **Mission workspace** — the main center column. The proof map occupies its upper region and the Live Sandbox occupies a terminal-style dock directly below it.
4. **Human Approval Required rail** — a fixed `270px` right column that spans the height of both the mission map and terminal dock. The rail never moves below the terminal at the reference viewport.

In compact notation, the approved structure is:

```text
header
└─ navigation | mission map     | approval rail
              | live sandbox    | approval rail
```

The sandbox is not a fourth graph column. It is a lower IDE-style terminal surface associated with the whole mission workspace.

## Mission Map

The map presents a left-to-right proof chain:

```text
MCP SDK v2.1.1 release
  → four affected imports
  → two graph-selected test modules
  → two collection errors
  → four-line import patch
  → 61 tests passed
```

WATCHER, LOCATOR, BLASTER, PATCHER, and VERIFIER labels make TrueForge delegation legible without avatars or chat bubbles. Every graph verdict before the sandbox run is labelled as static analysis, not proof.

Selecting release, source, test, failure, patch, or verification nodes changes the selected state and highlights the related terminal lines. Nodes use semantic borders and type rather than filled marketing cards.

## Live Sandbox Dock

The dock is a read-only mirror of TrueForge events from the Daytona sandbox. It includes:

- Header: `Live Sandbox · <sandbox id>`, connected state, elapsed time, collapse control, and pop-out control.
- Transcript: exact commands, stdout/stderr, exit status, and timing.
- Inspector: Environment, Files, and Processes tabs.
- A persistent selected tab and transcript position when collapsed and reopened.
- A dedicated read-only pop-out window using the same fixture/session state.

The dock must say **TrueForge-native Daytona sandbox** or **Daytona**. It must never say `sandbox · local`, `prebaked image`, or imply that a custom image is configured.

## Approval Rail

The rail is always visible at the right of the proof workspace. It contains:

- `HUMAN APPROVAL REQUIRED` status.
- Verified patch receipt, base commit, files changed, and before/after test result.
- The guard sentence: `The PR tool stayed locked while tests were red.`
- Primary `Approve verified PR` and secondary `Deny` actions.
- An explicit prototype note that neither action writes to GitHub.

The primary action remains disabled until the deterministic mission reaches a valid red-to-green state. Approval opens a confirmation dialog containing repository, target branch, patch summary, and test receipt. Confirming updates local fixture state only.

## Demo Data

Fixtures must use the real demo facts already committed in `configs/demo.yaml` and `docs/demo-repo.md`:

- Repository: `mvilanova/intervals-mcp-server`.
- Indexed commit: `cb1fbcac81095cf3e094e995decf04b8b1f259f8`.
- Dependency: `mcp[cli]`, baseline `1.29.1`, breaking release `2.1.1`.
- Break: `FastMCP` moved from `mcp.server.fastmcp` to `MCPServer` in `mcp.server.mcpserver`.
- Four importing files require the same one-line change.
- Graph selects exactly two test modules through import-prefix matching.
- Before: two pytest collection errors and exit code `2`.
- After: `61 passed`.
- Daytona evidence: `10.1s` cold path and `6.1s` live red-to-green path.

Do not use the older LangGraph/acme fixture copy in the production-shaped frontend.

## Application Architecture

- Framework: Next.js App Router, React, and TypeScript in `apps/web`.
- Styling: CSS Modules plus global CSS custom properties for tokens; no Tailwind dependency and no large component system.
- Icons: `lucide-react`.
- Fonts: locally installed `@fontsource/ibm-plex-sans` and `@fontsource/ibm-plex-mono` packages.
- Tests: Vitest, Testing Library, and jsdom.
- Fixture state: typed mission data and a deterministic event reducer separated from view components.
- Runtime boundary: the fixture adapter is the default. A later TrueForge adapter may target `http://localhost:8790` by default.

The application must start with `npm run dev` from `apps/web`. It requires no `.env`, API key, or frontend secret. NVIDIA NIM and Daytona credentials remain in TrueForge settings and are never exposed to browser code.

## Component Boundaries

- `MissionControlPage` composes the screen and owns no mission logic.
- `MissionProvider` exposes typed mission state and commands.
- `fixtureMissionAdapter` replays deterministic events.
- `MissionMap` renders proof nodes and selection.
- `ApprovalRail` renders the verified receipt and local-only approval flow.
- `SandboxDock` manages open/collapsed state, inspector tabs, and transcript focus.
- `SandboxWindow` renders the pop-out read-only view.
- Small shared primitives cover status labels, evidence nodes, and icon buttons; avoid card-inside-card nesting.

## Responsive Behavior

- `≥1280px`: full navigation labels, center workspace, and fixed approval rail.
- `1024–1279px`: navigation collapses to icons; approval rail remains right-aligned.
- `<1024px`: approval rail becomes a full-width panel between the mission map and terminal; map content pans horizontally rather than compressing labels.
- Mobile optimization is out of scope, but the page must remain readable and non-broken down to `768px`.

## Error and Safety States

- TrueForge unavailable: fixtures remain usable and the UI clearly says `Fixture replay`.
- Pop-out blocked: show an inline retry message without losing dock state.
- No selected node: show the full transcript without highlight.
- Approval before verification: button disabled and guard reason visible.
- Denial: no external write; patch and evidence remain inspectable.
- No component may claim a live sandbox when it is rendering fixture data.

## Verification

- Unit tests cover fixture reduction, selection-to-transcript highlighting, dock collapse persistence, inspector tabs, approval gating, approval confirmation, denial, and blocked pop-out handling.
- `npm test`, `npm run lint`, and `npm run build` pass from `apps/web`.
- Existing Python CI remains green.
- Render the reference state at `1440 × 1024` in the in-app browser.
- Compare the rendered implementation with option 1b at the same viewport and correct visible layout, typography, spacing, border, and color mismatches.
- Exercise the primary interactions and inspect browser console output.
- Record the final visual QA result in `apps/web/design-qa.md`; handoff requires `final result: passed` with no open P0–P2 issue.

## Acceptance Criteria

- The interface immediately reads as a purpose-built engineering instrument, not AI-generated SaaS UI.
- A new viewer can explain why two test modules were selected and see the exact red-to-green proof on one screen.
- The terminal dock sits below the mission map and the approval rail remains on the far right at the reference viewport.
- The sandbox is accurately labelled as TrueForge-native Daytona and visibly read-only.
- Approval is visibly impossible before matching red and green evidence exists.
- Every primary control works with deterministic fixtures.
- Local development requires no `.env` and exposes no credential to the frontend.
- No real GitHub, TrueForge, Daytona, or model write occurs from the fixture implementation.
