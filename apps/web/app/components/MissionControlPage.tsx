"use client";

import { useEffect, useRef, useState } from "react";
import type { CSSProperties } from "react";
import { GitBranch, Settings } from "lucide-react";
import { useResizable } from "../lib/useResizable";
import { useMission } from "./MissionProvider";
import MissionMap from "./MissionMap";
import RuntimeIndicator from "./RuntimeIndicator";
import SandboxDock from "./SandboxDock";
import ApprovalRail from "./ApprovalRail";
import styles from "./MissionControlPage.module.css";
import { writeSandboxSnapshot } from "../lib/sandboxSnapshot";

/** Floor for the proof-chain map. Fed to both the grid and the resize clamps. */
const MAP_MIN_WIDTH = 360;
const MAP_MIN_HEIGHT = 120;

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
  const workspaceRef = useRef<HTMLDivElement | null>(null);
  const rail = useResizable({
    initial: 270,
    min: 220,
    max: 520,
    axis: "x",
    label: "Resize approval rail",
    // Mirrors the map column's declared minimum below.
    bounds: { ref: workspaceRef, reserve: MAP_MIN_WIDTH },
  });
  const dock = useResizable({
    initial: 360,
    min: 120,
    axis: "y",
    label: "Resize sandbox dock",
    // Mirrors the map row's declared minimum below.
    bounds: { ref: workspaceRef, reserve: MAP_MIN_HEIGHT },
  });



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
          // Values only. Writing the tracks themselves inline would outrank
          // every class and media query, which is exactly how the sandbox
          // variant and the sub-1024 layout were being defeated.
          style={
            {
              "--rail-w": `${rail.size}px`,
              "--dock-h": `${dock.size}px`,
              "--map-min-w": `${MAP_MIN_WIDTH}px`,
              "--map-min-h": `${MAP_MIN_HEIGHT}px`,
            } as CSSProperties
          }
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
            dockSeparator={dock.separatorProps}
          />

          {!readOnly && (
            <ApprovalRail
              state={state}
              canApprove={canApprove}
              selectedNode={selectedNode}
              popOutError={popOutError}
              onApprove={approve}
              onDeny={deny}
              railSeparator={rail.separatorProps}
            />
          )}
        </div>
      </main>
    </div>
  );
}
