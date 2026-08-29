"use client";

import { useEffect, useState } from "react";
import MissionControlPage from "../components/MissionControlPage";
import { MissionProvider } from "../components/MissionProvider";
import { noOpAdapter } from "../lib/fixtureMissionAdapter";
import { MissionState } from "../lib/types";

export default function SandboxPage() {
  const [seed, setSeed] = useState<Partial<MissionState> | null>(null);
  const [hydrated, setHydrated] = useState(false);

  useEffect(() => {
    try {
      const raw = localStorage.getItem("ar-mission-snapshot");
      if (raw) {
        // Hydrating from localStorage is necessary because the snapshot is set
        // by the parent window immediately before opening this pop-out.
        // eslint-disable-next-line react-hooks/set-state-in-effect
        setSeed(JSON.parse(raw) as Partial<MissionState>);
      }
    } catch {
      // localStorage unavailable or invalid; fall back to default fixture state
    } finally {
      setHydrated(true);
    }
  }, []);

  if (!hydrated) return null;

  return (
    <MissionProvider adapter={noOpAdapter} seed={seed ?? undefined}>
      <MissionControlPage readOnly />
    </MissionProvider>
  );
}
