import { createContext, useContext } from 'react';
import type { useReproPilotRuntime } from '../hooks/useReproPilotRuntime';

type ReproPilotRuntimeApi = ReturnType<typeof useReproPilotRuntime>;

export interface ReproPilotRuntimeContextValue {
  state: {
    executionState: ReproPilotRuntimeApi['executionState'];
    selectedTaskState: ReproPilotRuntimeApi['selectedTaskState'];
  };
  actions: {
    onNodeClick: ReproPilotRuntimeApi['onNodeClick'];
    handleOpenTaskView: ReproPilotRuntimeApi['handleOpenTaskView'];
    handleExecuteTask: ReproPilotRuntimeApi['handleExecuteTask'];
    handleRunAllTasks: ReproPilotRuntimeApi['handleRunAllTasks'];
	handleApproveAndRun: ReproPilotRuntimeApi['handleApproveAndRun'];
	handleCancelPlan: ReproPilotRuntimeApi['handleCancelPlan'];
	handleRetryFailedPlan: ReproPilotRuntimeApi['handleRetryFailedPlan'];
    setDisplayMode: ReproPilotRuntimeApi['setDisplayMode'];
    closeTaskPanel: ReproPilotRuntimeApi['closeTaskPanel'];
    resetRuntimeState: ReproPilotRuntimeApi['resetRuntimeState'];
  };
  meta: {
    appendSelectedTaskLog: ReproPilotRuntimeApi['appendSelectedTaskLog'];
  };
}

export const ReproPilotRuntimeContext = createContext<ReproPilotRuntimeContextValue | null>(null);

export function useReproPilotRuntimeContext() {
  const context = useContext(ReproPilotRuntimeContext);
  if (!context) {
    throw new Error('useReproPilotRuntimeContext must be used within ReproPilotRuntimeProvider');
  }
  return context;
}
