import { createContext, useContext, useMemo } from "react";

const emptyContext = {
  clientId: null,
  clientSnapshotId: null,
  selectedGoalId: null,
  portfolioId: null,
  draftId: null,
  marketSnapshotId: null,
  calculationId: null,
  asOf: null,
};

const WorkspaceContext = createContext(emptyContext);

export function WorkspaceProvider({ value, children }) {
  const stable = useMemo(() => ({ ...emptyContext, ...(value || {}) }), [value]);
  return <WorkspaceContext.Provider value={stable}>{children}</WorkspaceContext.Provider>;
}

export function useWorkspace() {
  return useContext(WorkspaceContext);
}
