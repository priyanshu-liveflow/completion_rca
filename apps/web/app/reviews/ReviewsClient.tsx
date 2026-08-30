"use client";

import { useEffect, useRef, useState } from "react";

import styles from "./ReviewsPage.module.css";
import { ReviewEntry, ReviewRun, STATUS_META } from "./types";
import { useRepairRun } from "./useRepairRun";

/** Lines the transcript should call out rather than render as plain output. */
function toneOf(line: string): string {
  if (/Gate:\s*OPEN|repair is proven/i.test(line)) return styles.lineGood;
  if (/Gate:\s*SHUT|rejected|did not apply|Traceback/i.test(line)) {
    return styles.lineBad;
  }
  if (/CONFIRMED/.test(line)) return styles.lineBad;
  if (/^\s*\d\.\s/.test(line)) return styles.lineStep;
  if (/^\s{2,}\+/.test(line)) return styles.add;
  if (/^\s{2,}-\s/.test(line)) return styles.del;
  return styles.ctx;
}

function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre className={styles.diff}>
      <code>
        {diff.split("\n").map((line, i) => {
          const cls =
            line.startsWith("+++") ||
            line.startsWith("---") ||
            line.startsWith("diff ") ||
            line.startsWith("@@")
              ? styles.meta
              : line.startsWith("+")
                ? styles.add
                : line.startsWith("-")
                  ? styles.del
                  : styles.ctx;
          return (
            <span key={i} className={cls}>
              {line || " "}
            </span>
          );
        })}
      </code>
    </pre>
  );
}

function Entry({ entry }: { entry: ReviewEntry }) {
  const [open, setOpen] = useState(false);
  const meta = STATUS_META[entry.verdict.status];
  const finding = entry.verdict.finding;
  const tests = entry.verdict.selection?.tests ?? [];

  return (
    <article className={styles.entry}>
      <span className={`${styles.pill} ${styles[meta.tone]}`}>{meta.label}</span>

      <div className={styles.entryMain}>
        <h3 className={styles.findingTitle}>{finding.title}</h3>

        <span className={styles.where}>
          {finding.file_path}
          {finding.line ? `:${finding.line}` : ""}
          {entry.verdict.contact_points[0]
            ? ` → ${entry.verdict.contact_points[0].function_name}`
            : ""}
        </span>

        <p className={styles.why}>{entry.verdict.why}</p>

        {entry.verdict.report && (
          <div className={styles.counts}>
            <span>passed {entry.verdict.report.passed}</span>
            <span>failed {entry.verdict.report.failed}</span>
            <span>errors {entry.verdict.report.errors}</span>
            <span>{entry.verdict.report.duration_s.toFixed(2)}s</span>
          </div>
        )}

        {entry.repair && (
          <div className={styles.repair}>
            <div className={styles.repairHead}>
              <span
                className={`${styles.gate} ${
                  entry.repair.proven ? styles.goodText : styles.badText
                }`}
              >
                gate {entry.repair.proven ? "OPEN" : "SHUT"}
              </span>
              <span className={styles.repairMeta}>
                {entry.repair.before_failed} failing → {entry.repair.after_passed} passing
              </span>
              <span className={styles.repairMeta}>{entry.repair.files.join(", ")}</span>
              {entry.repair.pr_url && (
                <a className={styles.prLink} href={entry.repair.pr_url}>
                  pull request ↗
                </a>
              )}
            </div>
            {entry.repair.diff && <DiffBlock diff={entry.repair.diff} />}
          </div>
        )}

        {tests.length > 0 && (
          <div className={styles.testsWrap}>
            <button
              type="button"
              className={styles.disclosure}
              onClick={() => setOpen((v) => !v)}
              aria-expanded={open}
            >
              {open ? "▾" : "▸"} {tests.length} selected test
              {tests.length === 1 ? "" : "s"}
              {entry.verdict.selection?.strategy
                ? ` · ${entry.verdict.selection.strategy}`
                : ""}
            </button>
            {open && (
              <ul className={styles.testList}>
                {tests.map((t) => (
                  <li key={t}>{t}</li>
                ))}
              </ul>
            )}
          </div>
        )}
      </div>
    </article>
  );
}

export default function ReviewsClient({ runs }: { runs: ReviewRun[] }) {
  const [selected, setSelected] = useState(0);
  const run = runs[selected];

  const repair = useRepairRun();
  const paneRef = useRef<HTMLPreElement>(null);

  // Follow the tail as lines arrive, the way a terminal does.
  useEffect(() => {
    const pane = paneRef.current;
    if (pane) pane.scrollTop = pane.scrollHeight;
  }, [repair.lines]);

  const busy = repair.phase === "running";

  return (
    <div className={styles.layout}>
      <aside className={styles.sidebar}>
        <div className={styles.runnerBox}>
          <div className={styles.sidebarHead}>Run a repair</div>
          <p className={styles.runnerHint}>
            Builds a repo with one real defect, confirms it with a failing
            test, patches it, re-runs. The gate opens only on red-to-green.
          </p>
          <div className={styles.runnerButtons}>
            <button
              type="button"
              className={styles.runButton}
              disabled={busy}
              onClick={() => repair.start(false)}
            >
              {busy ? "running…" : "Run with model"}
            </button>
            <button
              type="button"
              className={styles.runButtonQuiet}
              disabled={busy}
              onClick={() => repair.start(true)}
            >
              Run offline
            </button>
          </div>
        </div>

        <div className={styles.sidebarHead}>Sessions</div>
        <nav className={styles.sessionList}>
          {runs.map((r, i) => {
            const confirmed = r.counts.confirmed ?? 0;
            return (
              <button
                type="button"
                key={r.id}
                onClick={() => setSelected(i)}
                className={`${styles.session} ${
                  i === selected ? styles.sessionActive : ""
                }`}
              >
                <span className={styles.sessionRepo}>
                  {r.repo.split("/").pop()}
                  {r.pr > 0 ? ` #${r.pr}` : ""}
                </span>
                <span className={styles.sessionMeta}>
                  {r.created_at.replace("T", " ").replace("+00:00", "")}
                </span>
                <span className={styles.sessionTally}>
                  <span className={styles.sessionCount}>
                    {r.entries.length} finding{r.entries.length === 1 ? "" : "s"}
                  </span>
                  {confirmed > 0 && (
                    <span className={`${styles.dot} ${styles.bad}`}>{confirmed}</span>
                  )}
                  {r.proven_repairs > 0 && (
                    <span className={`${styles.dot} ${styles.good}`}>
                      {r.proven_repairs} fixed
                    </span>
                  )}
                </span>
              </button>
            );
          })}
        </nav>
      </aside>

      <main className={styles.detail}>
        {run && (
          <>
            <div className={styles.detailHead}>
              <span className={styles.detailRepo}>
                {run.repo}
                {run.pr > 0 ? ` #${run.pr}` : ""}
              </span>
              <span className={styles.detailMeta}>{run.created_at}</span>
              <span className={styles.detailMeta}>graph: {run.repo_key}</span>
              <span className={styles.tally}>
                {Object.entries(run.counts)
                  .filter(([, n]) => n > 0)
                  .map(([status, n]) => {
                    const meta = STATUS_META[status as keyof typeof STATUS_META];
                    return (
                      <span
                        key={status}
                        className={`${styles.pill} ${styles[meta?.tone ?? "quiet"]}`}
                      >
                        {n} {meta?.label ?? status}
                      </span>
                    );
                  })}
              </span>
            </div>

            <div className={styles.entries}>
              {run.entries.map((entry, i) => (
                <Entry key={`${entry.verdict.finding.id}-${i}`} entry={entry} />
              ))}
            </div>
          </>
        )}
      </main>

      {repair.phase !== "idle" && (
        <section className={styles.transcript}>
          <div className={styles.transcriptHead}>
            <span className={styles.transcriptTitle}>Repair run</span>
            <span
              className={
                repair.phase === "running"
                  ? styles.ctx
                  : repair.phase === "done"
                    ? styles.lineGood
                    : styles.lineBad
              }
            >
              {repair.phase === "running" ? "running…" : repair.phase}
            </span>
            <button
              type="button"
              className={styles.dismiss}
              onClick={repair.dismiss}
              disabled={busy}
              title={busy ? "wait for the run to finish" : "dismiss"}
              aria-label="Dismiss the repair transcript"
            >
              ×
            </button>
          </div>
          <pre ref={paneRef} className={styles.transcriptPane}>
            <code>
              {repair.lines.map((line, i) => (
                <span key={i} className={toneOf(line)}>
                  {line || " "}
                </span>
              ))}
            </code>
          </pre>
        </section>
      )}
    </div>
  );
}
