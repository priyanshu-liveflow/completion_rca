"use client";

import { useEffect, useRef, useState } from "react";
import { MissionState, ProofNode } from "../lib/types";
import styles from "./MissionControlPage.module.css";

interface ApprovalRailProps {
  state: MissionState;
  canApprove: boolean;
  selectedNode: ProofNode | null;
  popOutError: string | null;
  onApprove: () => Promise<boolean>;
  onDeny: () => Promise<boolean>;
  onResizeRail?: (e: React.MouseEvent<HTMLDivElement>) => void;
}

export default function ApprovalRail({
  state,
  canApprove,
  selectedNode,
  popOutError,
  onApprove,
  onDeny,
  onResizeRail,
}: ApprovalRailProps) {
  const [confirmOpen, setConfirmOpen] = useState(false);
  const approveRef = useRef<HTMLButtonElement>(null);
  const cancelRef = useRef<HTMLButtonElement>(null);
  const wasOpenRef = useRef(false);

  useEffect(() => {
    if (confirmOpen) {
      cancelRef.current?.focus();
    } else if (wasOpenRef.current) {
      approveRef.current?.focus();
    }
    wasOpenRef.current = confirmOpen;
  }, [confirmOpen]);

  const isSubmitting = state.approvalSubmission === "submitting";

  const filesChanged = state.patchEvidence
    ? state.patchEvidence.files.length
    : "—";
  const before = state.redEvidence
    ? state.redTests > 0
      ? `${state.redTests} failed`
      : `exit ${state.redEvidence.exitCode}`
    : "—";
  const after = state.greenEvidence
    ? `${state.greenTests} passed`
    : "—";

  const guard = !state.redObserved
    ? "Locked until a failing selected-test run is observed."
    : !state.greenObservedAfterRed
      ? "Locked while selected tests are red; waiting for green verification."
      : state.approvalSubmission === "failed"
        ? "Approval resolution failed."
        : "The PR tool stayed locked while tests were red.";

  const note = (() => {
    if (state.approvalError) return state.approvalError;
    if (state.runtime.error) return state.runtime.error;
    if (state.runtime.mode === "live") {
      return "Waiting for an approval request from TrueForge";
    }
    return "Local fixture decision only — no GitHub write";
  })();

  useEffect(() => {
    if (!confirmOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        setConfirmOpen(false);
      }
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [confirmOpen]);

  const handleApprove = () => setConfirmOpen(true);
  const handleConfirm = async () => {
    const success = await onApprove();
    if (success) setConfirmOpen(false);
  };
  const handleDeny = async () => {
    await onDeny();
  };
  const handleClose = () => setConfirmOpen(false);

  return (
    <aside className={styles.rail}>
      {onResizeRail && (
        <div
          className={styles.railResizer}
          onMouseDown={onResizeRail}
          title="Drag to resize rail"
        />
      )}
      <div className={styles.railTitle}>Human approval required</div>
      <div className={styles.railSection}>
        <div className={styles.railHeading}>Verified patch receipt</div>
        <div className={styles.railRow}>
          Base commit: <code>{state.indexedCommit.slice(0, 12)}</code>
        </div>
        <div className={styles.railRow}>
          Dependency: {state.dependency}{" "}
          <code>
            {state.baselineVersion} → {state.breakingVersion}
          </code>
        </div>
        <div className={styles.railRow}>
          Files changed: <strong>{filesChanged}</strong>
        </div>
        <div className={styles.railRow}>
          Before:{" "}
          <span style={{ color: "var(--oxide)" }}>{before}</span>
        </div>
        <div className={styles.railRow}>
          After:{" "}
          <span style={{ color: "var(--mineral)" }}>{after}</span>
        </div>
      </div>
      <div className={styles.guard} aria-live="polite">
        {guard}
      </div>
      <p className={styles.note}>{note}</p>
      {selectedNode && (
        <div className={styles.railSection}>
          <div className={styles.railHeading}>Selected</div>
          <div className={styles.railRow}>
            {selectedNode.role}: {selectedNode.label}
          </div>
        </div>
      )}
      {state.approved !== null && (
        <div
          className={styles.railSection}
          style={{
            color: state.approved ? "var(--mineral)" : "var(--oxide)",
          }}
        >
          <div className={styles.railHeading}>Decision</div>
          <div className={styles.railRow}>
            {state.approved ? "Approved — local state only" : "Denied"}
          </div>
        </div>
      )}
      {popOutError && (
        <div className={styles.railSection}>
          <div className={styles.railHeading}>Pop-out</div>
          <div className={styles.railRow}>{popOutError}</div>
        </div>
      )}
      <div className={styles.actions}>
        <button
          ref={approveRef}
          className={styles.btnPrimary}
          disabled={!canApprove || isSubmitting}
          onClick={handleApprove}
        >
          {isSubmitting ? "Submitting..." : "Approve verified PR"}
        </button>
        <button
          className={styles.btnSecondary}
          onClick={handleDeny}
          disabled={state.approved !== null || isSubmitting}
        >
          {isSubmitting ? "Submitting..." : "Deny"}
        </button>
      </div>

      {confirmOpen && (
        <div
          className={styles.dialogOverlay}
          role="presentation"
          onClick={(e) => e.currentTarget === e.target && setConfirmOpen(false)}
        >
          <div
            className={styles.dialog}
            role="dialog"
            aria-modal="true"
            aria-labelledby="approve-dialog-title"
          >
            <h3 id="approve-dialog-title">Approve verified pull request</h3>
            <div className={styles.dialogRow}>
              Repository: <code>{state.repo}</code>
            </div>
            <div className={styles.dialogRow}>
              Target branch: <code>main</code>
            </div>
            <div className={styles.dialogRow}>
              Files changed: <strong>{filesChanged}</strong>
            </div>
            <div className={styles.dialogRow}>
              Test receipt:{" "}
              <span style={{ color: "var(--mineral)" }}>{after}</span> after
              red reproduction
            </div>
            {state.approvalError && (
              <div className={styles.dialogRow}>{state.approvalError}</div>
            )}
            <div className={styles.dialogActions}>
              <button
                ref={cancelRef}
                className={styles.btnSecondary}
                onClick={handleClose}
                disabled={isSubmitting}
              >
                Cancel
              </button>
              <button
                className={styles.btnPrimary}
                onClick={handleConfirm}
                disabled={isSubmitting}
              >
                Confirm
              </button>
            </div>
          </div>
        </div>
      )}
    </aside>
  );
}
