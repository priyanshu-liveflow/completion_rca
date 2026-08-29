"use client";

import { useEffect, useRef, useState } from "react";
import {
  Box,
  CheckCircle,
  Circle,
  FileText,
  GitBranch,
  Layers,
  Play,
  RefreshCw,
  Settings,
  Terminal,
} from "lucide-react";
import { useMission } from "./MissionProvider";
import MissionMap from "./MissionMap";
import RuntimeIndicator from "./RuntimeIndicator";
import SandboxDock from "./SandboxDock";
import styles from "./MissionControlPage.module.css";
import { writeSandboxSnapshot } from "../lib/sandboxSnapshot";

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

export default function MissionControlPage({
  readOnly = false,
}: {
  readOnly?: boolean;
}) {
  const {
    state,
    canApprove,
    selectNode,
    toggleDock,
    setTab,
    togglePopOut,
    approve,
    deny,
  } = useMission();
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [popOutError, setPopOutError] = useState<string | null>(null);
  const popOutRef = useRef<Window | null>(null);

  const isSubmitting = state.approvalSubmission === "submitting";

  const approvalGuard = !state.redObserved
    ? "Locked until a failing selected-test run is observed."
    : !state.greenObservedAfterRed
      ? "Locked while selected tests are red; waiting for green verification."
      : state.approvalError
        ? state.approvalError
        : state.approvalSubmission === "failed"
          ? "Approval resolution failed."
          : "The PR tool stayed locked while tests were red.";

  // Close the external window if this screen unmounts.
  useEffect(() => {
    return () => {
      if (popOutRef.current && !popOutRef.current.closed) {
        popOutRef.current.close();
      }
    };
  }, []);

  // Detect if the user closed the pop-out via browser chrome.
  useEffect(() => {
    if (!state.popOutOpen || !popOutRef.current) return;
    const id = window.setInterval(() => {
      if (popOutRef.current?.closed) {
        popOutRef.current = null;
        setPopOutError(null);
        togglePopOut();
      }
    }, 500);
    return () => window.clearInterval(id);
  }, [state.popOutOpen, togglePopOut]);

  // Publish the latest state to the pop-out while it is open.
  useEffect(() => {
    if (state.popOutOpen && popOutRef.current && !popOutRef.current.closed) {
      try {
        writeSandboxSnapshot(window.localStorage, state);
      } catch {
        // no-op
      }
    }
  }, [state]);

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

    try {
      writeSandboxSnapshot(window.localStorage, state);
    } catch {
      // localStorage may be unavailable; still attempt a default view
    }

    const popOut = window.open(
      "/sandbox",
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
  const onConfirm = async () => {
    const success = await approve();
    if (success) setConfirmOpen(false);
  };
  const onDeny = async () => {
    await deny();
  };

  const selectedNodeObj = state.nodes.find((n) => n.id === state.selectedNode);

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <div className={styles.logoDot} />
          <span>AGENTRADAR</span>
        </div>
        {!readOnly && (
          <>
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
          </>
        )}
        {readOnly && (
          <div className={styles.dockConnected}>
            <span className={styles.dockDot} />
            <span>TrueForge-native Daytona sandbox · read-only</span>
          </div>
        )}
        <div className={styles.spacer} />
        <div className={styles.time}>{state.currentTime}</div>
        {!readOnly && <div className={styles.docs}>DOCS</div>}
        {!readOnly && <Settings size={15} color="var(--ink-quiet)" />}
      </header>

      <main className={styles.main}>
        {!readOnly && (
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
              <span className={styles.navPinLabel}>Runtime</span>
              <RuntimeIndicator state={state} />
              <span className={styles.navPinRefresh}>Auto-refresh: on</span>
            </div>
          </nav>
        )}

        <div
          className={[
            styles.workspace,
            readOnly && styles.workspaceSandbox,
          ]
            .filter(Boolean)
            .join(" ")}
        >
          <MissionMap
            nodes={state.nodes}
            selectedNode={state.selectedNode}
            onSelect={selectNode}
          />

          <SandboxDock
            state={state}
            readOnly={readOnly}
            onToggleDock={toggleDock}
            onTabChange={setTab}
            onPopOut={readOnly ? undefined : onTogglePopOut}
          />

          {!readOnly && (
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
                    {state.approved
                      ? "Approved — local state only"
                      : "Denied"}
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
                  disabled={!canApprove || isSubmitting}
                  onClick={onApprove}
                >
                  {isSubmitting ? "Submitting..." : "Approve verified PR"}
                </button>
                <button
                  className={styles.btnSecondary}
                  onClick={onDeny}
                  disabled={state.approved !== null || isSubmitting}
                >
                  {isSubmitting ? "Submitting..." : "Deny"}
                </button>
                <p className={styles.note}>
                  No write to GitHub in this prototype
                </p>
              </div>
            </aside>
          )}
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
            {state.approvalError && (
              <div className={styles.dialogRow}>{state.approvalError}</div>
            )}
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
