import fs from "node:fs/promises";
import path from "node:path";

import styles from "./ReviewsPage.module.css";
import { ReviewRun, STATUS_META } from "./types";

// Read from disk on the server rather than fetching an API route. The
// verifier already writes this file, so a route would be a second copy of the
// same read plus a network hop, and the page would lose the ability to render
// before the client has any JavaScript.
async function loadRuns(): Promise<ReviewRun[]> {
  const file = path.join(process.cwd(), "public", "review-runs.json");
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as ReviewRun[];
  } catch {
    // No file yet is the ordinary state before the first run, not an error.
    return [];
  }
}

function DiffBlock({ diff }: { diff: string }) {
  return (
    <pre className={styles.diff}>
      <code>
        {diff.split("\n").map((line, i) => {
          const cls = line.startsWith("+++") || line.startsWith("---") || line.startsWith("diff ") || line.startsWith("@@")
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

export default async function ReviewsPage() {
  const runs = await loadRuns();

  return (
    <div className={styles.shell}>
      <header className={styles.header}>
        <span className={styles.title}>Review verification</span>
        <span className={styles.subtitle}>
          Every finding a reviewer left, located in the code graph, checked
          against the tests that reach it, and repaired only on a proven
          red-to-green.
        </span>
        <a className={styles.back} href="/">
          ← mission control
        </a>
      </header>

      {runs.length === 0 ? (
        <p className={styles.empty}>
          No runs stored yet. Run <code>python scripts/verify_findings.py --pr 20</code>{" "}
          and reload.
        </p>
      ) : (
        <div className={styles.body}>
          {runs.map((run) => (
            <section key={run.id} className={styles.run}>
              <div className={styles.runHead}>
                <span className={styles.runRepo}>
                  {run.repo} #{run.pr}
                </span>
                <span className={styles.runMeta}>{run.created_at}</span>
                <span className={styles.runMeta}>
                  {run.entries.length} finding(s)
                </span>
                {run.proven_repairs > 0 && (
                  <span className={`${styles.pill} ${styles.good}`}>
                    {run.proven_repairs} proven repair
                    {run.proven_repairs === 1 ? "" : "s"}
                  </span>
                )}
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
                {run.entries.map((entry, i) => {
                  const meta = STATUS_META[entry.verdict.status];
                  const finding = entry.verdict.finding;
                  return (
                    <article key={`${finding.id}-${i}`} className={styles.entry}>
                      <span className={`${styles.pill} ${styles[meta.tone]}`}>
                        {meta.label}
                      </span>

                      <div className={styles.entryMain}>
                        <h2 className={styles.findingTitle}>
                          {finding.url ? (
                            <a className={styles.prLink} href={finding.url}>
                              {finding.title}
                            </a>
                          ) : (
                            finding.title
                          )}
                        </h2>
                        <span className={styles.where}>
                          {finding.file_path}
                          {finding.line ? `:${finding.line}` : ""}
                          {entry.verdict.contact_points[0]
                            ? ` → ${entry.verdict.contact_points[0].function_name}`
                            : ""}
                        </span>
                        <p className={styles.why}>{entry.verdict.why}</p>

                        {entry.verdict.selection?.tests.length ? (
                          <div className={styles.tests}>
                            {entry.verdict.selection.tests.join("  ")}
                          </div>
                        ) : null}

                        {entry.repair && (
                          <div className={styles.repair}>
                            <div className={styles.repairHead}>
                              <span
                                className={`${styles.gate} ${
                                  entry.repair.proven ? styles.good : styles.bad
                                }`}
                              >
                                gate {entry.repair.proven ? "OPEN" : "SHUT"}
                              </span>
                              <span>
                                {entry.repair.before_failed} failing →{" "}
                                {entry.repair.after_passed} passing
                              </span>
                              <span>{entry.repair.files.join(", ")}</span>
                              {entry.repair.pr_url && (
                                <a className={styles.prLink} href={entry.repair.pr_url}>
                                  pull request ↗
                                </a>
                              )}
                            </div>
                            {entry.repair.diff && <DiffBlock diff={entry.repair.diff} />}
                          </div>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            </section>
          ))}
        </div>
      )}
    </div>
  );
}
