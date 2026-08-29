"use client";

import React, { useCallback, useEffect, useMemo, useReducer } from "react";
import { MissionAdapter } from "../lib/missionAdapter";
import { fixtureMissionAdapter } from "../lib/fixtureMissionAdapter";
import {
  canApproveMission,
  createInitialMissionState,
  missionReducer,
} from "../lib/missionReducer";
import { MissionState, NodeId } from "../lib/types";

interface MissionCtx {
  state: MissionState;
  canApprove: boolean;
  selectNode: (id: NodeId | null) => void;
  toggleDock: () => void;
  setTab: (tab: MissionState["activeTab"]) => void;
  togglePopOut: () => void;
  approve: () => Promise<boolean>;
  deny: () => Promise<boolean>;
}

const MissionContext = React.createContext<MissionCtx | null>(null);

export function useMission() {
  const ctx = React.useContext(MissionContext);
  if (!ctx) throw new Error("useMission must be inside MissionProvider");
  return ctx;
}

function formatTime() {
  const now = new Date();
  const yr = now.getUTCFullYear();
  const mo = String(now.getUTCMonth() + 1).padStart(2, "0");
  const da = String(now.getUTCDate()).padStart(2, "0");
  const hr = String(now.getUTCHours()).padStart(2, "0");
  const mn = String(now.getUTCMinutes()).padStart(2, "0");
  const sc = String(now.getUTCSeconds()).padStart(2, "0");
  return `${yr}-${mo}-${da} · ${hr}:${mn}:${sc} UTC`;
}

interface MissionProviderProps {
  children: React.ReactNode;
  adapter?: MissionAdapter;
  seed?: Partial<MissionState>;
}

export function MissionProvider({
  children,
  adapter = fixtureMissionAdapter,
  seed,
}: MissionProviderProps) {
  const [state, dispatch] = useReducer(
    missionReducer,
    undefined,
    () =>
      createInitialMissionState({
        currentTime: formatTime(),
        mode: adapter.mode,
        seed,
      })
  );

  // Live clock
  useEffect(() => {
    const id = window.setInterval(() => {
      dispatch({ type: "clock.ticked", currentTime: formatTime() });
    }, 1000);
    return () => window.clearInterval(id);
  }, []);

  useEffect(() => adapter.subscribe(dispatch), [adapter]);

  const selectNode = useCallback((id: NodeId | null) => {
    dispatch({ type: "selection.changed", nodeId: id });
  }, []);

  const toggleDock = useCallback(() => {
    dispatch({ type: "dock.toggled" });
  }, []);

  const setTab = useCallback((tab: MissionState["activeTab"]) => {
    dispatch({ type: "inspector.tab.changed", tab });
  }, []);

  const togglePopOut = useCallback(() => {
    dispatch({ type: "popout.toggled" });
  }, []);

  const canApprove = useMemo(
    () =>
      canApproveMission(state) &&
      (adapter.mode === "fixture" || Boolean(adapter.resolveApproval)),
    [state, adapter]
  );

  const approve = useCallback(async (): Promise<boolean> => {
    if (!canApprove) return false;
    dispatch({ type: "approval.submitting" });

    if (adapter.mode === "live") {
      dispatch({
        type: "approval.failed",
        message: "Live approval is not available in this build",
      });
      return false;
    }

    try {
      if (adapter.resolveApproval && state.pendingApproval) {
        await adapter.resolveApproval(state.pendingApproval, "approve");
      }
      dispatch({ type: "approval.resolved", decision: "approve" });
      return true;
    } catch (error) {
      dispatch({
        type: "approval.failed",
        message: error instanceof Error ? error.message : "Approval failed",
      });
      return false;
    }
  }, [canApprove, state, adapter]);

  const deny = useCallback(async (): Promise<boolean> => {
    if (state.approved !== null || state.approvalSubmission === "submitting") {
      return false;
    }
    dispatch({ type: "approval.submitting" });

    if (adapter.mode === "live") {
      dispatch({
        type: "approval.failed",
        message: "Live approval is not available in this build",
      });
      return false;
    }

    try {
      if (adapter.resolveApproval && state.pendingApproval) {
        await adapter.resolveApproval(state.pendingApproval, "deny");
      }
      dispatch({ type: "approval.resolved", decision: "deny" });
      return true;
    } catch (error) {
      dispatch({
        type: "approval.failed",
        message: error instanceof Error ? error.message : "Denial failed",
      });
      return false;
    }
  }, [state, adapter]);

  const value = useMemo<MissionCtx>(
    () => ({
      state,
      canApprove,
      selectNode,
      toggleDock,
      setTab,
      togglePopOut,
      approve,
      deny,
    }),
    [state, canApprove, selectNode, toggleDock, setTab, togglePopOut, approve, deny]
  );

  return (
    <MissionContext.Provider value={value}>{children}</MissionContext.Provider>
  );
}
