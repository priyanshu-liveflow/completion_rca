"use client";

import { useEffect, useState } from "react";
import { MissionProvider } from "../components/MissionProvider";
import { useMission } from "../components/MissionProvider";
import SandboxDock from "../components/SandboxDock";
import { noOpAdapter } from "../lib/fixtureMissionAdapter";
import {
  readSandboxSnapshot,
  subscribeSandboxSnapshot,
} from "../lib/sandboxSnapshot";
import { MissionState } from "../lib/types";
import styles from "../components/MissionControlPage.module.css";

function SandboxWindow() {
  const { state, toggleDock, setTab } = useMission();

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <div className={styles.logo}>
          <div className={styles.logoDot} />
          <span>AGENTRADAR</span>
        </div>
        <div className={styles.dockConnected}>
          <span className={styles.dockDot} />
          <span>TrueForge-native Daytona sandbox · read-only</span>
        </div>
        <div className={styles.spacer} />
        <div className={styles.time}>{state.currentTime}</div>
      </header>

      <main
        className={[styles.main, styles.workspace, styles.workspaceSandbox]
          .filter(Boolean)
          .join(" ")}
      >
        <SandboxDock
          state={state}
          readOnly
          onToggleDock={toggleDock}
          onTabChange={setTab}
        />
      </main>
    </div>
  );
}

export default function SandboxPage() {
  const [seed, setSeed] = useState<Partial<MissionState> | null>(null);
  const [tick, setTick] = useState(0);

  useEffect(() => {
    if (typeof window === "undefined") return;

    const initial = readSandboxSnapshot(window.localStorage);
    if (initial) {
      // eslint-disable-next-line react-hooks/set-state-in-effect
      setSeed(initial);
      setTick((t) => t + 1);
    }

    const unsubscribe = subscribeSandboxSnapshot((snapshot) => {
      setSeed(snapshot);
      setTick((t) => t + 1);
    });
    return unsubscribe;
  }, []);

  return (
    <MissionProvider key={tick} adapter={noOpAdapter} seed={seed ?? undefined}>
      <SandboxWindow />
    </MissionProvider>
  );
}
