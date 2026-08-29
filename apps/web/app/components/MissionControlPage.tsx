"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  ArrowRight,
  Box,
  CheckCircle,
  Circle,
  FileText,
  GitBranch,
  Layers,
  Maximize,
  Minus,
  Play,
  RefreshCw,
  Settings,
  Terminal,
} from "lucide-react";
import { useMission } from "./MissionProvider";
import styles from "./MissionControlPage.module.css";
import { TestLine } from "../lib/types";
import { canApproveMission } from "../lib/missionReducer";

const navItems = [
  { icon: Circle, label: "Mission Control", active: true },
  { icon: GitBranch, label: "Graph" },
  { icon: FileText, label: "Events" },
  { icon: Box, label: "Agents" },
  { icon: Terminal, label: "Sandbox" },
  { icon: CheckCircle, label: "Commits" },
  { icon: Play, label: "Tests" },
  { icon: Layers, label: "Artifacts" },
  { icon: Settings, label: "Settings" },
];

const tabs = [
  { id: "environment" as const, label: "Environment" },
  { id: "files" as const, label: "Files" },
  { id: "processes" as const, label: "Processes" },
];

const inspectorContent: Record<string, string[]> = {
  environment: [
    "DAYTONA_IMAGE=debian-13-python-3.14",
    "PIP_NO_BUILD_ISOLATION=1",
    "PYTHONPATH=/workspace/repo",
    "TF_SESSION=sxn-72a9f0",
  ],
  files: [
    "/workspace/repo/src/intervals/server.py",
    "/workspace/repo/src/intervals/mcp.py",
    "/workspace/repo/tests/test_mcp.py",
    "/workspace/repo/tests/test_server.py",
  ],
  processes: [
    "pytest (pid 1842)",
    "git (pid 881)",
    "python -c apply patch (pid 1922)",
  ],
};

function lineClass(kind: TestLine["kind"]) {
  switch (kind) {
    case "command":
      return styles.lineCommand;
    case "stderr":
      return styles.lineStderr;
    case "status":
      return styles.lineStatus;
    case "timing":
      return styles.lineTiming;
    default:
      return "";
  }
}

export default function MissionControlPage() {
  const { state, selectNode, toggleDock, setTab, togglePopOut, approve, deny } =
    useMission();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [popOutError, setPopOutError] = useState<string | null>(null);
  const transcriptRef = useRef<HTMLDivElement>(null);
  const popOutRef = useRef<Window | null>(null);

  const canApprove = useMemo(() => canApproveMission(state), [state]);

  const approvalGuard = !state.redObserved
    ? "Locked until a failing selected-test run is observed."
    : !state.greenObservedAfterRed
      ? "Locked while selected tests are red; waiting for green verification."
      : "The PR tool stayed locked while tests were red.";

  // Scroll selected node transcript lines into view
  useEffect(() => {
    if (!state.selectedNode || !transcriptRef.current) return;
    const el = transcriptRef.current.querySelector(
      `[data-node="${state.selectedNode}"]`
    );
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [state.selectedNode]);

  // Close the external window if this screen unmounts.
  useEffect(() => {
    return () => {
      if (popOutRef.current && !popOutRef.current.closed) {
        popOutRef.current.close();
      }
    };
  }, []);

  const onTogglePopOut = () => {
    if (state.popOutOpen) {
      if (popOutRef.current && !popOutRef.current.closed) {
        popOutRef.current.close();
      }
      popOutRef.current = null;
      setPopOutError(null);
      togglePopOut();
      return;
    }

    const popOut = window.open(
      "/",
      "AgentRadarSandbox",
      "width=900,height=600,menubar=no,toolbar=no,location=no"
    );
    if (!popOut) {
      setPopOutError("Pop-out blocked. Allow pop-ups to open the sandbox.");
      return;
    }
    popOutRef.current = popOut;
    setPopOutError(null);
    togglePopOut();
  };

  const onApprove = () => setConfirmOpen(true);
  const onConfirm = () => {
    approve();
    setConfirmOpen(false);
  };

  const selectedNodeObj = state.nodes.find((n) => n.id === state.selectedNode);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <div className={styles.logoDot} />
          <span>AGENTRADAR</span>
        </div>
        <div className={styles.repo}>
          <GitBranch size={12} />
          <span>mvilanova/intervals-mcp-server</span>
        </div>
        <div className={styles.missionId}>{state.id}</div>
        {state.restored && (
          <div className={styles.restored}>
            <RefreshCw size={10} />
            <span>Session restored</span>
          </div>
        )}
        <div className={styles.spacer} />
        <div className={styles.time}>{state.currentTime}</div>
        <div className={styles.docs}>DOCS</div>
        <Settings size={15} color="var(--ink-quiet)" />
      </header>

      <main className={styles.main}>
        <nav className={styles.nav}>
          <div className={styles.navList}>
            {navItems.map((it) => (
              <div
                key={it.label}
                className={
                  it.active
                    ? `${styles.navItem} ${styles.navItemActive}`
                    : styles.navItem
                }
              >
                <it.icon size={13} />
                <span>{it.label}</span>
              </div>
            ))}
          </div>
          <div className={styles.navPin}>
            <span>State: fixture replay</span>
            <span>Auto-refresh: on</span>
          </div>
        </nav>

        <div className={styles.workspace}>
          <section className={styles.map}>
            <h2 className={styles.mapTitle}>
              Dependency upgrade proof chain
            </h2>
            <div className={styles.chain}>
              {state.nodes.map((node) => (
                <div
                  key={node.id}
                  className={[
                    styles.node,
                    node.status === "amber" && styles.nodeAmber,
                    node.status === "red" && styles.nodeRed,
                    node.status === "green" && styles.nodeGreen,
                    state.selectedNode === node.id && styles.nodeSelected,
                  ]
                    .filter(Boolean)
                    .join(" ")}
                  onClick={() =>
                    selectNode(state.selectedNode === node.id ? null : node.id)
                  }
                >
                  <div className={styles.nodeRole}>{node.role}</div>
                  <div className={styles.nodeLabel}>{node.label}</div>
                  <div className={styles.nodeDetail}>{node.detail}</div>
                  {node.status === "static" && (
                    <span className={styles.staticBadge}>static analysis</span>
                  )}
                </div>
              ))}
              {state.nodes.map((_, i) =>
                i < state.nodes.length - 1 ? (
                  <div key={i} className={styles.arrow}>
                    <ArrowRight size={16} />
                  </div>
                ) : null
              )}
            </div>
          </section>

          <section className={styles.dock}>
            <div className={styles.dockHeader}>
              <span className={styles.dockTitle}>Live Sandbox</span>
              <span className={styles.dockConnected}>
                <span className={styles.dockDot} />
                <span>TrueForge-native Daytona</span>
              </span>
              <span className={styles.dockMeta}>(read-only · fixture)</span>
              <div className={styles.dockSpacer} />
              <button
                className={styles.dockBtn}
                onClick={onTogglePopOut}
                title="Pop out sandbox"
              >
                <Maximize size={14} />
              </button>
              <button
                className={styles.dockBtn}
                onClick={toggleDock}
                title="Collapse sandbox"
              >
                <Minus size={14} />
              </button>
            </div>
            <div className={styles.dockBody}>
              <div ref={transcriptRef} className={styles.transcript}>
                {state.transcript.map((line) => (
                  <div
                    key={line.id}
                    data-node={line.nodeId}
                    className={[
                      styles.line,
                      lineClass(line.kind),
                      line.nodeId && line.nodeId === state.selectedNode
                        ? styles.lineHighlighted
                        : "",
                    ].join(" ")}
                  >
                    {line.kind === "command" && "$ "}
                    {line.text}
                  </div>
                ))}
              </div>
              <aside className={styles.inspector}>
                <div className={styles.inspectorTabs}>
                  {tabs.map((t) => (
                    <button
                      key={t.id}
                      className={
                        state.activeTab === t.id
                          ? `${styles.inspectorTab} ${styles.inspectorTabActive}`
                          : styles.inspectorTab
                      }
                      onClick={() => setTab(t.id)}
                    >
                      {t.label}
                    </button>
                  ))}
                </div>
                <div className={styles.inspectorBody}>
                  {inspectorContent[state.activeTab].map((row, i) => (
                    <div key={i}>{row}</div>
                  ))}
                </div>
              </aside>
            </div>
          </section>

          <aside className={styles.rail}>
            <div className={styles.railTitle}>Human approval required</div>
            <div className={styles.railSection}>
              <div className={styles.railHeading}>Verified patch receipt</div>
              <div className={styles.railRow}>
                Base commit: <code>{state.indexedCommit.slice(0, 12)}</code>
              </div>
              <div className={styles.railRow}>
                Dependency: {state.dependency}{" "}
                <code>
                  {state.baselineVersion} → {state.breakingVersion}
                </code>
              </div>
              <div className={styles.railRow}>
                Files changed: <strong>4</strong>
              </div>
              <div className={styles.railRow}>
                Before: <span style={{ color: "var(--oxide)" }}>exit 2</span>
              </div>
              <div className={styles.railRow}>
                After: <span style={{ color: "var(--mineral)" }}>61 passed</span>
              </div>
            </div>
            <div className={styles.guard} aria-live="polite">
              {approvalGuard}
            </div>
            {selectedNodeObj && (
              <div className={styles.railSection}>
                <div className={styles.railHeading}>Selected</div>
                <div className={styles.railRow}>
                  {selectedNodeObj.role}: {selectedNodeObj.label}
                </div>
              </div>
            )}
            {state.approved !== null && (
              <div
                className={styles.railSection}
                style={{
                  color: state.approved ? "var(--mineral)" : "var(--oxide)",
                }}
              >
                <div className={styles.railHeading}>Decision</div>
                <div className={styles.railRow}>
                  {state.approved ? "Approved — local state only" : "Denied"}
                </div>
              </div>
            )}
            {popOutError && (
              <div className={styles.railSection}>
                <div className={styles.railHeading}>Pop-out</div>
                <div className={styles.railRow}>{popOutError}</div>
              </div>
            )}
            <div className={styles.actions}>
              <button
                className={styles.btnPrimary}
                disabled={!canApprove}
                onClick={onApprove}
              >
                Approve verified PR
              </button>
              <button
                className={styles.btnSecondary}
                onClick={deny}
                disabled={state.approved !== null}
              >
                Deny
              </button>
              <p className={styles.note}>No write to GitHub in this prototype</p>
            </div>
          </aside>
        </div>
      </main>

      {confirmOpen && (
        <div
          className={styles.dialogOverlay}
          onClick={(e) => e.currentTarget === e.target && setConfirmOpen(false)}
        >
          <div className={styles.dialog}>
            <h3>Approve verified pull request</h3>
            <div className={styles.dialogRow}>
              Repository: <code>{state.repo}</code>
            </div>
            <div className={styles.dialogRow}>
              Target branch: <code>main</code>
            </div>
            <div className={styles.dialogRow}>
              Patch summary: import path update for 4 files
            </div>
            <div className={styles.dialogRow}>
              Test receipt: <code>61 passed</code> after red reproduction
            </div>
            <div className={styles.dialogActions}>
              <button
                className={styles.btnSecondary}
                onClick={() => setConfirmOpen(false)}
              >
                Cancel
              </button>
              <button className={styles.btnPrimary} onClick={onConfirm}>
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
