"use client";

import { MissionState } from "../lib/types";
import styles from "./MissionControlPage.module.css";

interface RuntimeIndicatorProps {
  state: MissionState;
}

interface RuntimeCopy {
  text: string;
  tone: "neutral" | "amber" | "green" | "red";
}

function runtimeCopy(state: MissionState): RuntimeCopy {
  const { runtime } = state;

  if (runtime.mode === "fixture") {
    return { text: "Fixture replay", tone: "neutral" };
  }

  switch (runtime.status) {
    case "idle":
      return { text: "TrueForge ready", tone: "neutral" };
    case "connecting":
      return { text: "Connecting to TrueForge", tone: "amber" };
    case "streaming":
      return state.runtime.sandboxId
        ? { text: "Daytona connected", tone: "green" }
        : { text: "Mission streaming", tone: "amber" };
    case "awaiting_approval":
      return { text: "Awaiting human approval", tone: "amber" };
    case "completed":
      return { text: "Mission completed", tone: "green" };
    case "failed":
      return {
        text: runtime.error ?? "TrueForge unavailable",
        tone: "red",
      };
    default:
      return { text: "TrueForge ready", tone: "neutral" };
  }
}

export default function RuntimeIndicator({ state }: RuntimeIndicatorProps) {
  const { text, tone } = runtimeCopy(state);
  const toneClass =
    tone === "neutral"
      ? styles.runtimeNeutral
      : tone === "amber"
        ? styles.runtimeAmber
        : tone === "green"
          ? styles.runtimeGreen
          : styles.runtimeRed;

  return (
    <span className={[styles.runtime, toneClass].filter(Boolean).join(" ")}>
      {text}
    </span>
  );
}
