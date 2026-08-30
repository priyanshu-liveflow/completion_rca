"use client";

import { useEffect, useRef, useState } from "react";
import { GitBranch, Settings } from "lucide-react";
import { useMission } from "./MissionProvider";
import MissionMap from "./MissionMap";
import RuntimeIndicator from "./RuntimeIndicator";
import SandboxDock from "./SandboxDock";
import ApprovalRail from "./ApprovalRail";
import styles from "./MissionControlPage.module.css";
import { writeSandboxSnapshot } from "../lib/sandboxSnapshot";

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
  const [dockHeight, setDockHeight] = useState(360);
  const [railWidth, setRailWidth] = useState(270);
  const popOutRef = useRef<Window | null>(null);
  const workspaceRef = useRef<HTMLDivElement | null>(null);

  const startResizeRail = (e: React.MouseEvent<HTMLDivElement>) => {
    e.preventDefault();
    document.body.style.userSelect = "none";
    const startX = e.clientX;
    const startW = railWidth;
    const onMove = (ev: MouseEvent) => {
      const newW = Math.min(
        Math.max(startW + (startX - ev.clientX), 220),
        520
      );
      setRailWidth(newW);
    };
    const onUp = () => {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

  const startResizeDock = (e: React.MouseEvent<HTMLDivElement>) => {
    if (!workspaceRef.current) return;
    e.preventDefault();
    document.body.style.userSelect = "none";
    const startY = e.clientY;
    const startH = dockHeight;
    const maxH = workspaceRef.current.clientHeight - 120;
    const onMove = (ev: MouseEvent) => {
      const newH = Math.min(
        Math.max(startH + (startY - ev.clientY), 120),
        maxH
      );
      setDockHeight(newH);
    };
    const onUp = () => {
      document.body.style.userSelect = "";
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
  };

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
            <div className={styles.headerStatus}>
              <RuntimeIndicator state={state} />
            </div>
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
        {!readOnly && (
          <button type="button" className={styles.iconBtn} title="Settings">
            <Settings size={15} color="var(--ink-quiet)" />
          </button>
        )}
      </header>

      <main className={styles.main}>
        <div
          ref={workspaceRef}
          className={[
            styles.workspace,
            readOnly && styles.workspaceSandbox,
          ]
            .filter(Boolean)
            .join(" ")}
          style={{
            gridTemplateColumns: readOnly ? undefined : `1fr ${railWidth}px`,
            gridTemplateRows: `minmax(120px, 1fr) ${dockHeight}px`,
          }}
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
            onResizeDock={startResizeDock}
          />

          {!readOnly && (
            <ApprovalRail
              state={state}
              canApprove={canApprove}
              selectedNode={selectedNode}
              popOutError={popOutError}
              onApprove={approve}
              onDeny={deny}
              onResizeRail={startResizeRail}
            />
          )}
        </div>
      </main>
    </div>
  );
}
