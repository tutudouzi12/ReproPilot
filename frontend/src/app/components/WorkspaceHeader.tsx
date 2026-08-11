import { Atom, Check, Play, RotateCcw, ShieldCheck, Square } from 'lucide-react';

interface WorkspaceHeaderProps {
  leftPanelWidth: number;
  taskTitle: string;
  stepCount: number;
  completedCount: number;
  failedCount: number;
  statusLabel: string;
  isExecuting: boolean;
  requiresApproval: boolean;
  runnableCount: number;
  onRun: () => void;
  onApproveAndRun: () => void;
  onCancel: () => void;
  onRetry: () => void;
}
export function WorkspaceHeader(props: WorkspaceHeaderProps) {
  const {
    leftPanelWidth,
    taskTitle,
    stepCount,
    completedCount,
    failedCount,
    statusLabel,
    isExecuting,
    requiresApproval,
    runnableCount,
    onRun,
    onApproveAndRun,
    onCancel,
    onRetry,
  } = props;

  const statusTone = isExecuting ? 'is-running' : failedCount > 0 ? 'is-failed' : stepCount > 0 ? 'is-ready' : 'is-idle';

  return (
    <header className="workspace-header">
      <div className="workspace-brand" style={{ width: `${leftPanelWidth}px` }}>
        <span className="workspace-brand__mark" aria-hidden="true"><Atom /></span>
        <span className="workspace-brand__name">ReproPilot</span>
      </div>

      <div className="workspace-context">
        <div className="workspace-context__copy">
          <span className="workspace-context__eyebrow">Research workspace</span>
          <h1 title={taskTitle}>{taskTitle}</h1>
        </div>
        <div className="workspace-context__progress" aria-label={`${completedCount} of ${stepCount} steps complete`}>
          <span className={`workspace-status ${statusTone}`}>
            <span className="workspace-status__dot" />
            {statusLabel}
          </span>
          {stepCount > 0 && (
            <>
              <span className="workspace-context__divider" />
              <span>{completedCount} / {stepCount}</span>
              <Check className="workspace-context__check" />
            </>
          )}
        </div>
      </div>

      <div className="workspace-header-actions">
        {isExecuting ? (
          <button type="button" onClick={onCancel} className="workspace-button workspace-button-danger">
            <Square className="fill-current" /> Stop
          </button>
        ) : requiresApproval ? (
          <button type="button" onClick={onApproveAndRun} className="workspace-button workspace-button-primary">
            <ShieldCheck /> Approve &amp; run
          </button>
        ) : failedCount > 0 ? (
          <button type="button" onClick={onRetry} className="workspace-button workspace-button-secondary">
            <RotateCcw /> Retry
          </button>
        ) : (
          <button type="button" onClick={onRun} disabled={runnableCount === 0} className="workspace-button workspace-button-primary">
            <Play className="fill-current" /> Run
          </button>
        )}
      </div>
    </header>
  );
}
