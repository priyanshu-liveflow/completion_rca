/** Mirrors `contracts/review.py`. Kept in step with it by hand, deliberately:
 *  a generated client would be a build step for four types that change rarely.
 */
export type FindingStatus =
  | "confirmed"
  | "unreproduced"
  | "uncovered"
  | "inconclusive"
  | "unlocatable";

export interface ContactPoint {
  symbol: string;
  function_name: string;
  fid: number;
  file_path: string;
  line: number | null;
}

export interface ReviewFinding {
  id: string;
  reviewer: string;
  file_path: string;
  line: number | null;
  title: string;
  body: string;
  url: string | null;
}

export interface TestSelection {
  tests: string[];
  strategy: string;
  reached_from: string[];
  truncated: boolean;
}

export interface TestReport {
  id: string;
  passed: number;
  failed: number;
  errors: number;
  duration_s: number;
  raw_tail: string;
  exit_code: number | null;
}

export interface FindingVerdict {
  finding: ReviewFinding;
  contact_points: ContactPoint[];
  selection: TestSelection | null;
  report: TestReport | null;
  status: FindingStatus;
  why: string;
}

export interface RepairRecord {
  diff: string;
  files: string[];
  applied: boolean;
  proven: boolean;
  before_failed: number;
  after_passed: number;
  reason: string;
  pr_url: string | null;
}

export interface ReviewEntry {
  verdict: FindingVerdict;
  repair: RepairRecord | null;
}

export interface ReviewRun {
  id: string;
  repo: string;
  pr: number;
  created_at: string;
  repo_key: string;
  entries: ReviewEntry[];
  counts: Record<FindingStatus, number>;
  proven_repairs: number;
}

/** Verdict presentation. `confirmed` is the only alarming one: it means a
 *  test really failed where the reviewer said it would. The three
 *  can't-say verdicts are deliberately quiet rather than red, because
 *  colouring them as failures is exactly the false-positive framing the
 *  four-verdict split exists to avoid. */
export const STATUS_META: Record<
  FindingStatus,
  { label: string; tone: "bad" | "good" | "quiet" | "warn" }
> = {
  confirmed: { label: "confirmed", tone: "bad" },
  unreproduced: { label: "unreproduced", tone: "good" },
  uncovered: { label: "uncovered", tone: "warn" },
  inconclusive: { label: "inconclusive", tone: "quiet" },
  unlocatable: { label: "unlocatable", tone: "quiet" },
};
