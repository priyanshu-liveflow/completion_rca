"use client";

import { useRouter } from "next/navigation";
import { useCallback, useRef, useState } from "react";

import styles from "./ReviewsPage.module.css";

type Phase = "idle" | "running" | "done" | "failed";

// The script prints ANSI colour for a terminal. The browser has CSS, so the
// escape sequences are stripped and the meaning re-applied from the text.
const ANSI = /\u001b\[[0-9;]*m/g;

function toneOf(line: string): string {
  if (/Gate:\s*OPEN|repair is proven/i.test(line)) return styles.lineGood;
  if (/Gate:\s*SHUT|rejected|did not apply|Traceback/i.test(line)) {
    return styles.lineBad;
  }
  if (/CONFIRMED/.test(line)) return styles.lineBad;
  if (/^\s*\d\.\s/.test(line)) return styles.lineStep;
  if (/^\s*\+/.test(line)) return styles.add;
  if (/^\s*-{1,2}\s|^\s*-\s{4}/.test(line)) return styles.del;
  return styles.ctx;
}

export default function RepairRunner() {
  const [phase, setPhase] = useState<Phase>("idle");
  const [lines, setLines] = useState<string[]>([]);
  const paneRef = useRef<HTMLPreElement>(null);
  const router = useRouter();

  const run = useCallback(
    async (canned: boolean) => {
      setPhase("running");
      setLines([]);

      let response: Response;
      try {
        response = await fetch(`/api/repair?canned=${canned ? "1" : "0"}`, {
          method: "POST",
        });
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
        if (cleaned.length) {
          setLines((prev) => [...prev, ...cleaned]);
          requestAnimationFrame(() => {
            const pane = paneRef.current;
            if (pane) pane.scrollTop = pane.scrollHeight;
          });
        }
      }

      setPhase(exit === 0 ? "done" : "failed");
      // The run wrote a new session and re-exported the JSON this page reads
      // on the server, so refresh to pull it into the sidebar.
      router.refresh();
    },
    [router],
  );

  const busy = phase === "running";

  return (
    <div className={styles.runner}>
      <div className={styles.runnerHead}>
        <span className={styles.runnerTitle}>Run a repair</span>
        <span className={styles.runnerHint}>
          Builds a repo with one real defect, confirms it with a failing test,
          patches it, re-runs. The gate opens only on red-to-green.
        </span>
        <button
          type="button"
          className={styles.runButton}
          disabled={busy}
          onClick={() => run(false)}
        >
          {busy ? "running…" : "Run with model"}
        </button>
        <button
          type="button"
          className={styles.runButtonQuiet}
          disabled={busy}
          onClick={() => run(true)}
        >
          Run offline
        </button>
        {phase === "done" && <span className={styles.lineGood}>finished</span>}
        {phase === "failed" && <span className={styles.lineBad}>failed</span>}
      </div>

      {lines.length > 0 && (
        <pre ref={paneRef} className={styles.runnerPane}>
          <code>
            {lines.map((line, i) => (
              <span key={i} className={toneOf(line)}>
                {line || " "}
              </span>
            ))}
          </code>
        </pre>
      )}
    </div>
  );
}
