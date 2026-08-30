"use client";

import { useMemo } from "react";
import { MissionProvider } from "./MissionProvider";
import MissionControlPage from "./MissionControlPage";
import { fixtureMissionAdapter } from "../lib/fixtureMissionAdapter";
import { createTrueForgeMissionAdapter } from "../lib/trueForgeMissionAdapter";
import { MissionMode } from "../lib/types";
import styles from "./MissionRuntime.module.css";

interface MissionRuntimeProps {
  mode: MissionMode;
}

/**
 * Selects the active mission adapter based on the requested mode.
 *
 * `fixture` is the default and requires no live TrueForge harness.
 * `live` connects to `/api/trueforge/...` but only claims a sandbox once
 * `sandbox.created` is observed.
 */
export default function MissionRuntime({ mode }: MissionRuntimeProps) {
  const adapter = useMemo(
    () =>
      mode === "live" ? createTrueForgeMissionAdapter() : fixtureMissionAdapter,
    [mode]
  );

  return (
    <MissionProvider adapter={adapter}>
      {mode === "fixture" && (
        // The fixture adapter schedules the whole recorded mission on
        // subscribe, so it starts replaying the moment this page mounts. That
        // is fine as a demo fallback and misleading without a label: an
        // observer sees a mission progressing and reasonably assumes work is
        // happening now. Say plainly that it is a recording.
        <div className={styles.replayBadge}>
          <span className={styles.replayDot} />
          recorded replay · not a live run
          <a className={styles.replayLink} href="/?live=1">
            go live
          </a>
        </div>
      )}
      <MissionControlPage />
    </MissionProvider>
  );
}
