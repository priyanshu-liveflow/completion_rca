"use client";

import { useRouter } from "next/navigation";
import { useCallback, useState } from "react";

export type RepairPhase = "idle" | "running" | "done" | "failed";

// The script colours its output for a terminal. The browser has CSS, so the
// escape sequences are stripped and the meaning re-applied from the text.
const ANSI = /\u001b\[[0-9;]*m/g;

export interface StartOptions {
  /** "demo" builds a throwaway repo and repairs it. "verify" checks a real PR. */
  action: "demo" | "verify";
  /** demo only: use a fixed patch instead of calling a model. */
  canned?: boolean;
  /** verify only: the pull request to check. */
  pr?: number;
}

export interface RepairRun {
  phase: RepairPhase;
  lines: string[];
  start: (opts: StartOptions) => Promise<void>;
  dismiss: () => void;
}

/**
 * Drives one repair run and exposes its output as it arrives.
 *
 * A hook rather than a component so the controls and the output pane can live
 * in different parts of the layout — the buttons belong beside the session
 * list, the transcript belongs over the detail pane — without threading state
 * through props or lifting a component that renders in two places.
 */
export function useRepairRun(): RepairRun {
  const [phase, setPhase] = useState<RepairPhase>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const router = useRouter();

  const dismiss = useCallback(() => {
    setPhase("idle");
    setLines([]);
  }, []);

  const start = useCallback(
    async ({ action, canned = false, pr }: StartOptions) => {
      setPhase("running");
      setLines([]);

      const query = new URLSearchParams({ action });
      if (action === "demo") query.set("canned", canned ? "1" : "0");
      if (action === "verify" && pr !== undefined) query.set("pr", String(pr));

      let response: Response;
      try {
        response = await fetch(`/api/repair?${query}`, { method: "POST" });
      } catch (err) {
        setLines([`could not reach the server: ${String(err)}`]);
        setPhase("failed");
        return;
      }

      if (!response.body) {
        setLines(["the server returned no stream"]);
        setPhase("failed");
        return;
      }

      const reader = response.body.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      let exit = -1;

      // Read incrementally and repaint per chunk. Awaiting the whole response
      // would paint the finished log at once, which is the terminal behaviour
      // this pane exists to replace.
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });

        const parts = buffer.split("\n");
        buffer = parts.pop() ?? "";
        const cleaned: string[] = [];
        for (const raw of parts) {
          const line = raw.replace(ANSI, "");
          const marker = line.match(/^__EXIT__ (-?\d+)/);
          if (marker) {
            exit = Number(marker[1]);
            continue;
          }
          cleaned.push(line);
        }
        if (cleaned.length) setLines((prev) => [...prev, ...cleaned]);
      }

      setPhase(exit === 0 ? "done" : "failed");
      // The run wrote a new session and re-exported the JSON this page reads
      // on the server, so refresh to pull it into the sidebar.
      router.refresh();
    },
    [router],
  );

  return { phase, lines, start, dismiss };
}
