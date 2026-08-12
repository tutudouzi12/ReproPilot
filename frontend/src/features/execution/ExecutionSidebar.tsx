import { useMemo, useState, type RefObject } from 'react';
import { Activity, BarChart3, Box, CheckCircle2, ChevronRight, Code, FileText, GitBranch, Info, ListTree, Maximize2, PackageOpen, Play, RefreshCw, TerminalSquare, X } from 'lucide-react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import type { ExecutionDisplayMode } from '../../app/hooks/useReproPilotRuntime';
import type { Task } from '../../contracts/api';
import { ClaimEvidenceGraphView } from '../claim-evidence/ClaimEvidenceGraphView';
import { AutoResearchTrialView } from '../autoresearch/AutoResearchTrialView';
import { getAgentIcon } from '../shared/agentVisuals';
import { containsUnverifiedDemo } from '../shared/executionEvidence';

type CompactMode = Exclude<ExecutionDisplayMode, 'report-expanded' | 'plot-expanded' | 'evidence-expanded'>;
type InspectorTab = 'overview' | 'trace' | 'output' | 'artifacts';

interface ExecutionSidebarProps {
  selectedTask: Task;
  width: string;
  isExecuting: boolean;
  displayMode: ExecutionDisplayMode;
  executionLogs: string;
  executionResult: string;
  executionCode: string;
  executionStructuredData: string;
  executionImage: string;
  logsEndRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onExecute: () => void;
  onReassign: (assignedTo: string) => Promise<void>;
  onChangeDisplayMode: (mode: ExecutionDisplayMode) => void;
}

const resolveCompactMode = (displayMode: ExecutionDisplayMode): CompactMode => {
  if (displayMode === 'report-expanded') return 'report';
  if (displayMode === 'plot-expanded') return 'plot';
  if (displayMode === 'evidence-expanded') return 'evidence';
  return displayMode;
};

const reportAgents = new Set(['librarian_agent', 'data_agent', 'research_coding_agent']);

const inspectorAgentLabels: Record<string, string> = {
  librarian_agent: 'Research Agent',
  coder_agent: 'Coding Agent',
  research_coding_agent: 'Research Coding Agent',
  sandbox_agent: 'Sandbox Agent',
  data_agent: 'Data Agent',
  general_agent: 'General Agent',
};

export function ExecutionSidebar(props: ExecutionSidebarProps) {
  const {
    selectedTask,
    width,
    isExecuting,
    displayMode,
    executionLogs,
    executionResult,
    executionCode,
    executionStructuredData,
    executionImage,
    logsEndRef,
    onClose,
    onExecute,
    onReassign,
    onChangeDisplayMode,
  } = props;

  const activeMode = resolveCompactMode(displayMode);
  const isExpanded = displayMode === 'report-expanded' || displayMode === 'plot-expanded' || displayMode === 'evidence-expanded';

  return (
    <div
      style={{ width }}
      className={`repropilot-execution-sidebar z-20 flex flex-col transition-[width] duration-200 ${
        isExpanded ? 'absolute inset-0' : 'relative'
      }`}
    >
      {displayMode === 'evidence-expanded' ? (
        <ExpandedEvidenceView title={selectedTask.Name} rawGraph={executionStructuredData} onClose={() => onChangeDisplayMode('evidence')} />
      ) : displayMode === 'plot-expanded' ? (
        <ExpandedPlotView executionImage={executionImage} onClose={() => onChangeDisplayMode('plot')} />
      ) : displayMode === 'report-expanded' ? (
        <ExpandedReportView title={selectedTask.Name} executionResult={executionResult} onClose={() => onChangeDisplayMode('report')} />
      ) : (
        <ExecutionSidebarShell
          key={`${selectedTask.ID}:${selectedTask.AssignedTo}`}
          selectedTask={selectedTask}
          isExecuting={isExecuting}
          activeMode={activeMode}
          executionLogs={executionLogs}
          executionResult={executionResult}
          executionCode={executionCode}
          executionStructuredData={executionStructuredData}
          executionImage={executionImage}
          logsEndRef={logsEndRef}
          onClose={onClose}
          onExecute={onExecute}
          onReassign={onReassign}
          onChangeDisplayMode={onChangeDisplayMode}
        />
      )}
    </div>
  );
}

interface ExpandedEvidenceViewProps {
  title: string;
  rawGraph: string;
  onClose: () => void;
}

function ExpandedEvidenceView({ title, rawGraph, onClose }: ExpandedEvidenceViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col bg-white p-6">
      <div className="mb-4 flex flex-shrink-0 items-center justify-between border-b border-slate-200 pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-emerald-800">
            <GitBranch className="h-4 w-4" />
            Claim-to-Evidence Graph
          </div>
          <h2 className="mt-1 truncate text-xl font-semibold text-slate-900">{title}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-2 text-slate-500 transition-colors hover:bg-slate-100 hover:text-slate-900"
          title="退出全屏证据图"
          aria-label="退出全屏证据图"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 border border-slate-200">
        <ClaimEvidenceGraphView rawGraph={rawGraph} expanded />
      </div>
    </div>
  );
}

interface ExpandedPlotViewProps {
  executionImage: string;
  onClose: () => void;
}

function ExpandedPlotView({ executionImage, onClose }: ExpandedPlotViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white p-6">
      <div className="mb-4 flex flex-shrink-0 items-center justify-between border-b border-slate-200 pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-violet-700">
            <BarChart3 className="h-4 w-4" />
            Generated chart
          </div>
          <h2 className="mt-1 text-xl font-semibold text-slate-900">图表可视化</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          title="退出全屏图表"
          aria-label="退出全屏图表"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="flex min-h-0 flex-1 items-center justify-center overflow-hidden border border-slate-200 bg-slate-50 p-6">
        <img
          src={`data:image/png;base64,${executionImage}`}
          alt="Full Resolution Plot"
          className="max-h-full max-w-full object-contain"
        />
      </div>
    </div>
  );
}

interface ExpandedReportViewProps {
  title: string;
  executionResult: string;
  onClose: () => void;
}

function ExpandedReportView({ title, executionResult, onClose }: ExpandedReportViewProps) {
  return (
    <div className="flex min-h-0 flex-1 flex-col overflow-hidden bg-white p-6">
      <div className="mb-4 flex flex-shrink-0 items-center justify-between border-b border-slate-200 pb-4">
        <div className="min-w-0">
          <div className="flex items-center gap-2 text-sm font-semibold text-amber-800">
            <FileText className="h-4 w-4" />
            Analysis report
          </div>
          <h2 className="mt-1 truncate text-xl font-semibold text-slate-900">{title}</h2>
        </div>
        <button
          type="button"
          onClick={onClose}
          className="rounded-md p-2 text-slate-400 transition-colors hover:bg-slate-100 hover:text-slate-700"
          title="退出全屏报告"
          aria-label="退出全屏报告"
        >
          <X className="h-5 w-5" />
        </button>
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto px-4">
        <div className="prose prose-slate mx-auto max-w-4xl pb-10 text-slate-800 prose-headings:text-slate-900 prose-strong:text-slate-900 prose-code:rounded prose-code:bg-amber-50 prose-code:px-1 prose-code:text-amber-900">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
            {executionResult}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

interface ExecutionSidebarShellProps {
  selectedTask: Task;
  isExecuting: boolean;
  activeMode: CompactMode;
  executionLogs: string;
  executionResult: string;
  executionCode: string;
  executionStructuredData: string;
  executionImage: string;
  logsEndRef: RefObject<HTMLDivElement | null>;
  onClose: () => void;
  onExecute: () => void;
  onReassign: (assignedTo: string) => Promise<void>;
  onChangeDisplayMode: (mode: ExecutionDisplayMode) => void;
}

function ExecutionSidebarShell(props: ExecutionSidebarShellProps) {
  const {
    selectedTask,
    isExecuting,
    activeMode,
    executionLogs,
    executionResult,
    executionCode,
    executionStructuredData,
    executionImage,
    logsEndRef,
    onClose,
    onExecute,
    onReassign,
    onChangeDisplayMode,
  } = props;
  const [inspectorTab, setInspectorTab] = useState<InspectorTab>('overview');
  const ablationBudget = selectedTask.Type === 'ablation_design' ? selectedTask.Inputs : undefined;
  const unverifiedDemo = containsUnverifiedDemo(executionResult, executionCode, executionStructuredData);
  const status = resolveInspectorStatus(selectedTask.Status, isExecuting, unverifiedDemo);
  const traceEntries = useMemo(() => buildTraceEntries(executionLogs), [executionLogs]);
  const artifactModes = useMemo(() => {
    const modes: CompactMode[] = [];
    if (executionCode) modes.push('code');
    if (executionImage) modes.push('plot');
    if (selectedTask.Type === 'claim_evidence_build' && executionStructuredData) modes.push('evidence');
    if (reportAgents.has(selectedTask.AssignedTo) && executionResult) modes.push('report');
    return modes;
  }, [executionCode, executionImage, executionResult, executionStructuredData, selectedTask.AssignedTo, selectedTask.Type]);
  const effectiveArtifactMode = artifactModes.includes(activeMode) ? activeMode : artifactModes[0];

  const openArtifacts = () => {
    setInspectorTab('artifacts');
    if (!artifactModes.includes(activeMode) && artifactModes[0]) onChangeDisplayMode(artifactModes[0]);
  };

  return (
    <>
      <header className="execution-inspector-header">
        <div className="execution-inspector-kicker">
          <div>Execution</div>
          <button
            type="button"
            onClick={onClose}
            className="workspace-icon-button"
            title="关闭节点执行面板"
            aria-label="关闭节点执行面板"
          >
            <X className="h-4 w-4" />
          </button>
        </div>

        <div className="execution-inspector-identity">
          <span className="execution-inspector-agent-icon">
            {getAgentIcon(selectedTask.AssignedTo)}
          </span>
          <div className="min-w-0 flex-1">
            <h2 title={selectedTask.Name}>{selectedTask.Name}</h2>
            <div className="execution-inspector-agent-name">
              {inspectorAgentLabels[selectedTask.AssignedTo] ?? selectedTask.AssignedTo}
              {selectedTask.Type && <><span />{selectedTask.Type.replaceAll('_', ' ')}</>}
            </div>
          </div>
        </div>

        <div className="execution-inspector-command">
          <span className={`execution-inspector-status ${status.textClass}`}>
            <span className={status.dotClass} />
            {status.label}
          </span>
          <button type="button" onClick={onExecute} disabled={isExecuting} className="workspace-button workspace-button-primary">
            {isExecuting ? <span className="repropilot-loading-dot is-on-primary" /> : <Play className="fill-current" />}
            {isExecuting ? 'Running…' : 'Run node'}
          </button>
        </div>
      </header>

      <nav className="execution-inspector-tabs" role="tablist" aria-label="Execution inspector views">
        <InspectorTabButton label="Overview" icon={<Info className="h-3.5 w-3.5" />} active={inspectorTab === 'overview'} onClick={() => setInspectorTab('overview')} />
        <InspectorTabButton label="Trace" icon={<ListTree className="h-3.5 w-3.5" />} active={inspectorTab === 'trace'} onClick={() => setInspectorTab('trace')} />
        <InspectorTabButton
          label="Output"
          icon={<TerminalSquare className="h-3.5 w-3.5" />}
          active={inspectorTab === 'output'}
          onClick={() => {
            setInspectorTab('output');
            onChangeDisplayMode('logs');
          }}
        />
        <InspectorTabButton
          label="Artifacts"
          icon={<PackageOpen className="h-3.5 w-3.5" />}
          count={artifactModes.length}
          active={inspectorTab === 'artifacts'}
          onClick={openArtifacts}
        />
      </nav>

      <div className="execution-inspector-body">
        <div key={inspectorTab} className="repropilot-inspector-view min-h-full">
          {inspectorTab === 'overview' ? (
            <OverviewTab selectedTask={selectedTask} status={status} ablationBudget={ablationBudget} onReassign={onReassign} />
          ) : inspectorTab === 'trace' ? (
            <TraceTab entries={traceEntries} isExecuting={isExecuting} />
          ) : inspectorTab === 'output' ? (
            <OutputTab
              selectedTask={selectedTask}
              executionLogs={executionLogs}
              executionResult={executionResult}
              logsEndRef={logsEndRef}
            />
          ) : (
            <ArtifactsTab
              selectedTask={selectedTask}
              artifactModes={artifactModes}
              activeMode={effectiveArtifactMode}
              executionResult={executionResult}
              executionCode={executionCode}
              executionStructuredData={executionStructuredData}
              executionImage={executionImage}
              onChangeDisplayMode={onChangeDisplayMode}
            />
          )}
        </div>
      </div>
    </>
  );
}

interface InspectorStatus {
  label: string;
  textClass: string;
  dotClass: string;
}

const resolveInspectorStatus = (taskStatus: string, isExecuting: boolean, unverifiedDemo: boolean): InspectorStatus => {
  if (unverifiedDemo) return { label: 'Unverified demo', textClass: 'is-unverified', dotClass: 'is-unverified' };
  if (isExecuting || taskStatus === 'in_progress') return { label: 'Running', textClass: 'is-running', dotClass: 'is-running repropilot-status-dot-pulse' };
  if (taskStatus === 'completed') return { label: 'Completed', textClass: 'is-completed', dotClass: 'is-completed' };
  if (taskStatus === 'failed') return { label: 'Failed', textClass: 'is-failed', dotClass: 'is-failed' };
  if (taskStatus === 'blocked') return { label: 'Blocked', textClass: 'is-muted', dotClass: 'is-muted' };
  if (taskStatus === 'canceled') return { label: 'Canceled', textClass: 'is-muted', dotClass: 'is-muted' };
  if (taskStatus === 'ready') return { label: 'Ready', textClass: 'is-ready', dotClass: 'is-ready' };
  return { label: 'Waiting', textClass: 'is-muted', dotClass: 'is-muted' };
};

function InspectorTabButton({
  label,
  icon,
  count,
  active,
  onClick,
}: {
  label: string;
  icon: React.ReactNode;
  count?: number;
  active: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      role="tab"
      aria-selected={active}
      onClick={onClick}
      className={`execution-inspector-tab ${active ? 'is-active' : ''}`}
    >
      {icon}
      <span className="truncate">{label}</span>
      {typeof count === 'number' && count > 0 && <span className="execution-inspector-tab__count">{count}</span>}
    </button>
  );
}

function OverviewTab({ selectedTask, status, ablationBudget, onReassign }: { selectedTask: Task; status: InspectorStatus; ablationBudget?: Record<string, unknown>; onReassign: (assignedTo: string) => Promise<void> }) {
  const inputEntries = Object.entries(selectedTask.Inputs ?? {});
  const expectedArtifacts = selectedTask.OutputArtifacts ?? [];
  const requiredArtifacts = selectedTask.RequiredArtifacts ?? [];
  const dependencyLabel = selectedTask.Dependencies.length === 0
    ? 'None'
    : selectedTask.Dependencies.length === 1
      ? selectedTask.Dependencies[0]
      : `${selectedTask.Dependencies.length} upstream nodes`;

  return (
    <div className="execution-overview">
      {selectedTask.Description && <p className="execution-overview__description">{selectedTask.Description}</p>}

      <div className="execution-summary-grid">
        <div>
          <span>Status</span>
          <strong className={status.textClass}>{status.label}</strong>
        </div>
        <div>
          <span>Agent</span>
          <strong>{inspectorAgentLabels[selectedTask.AssignedTo] ?? selectedTask.AssignedTo}</strong>
        </div>
        <div>
          <span>Dependency</span>
          <strong title={selectedTask.Dependencies.join(', ')}>{dependencyLabel}</strong>
        </div>
      </div>

      <AgentReassignmentControl selectedTask={selectedTask} onReassign={onReassign} />

      {ablationBudget && (
        <section className="execution-inspector-section">
          <h3><Box /> Execution budget</h3>
          <div className="execution-budget-grid">
            <BudgetValue label="实验" value={ablationBudget.ablation_max_experiments} suffix="组" />
            <BudgetValue label="GPU" value={ablationBudget.ablation_max_gpu_minutes} suffix="分钟" />
            <BudgetValue label="总耗时" value={ablationBudget.ablation_max_wall_minutes} suffix="分钟" />
          </div>
        </section>
      )}

      <section className="execution-inspector-section">
        <h3><PackageOpen /> Expected artifacts</h3>
        <div className="expected-artifact-list">
          {expectedArtifacts.length > 0 ? expectedArtifacts.map((artifact) => (
            <div key={artifact} className="expected-artifact-row">
              <span className="expected-artifact-row__icon"><FileText /></span>
              <span>{artifact}</span>
              <span className="expected-artifact-row__state">Planned</span>
            </div>
          )) : <EmptyInspectorState text="This node does not declare output artifacts." />}
        </div>
      </section>

      <details className="execution-inspector-disclosure">
        <summary>
          <span><Code /> Inputs</span>
          <span>{inputEntries.length}</span>
        </summary>
        <div className="execution-inspector-disclosure__content">
          {inputEntries.length > 0 ? inputEntries.map(([key, value]) => (
            <div key={key} className="execution-input-row">
              <div>{key}</div>
              <pre>{formatMetadataValue(value)}</pre>
            </div>
          )) : <EmptyInspectorState text="No explicit inputs for this node." />}
        </div>
      </details>

      {requiredArtifacts.length > 0 && (
        <details className="execution-inspector-disclosure">
          <summary>
            <span><Activity /> Required context</span>
            <span>{requiredArtifacts.length}</span>
          </summary>
          <div className="execution-inspector-disclosure__content execution-required-list">
            {requiredArtifacts.map((artifact) => <span key={artifact}>{artifact}</span>)}
          </div>
        </details>
      )}
    </div>
  );
}

function AgentReassignmentControl({ selectedTask, onReassign }: { selectedTask: Task; onReassign: (assignedTo: string) => Promise<void> }) {
  const [assignedTo, setAssignedTo] = useState(selectedTask.AssignedTo);
  const [isReassigning, setIsReassigning] = useState(false);
  const [reassignError, setReassignError] = useState('');

  const applyReassignment = async () => {
    if (!assignedTo || assignedTo === selectedTask.AssignedTo || isReassigning) return;
    setIsReassigning(true);
    setReassignError('');
    try {
      await onReassign(assignedTo);
    } catch {
      setReassignError('重新分配失败，请确认计划仍处于可修改状态。');
    } finally {
      setIsReassigning(false);
    }
  };

  return (
    <section className="execution-inspector-section">
      <h3><RefreshCw /> Reassign agent</h3>
      <div className="flex gap-2">
        <select
          aria-label="重新分配 Agent"
          value={assignedTo}
          onChange={(event) => setAssignedTo(event.target.value)}
          disabled={isReassigning}
          className="min-w-0 flex-1 rounded-lg border border-slate-200 bg-white px-3 py-2 text-xs font-semibold text-slate-700 outline-none transition focus:border-blue-400 focus:ring-2 focus:ring-blue-100 disabled:opacity-60"
        >
          <option value="librarian_agent">Research Agent</option>
          <option value="coder_agent">Coding Agent</option>
          <option value="research_coding_agent">Research Coding Agent</option>
          <option value="sandbox_agent">Sandbox Agent</option>
          <option value="data_agent">Data Agent</option>
          <option value="general_agent">General Agent</option>
        </select>
        <button
          type="button"
          onClick={() => void applyReassignment()}
          disabled={isReassigning || assignedTo === selectedTask.AssignedTo}
          className="workspace-button workspace-button-secondary"
        >
          <RefreshCw className={isReassigning ? 'animate-spin' : ''} />
          Apply
        </button>
      </div>
      <p className="mt-2 text-xs text-slate-500">Resets the node and invalidates results from the previous execution lease.</p>
      {reassignError && <p className="mt-2 text-xs font-medium text-red-600">{reassignError}</p>}
    </section>
  );
}

interface TraceEntry {
  time?: string;
  content: string;
}

const buildTraceEntries = (logs: string): TraceEntry[] =>
  logs
    .split(/\r?\n/)
    .map((line) => line.trim())
    .filter(Boolean)
    .map((line) => {
      const match = line.match(/^\[?(\d{2}:\d{2}(?::\d{2})?)\]?\s+(.*)$/);
      return match ? { time: match[1], content: match[2] } : { content: line };
    });

function TraceTab({ entries, isExecuting }: { entries: TraceEntry[]; isExecuting: boolean }) {
  return (
    <div className="execution-trace">
      <div className="execution-view-heading">
        <div>
          <h3>Execution timeline</h3>
          <p>Events reported by the current agent and its tools.</p>
        </div>
        {entries.length > 0 && <span>{entries.length} events</span>}
      </div>
      {entries.length === 0 ? (
        <EmptyInspectorState text={isExecuting ? 'Waiting for the first execution event…' : 'No execution trace yet.'} />
      ) : (
        <ol className="execution-timeline">
          {entries.map((entry, index) => (
            <li key={`${index}-${entry.content}`} className={index === entries.length - 1 && isExecuting ? 'is-running' : ''}>
              <span className="execution-timeline__marker">
                {index < entries.length - 1 || !isExecuting ? <CheckCircle2 /> : <span />}
              </span>
              <div className="execution-timeline__content">
                <div>{entry.content}</div>
                {entry.time && <time>{entry.time}</time>}
              </div>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

function OutputTab({
  selectedTask,
  executionLogs,
  executionResult,
  logsEndRef,
}: {
  selectedTask: Task;
  executionLogs: string;
  executionResult: string;
  logsEndRef: RefObject<HTMLDivElement | null>;
}) {
  return (
    <div className="execution-output">
      <div className="execution-view-heading">
        <div>
          <h3><TerminalSquare />
          Terminal output
          </h3>
          <p>Raw output streamed from this node.</p>
        </div>
      </div>
      <div className="execution-terminal">
        {executionLogs || '> Ready. Run this node to stream output.'}
        {executionResult && !reportAgents.has(selectedTask.AssignedTo) && (
          <div className="execution-terminal__result">
            <span className="font-semibold">[Result]</span>{'\n'}
            {executionResult}
          </div>
        )}
        <div ref={logsEndRef} />
      </div>
    </div>
  );
}

function ArtifactsTab({
  selectedTask,
  artifactModes,
  activeMode,
  executionResult,
  executionCode,
  executionStructuredData,
  executionImage,
  onChangeDisplayMode,
}: {
  selectedTask: Task;
  artifactModes: CompactMode[];
  activeMode?: CompactMode;
  executionResult: string;
  executionCode: string;
  executionStructuredData: string;
  executionImage: string;
  onChangeDisplayMode: (mode: ExecutionDisplayMode) => void;
}) {
  const plannedArtifacts = selectedTask.OutputArtifacts ?? [];
  const artifactLabels: Partial<Record<CompactMode, { label: string; icon: React.ReactNode }>> = {
    code: { label: 'Code', icon: <Code className="h-3.5 w-3.5" /> },
    plot: { label: 'Chart', icon: <BarChart3 className="h-3.5 w-3.5" /> },
    report: { label: 'Report', icon: <FileText className="h-3.5 w-3.5" /> },
    evidence: { label: 'Evidence', icon: <GitBranch className="h-3.5 w-3.5" /> },
  };

  return (
    <div className="execution-artifacts">
      <div className="execution-view-heading">
        <div>
          <h3>Artifacts</h3>
          <p>Research objects produced by this node.</p>
        </div>
      </div>

      {artifactModes.length > 0 ? (
        <div className="artifact-object-list">
          {artifactModes.map((mode) => {
            const meta = artifactLabels[mode];
            if (!meta) return null;
            return (
              <button
                key={mode}
                type="button"
                onClick={() => onChangeDisplayMode(mode)}
                className={`artifact-object ${activeMode === mode ? 'is-active' : ''}`}
              >
                <span className="artifact-object__icon">{meta.icon}</span>
                <span className="artifact-object__copy">
                  <strong>{meta.label}</strong>
                  <small>Available output</small>
                </span>
                <ChevronRight />
              </button>
            );
          })}
        </div>
      ) : (
        <EmptyInspectorState text="No generated artifacts yet." />
      )}

      {activeMode && artifactModes.includes(activeMode) && (
        <ArtifactPreview
          taskType={selectedTask.Type}
          activeMode={activeMode}
          executionResult={executionResult}
          executionCode={executionCode}
          executionStructuredData={executionStructuredData}
          executionImage={executionImage}
          onChangeDisplayMode={onChangeDisplayMode}
        />
      )}

      {plannedArtifacts.length > 0 && (
        <div className="planned-artifacts">
          <div className="planned-artifacts__title">Planned outputs</div>
          <div>
            {plannedArtifacts.map((artifact) => (
              <div key={artifact} className="planned-artifact-row">
                <Box />
                <span>{artifact}</span>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  );
}

function ArtifactPreview({
  taskType,
  activeMode,
  executionResult,
  executionCode,
  executionStructuredData,
  executionImage,
  onChangeDisplayMode,
}: {
  taskType?: string;
  activeMode: CompactMode;
  executionResult: string;
  executionCode: string;
  executionStructuredData: string;
  executionImage: string;
  onChangeDisplayMode: (mode: ExecutionDisplayMode) => void;
}) {
  const expandedMode = activeMode === 'report' ? 'report-expanded' : activeMode === 'plot' ? 'plot-expanded' : activeMode === 'evidence' ? 'evidence-expanded' : null;
  return (
    <div className="artifact-preview">
      <div className="artifact-preview__header">
        <div>Preview</div>
        {expandedMode && (
          <button
            type="button"
            onClick={() => onChangeDisplayMode(expandedMode)}
            className="workspace-icon-button"
            title="全屏查看"
            aria-label="全屏查看"
          >
            <Maximize2 className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {activeMode === 'code' ? (
        <div className="artifact-preview__code">
          <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
            {`\`\`\`python\n${executionCode}\n\`\`\``}
          </ReactMarkdown>
        </div>
      ) : activeMode === 'plot' ? (
        <div className="artifact-preview__media">
          <img src={`data:image/png;base64,${executionImage}`} alt="Generated Plot" className="max-h-full max-w-full object-contain" />
        </div>
      ) : activeMode === 'evidence' ? (
        <div className="artifact-preview__evidence">
          <ClaimEvidenceGraphView rawGraph={executionStructuredData} />
        </div>
      ) : (
        selectedTaskTypeIsAutoResearch(executionStructuredData) ? (
          <AutoResearchTrialView raw={executionStructuredData || executionResult} taskType={taskType} />
        ) : (
          <div className="artifact-preview__report prose max-w-none">
            <ReactMarkdown remarkPlugins={[remarkGfm, remarkMath]} rehypePlugins={[rehypeKatex]}>
              {executionResult}
            </ReactMarkdown>
          </div>
        )
      )}
    </div>
  );
}

const selectedTaskTypeIsAutoResearch = (raw: string): boolean => raw.includes('autoresearch.ledger/v1') || raw.includes('autoresearch.validation/v1');

function EmptyInspectorState({ text }: { text: string }) {
  return <div className="execution-empty-state">{text}</div>;
}

const formatMetadataValue = (value: unknown): string => {
  if (typeof value === 'string') return value;
  if (value === undefined) return '—';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
};

function BudgetValue({ label, value, suffix }: { label: string; value: unknown; suffix: string }) {
  const displayValue = typeof value === 'number' || typeof value === 'string' ? String(value) : '-';
  return (
    <div>
      <div className="execution-budget-label">{label}</div>
      <div className="execution-budget-value">{displayValue} {suffix}</div>
    </div>
  );
}
