"use client";

import { useMemo } from "react";
import { MissionProvider } from "./MissionProvider";
import MissionControlPage from "./MissionControlPage";
import { fixtureMissionAdapter } from "../lib/fixtureMissionAdapter";
import { createTrueForgeMissionAdapter } from "../lib/trueForgeMissionAdapter";
import { MissionMode } from "../lib/types";

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

  const runtimeLabel = mode === "live" ? "live" : "fixture replay";

  return (
    <MissionProvider adapter={adapter}>
      <MissionControlPage runtimeLabel={runtimeLabel} />
    </MissionProvider>
  );
}
