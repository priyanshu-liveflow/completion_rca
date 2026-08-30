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
import ApprovalRail from "./ApprovalRail";
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
  const [popOutError, setPopOutError] = useState<string | null>(null);
  const popOutRef = useRef<Window | null>(null);

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

  const selectedNode =
    state.nodes.find((n) => n.id === state.selectedNode) ?? null;

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
        <div className={styles.time} suppressHydrationWarning>{state.currentTime}</div>
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
            <ApprovalRail
              state={state}
              canApprove={canApprove}
              selectedNode={selectedNode}
              popOutError={popOutError}
              onApprove={approve}
              onDeny={deny}
            />
          )}
        </div>
      </main>
    </div>
  );
}
