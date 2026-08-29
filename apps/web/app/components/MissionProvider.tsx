"use client";

import React, { useCallback, useEffect, useMemo, useReducer } from "react";
import {
  fixtureMissionAdapter,
  MissionAdapter,
} from "../lib/fixtureMissionAdapter";
import {
  createInitialMissionState,
  missionReducer,
} from "../lib/missionReducer";
import { MissionState, NodeId } from "../lib/types";

interface MissionCtx {
  state: MissionState;
  selectNode: (id: NodeId | null) => void;
  toggleDock: () => void;
  setTab: (tab: MissionState["activeTab"]) => void;
  togglePopOut: () => void;
  approve: () => void;
  deny: () => void;
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
}

export function MissionProvider({
  children,
  adapter = fixtureMissionAdapter,
}: MissionProviderProps) {
  const [state, dispatch] = useReducer(
    missionReducer,
    undefined,
    () => createInitialMissionState(formatTime())
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

  const approve = useCallback(() => {
    dispatch({ type: "approval.approved" });
  }, []);

  const deny = useCallback(() => {
    dispatch({ type: "approval.denied" });
  }, []);

  const value = useMemo<MissionCtx>(
    () => ({
      state,
      selectNode,
      toggleDock,
      setTab,
      togglePopOut,
      approve,
      deny,
    }),
    [state, selectNode, toggleDock, setTab, togglePopOut, approve, deny]
  );

  return (
    <MissionContext.Provider value={value}>{children}</MissionContext.Provider>
  );
}
