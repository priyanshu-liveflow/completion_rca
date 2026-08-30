"use client";

import { useEffect, useLayoutEffect, useRef } from "react";
import { Maximize, Minus } from "lucide-react";
import { MissionState, TestLine } from "../lib/types";
import { useResizable } from "../lib/useResizable";
import styles from "./MissionControlPage.module.css";

interface SandboxDockProps {
  state: MissionState;
  readOnly?: boolean;
  onToggleDock: () => void;
  onTabChange: (tab: MissionState["activeTab"]) => void;
  onPopOut?: () => void;
  onResizeDock?: (e: React.MouseEvent<HTMLDivElement>) => void;
}

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

const tabs: { id: MissionState["activeTab"]; label: string }[] = [
  { id: "environment", label: "Environment" },
  { id: "files", label: "Files" },
  { id: "processes", label: "Processes" },
];

const fixtureInspector: Record<MissionState["activeTab"], string[]> = {
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

export default function SandboxDock({
  state,
  readOnly = false,
  onToggleDock,
  onTabChange,
  onPopOut,
  onResizeDock,
}: SandboxDockProps) {
  const inspector = useResizable({
    initial: 220,
    min: 120,
    max: 460,
    axis: "x",
  });
  const transcriptRef = useRef<HTMLDivElement>(null);
  const savedScrollRef = useRef(0);


  // Keep the terminal pinned to the bottom like VS Code unless the user
  // has intentionally scrolled up more than ~80px.
  const bottomThreshold = 80;
  useEffect(() => {
    const el = transcriptRef.current;
    if (!el) return;
    const distanceFromBottom =
      el.scrollHeight - el.scrollTop - el.clientHeight;
    if (distanceFromBottom < bottomThreshold) {
      el.scrollTop = el.scrollHeight;
    }
  }, [state.transcript]);

  useEffect(() => {
    if (!state.selectedNode || !transcriptRef.current) return;
    const el = transcriptRef.current.querySelector(
      `[data-node="${state.selectedNode}"]`
    );
    if (el) {
      el.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  }, [state.selectedNode]);

  useLayoutEffect(() => {
    if (state.dockOpen && transcriptRef.current) {
      transcriptRef.current.scrollTop = savedScrollRef.current;
    }
  }, [state.dockOpen]);

  const handleToggleDock = () => {
    if (transcriptRef.current) {
      savedScrollRef.current = transcriptRef.current.scrollTop;
    }
    onToggleDock();
  };

  const isLive = state.runtime.mode === "live";
  const title = isLive && state.runtime.sandboxId ? "Live sandbox" : "Sandbox";

  return (
    <section className={styles.dock}>
      {onResizeDock && (
        <div
          className={styles.dockResizer}
          onMouseDown={onResizeDock}
          title="Drag to resize dock"
        />
      )}
      <div className={styles.dockHeader}>
        <span className={styles.dockTitle}>{title}</span>
        <span className={styles.dockConnected}>
          <span className={styles.dockDot} />
          <span>
            {isLive ? "TrueForge / Daytona" : "Demo"}
          </span>
        </span>
        {readOnly && <span className={styles.dockMeta}>read-only</span>}
        <div className={styles.dockSpacer} />
        {!readOnly && onPopOut && (
          <button
            className={styles.dockBtn}
            onClick={onPopOut}
            title="Pop out sandbox"
          >
            <Maximize size={14} />
          </button>
        )}
        <button
          className={styles.dockBtn}
          onClick={handleToggleDock}
          title={state.dockOpen ? "Collapse sandbox" : "Expand sandbox"}
        >
          {state.dockOpen ? <Minus size={14} /> : "+"}
        </button>
      </div>
      <div
        className={[
          styles.dockBody,
          !state.dockOpen && styles.dockBodyHidden,
        ]
          .filter(Boolean)
          .join(" ")}
      >
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
        <aside className={styles.inspector} style={{ width: inspector.size }}>
          <div
            className={styles.inspectorResizer}
            onMouseDown={inspector.onMouseDown}
            title="Drag to resize inspector"
          />
          <div className={styles.inspectorTabs}>
            {tabs.map((t) => (
              <button
                key={t.id}
                className={
                  state.activeTab === t.id
                    ? `${styles.inspectorTab} ${styles.inspectorTabActive}`
                    : styles.inspectorTab
                }
                onClick={() => onTabChange(t.id)}
              >
                {t.label}
              </button>
            ))}
          </div>
          <div className={styles.inspectorBody}>
            {isLive ? (
              <div>Not reported by the TrueForge stream</div>
            ) : (
              fixtureInspector[state.activeTab].map((row, i) => (
                <div key={i}>{row}</div>
              ))
            )}
          </div>
        </aside>
      </div>
    </section>
  );
}
