import fs from "node:fs/promises";
import path from "node:path";

import ReviewsClient from "./ReviewsClient";
import styles from "./ReviewsPage.module.css";
import { ReviewRun } from "./types";

// Read on every request, never at build time. `router.refresh()` after a run
// only shows the new session if this component actually re-reads the file;
// with the default caching it would re-render the same snapshot forever and
// the sidebar would look frozen for exactly the run the viewer just watched.
export const dynamic = "force-dynamic";

// Read from disk on the server rather than through an API route. The verifier
// already writes this file, so a route would be a second copy of the same read
// plus a network hop, and the page would lose the ability to render before the
// client has any JavaScript.
async function loadRuns(): Promise<ReviewRun[]> {
  const file = path.join(process.cwd(), "public", "review-runs.json");
  try {
    return JSON.parse(await fs.readFile(file, "utf8")) as ReviewRun[];
  } catch {
    // No file yet is the ordinary state before the first run, not an error.
    return [];
  }
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
          No runs stored yet. Run{" "}
          <code>python scripts/verify_findings.py --pr 20</code> and reload.
        </p>
      ) : (
        <ReviewsClient runs={runs} />
      )}
    </div>
  );
}
