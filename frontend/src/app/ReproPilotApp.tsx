import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { useEdgesState, useNodesState } from '@xyflow/react';
import type { Edge, Node, OnEdgesChange, OnNodesChange } from '@xyflow/react';
import { GitBranch, MessageSquareText } from 'lucide-react';
import '@xyflow/react/dist/style.css';
import 'katex/dist/katex.min.css';

import { LeftWorkspaceChat, LeftWorkspacePdf } from './components/LeftWorkspace';
import { WorkspaceHeader } from './components/WorkspaceHeader';
import { useReproPilotRuntimeContext, type ReproPilotRuntimeContextValue } from './context/ReproPilotRuntimeContext';
import { ReproPilotRuntimeProvider } from './context/ReproPilotRuntimeProvider';
import { usePdfAssistFlow } from './hooks/usePdfAssistFlow';
import { useReproPilotChatFlow } from './hooks/useReproPilotChatFlow';
import { useReproPilotLayoutState } from './hooks/useReproPilotLayoutState';
import { useReproPilotRuntime } from './hooks/useReproPilotRuntime';
import { useGraphExecutionViewModel } from './viewModels/useGraphExecutionViewModel';
import { ExecutionSidebar } from '../features/execution/ExecutionSidebar';
import { GraphPanel } from '../features/plan-graph/GraphPanel';
import { buildGraphLayout } from '../features/plan-graph/buildGraphLayout';
import type { IntentContext } from '../contracts/api';
import { getPdfProxyUrl } from '../services/api/repropilotApi';

interface ReproPilotAppShellProps {
  layout: ReturnType<typeof useReproPilotLayoutState>;
  leftWorkspace: ReactNode;
  graphExecutionViewModel: ReturnType<typeof useGraphExecutionViewModel>;
  mobilePane: 'chat' | 'graph';
  onMobilePaneChange: (pane: 'chat' | 'graph') => void;
}

function ReproPilotAppShell(props: ReproPilotAppShellProps) {
  const { layout, leftWorkspace, graphExecutionViewModel, mobilePane, onMobilePaneChange } = props;
  const graphProps = graphExecutionViewModel.graphPanelProps;
  const graphNodeCount = graphProps.nodes.length;
  const completedCount = graphProps.nodes.filter((node) => node.data.status === 'completed' && !node.data.unverifiedDemo).length;
  const failedCount = graphProps.nodes.filter((node) => node.data.status === 'failed').length;
  const runnableCount = graphProps.nodes.filter((node) => ['pending', 'ready'].includes(String(node.data.status))).length;
  const taskTitle = graphProps.intentContext?.raw_intent || 'Start a new research task';
  const statusLabel = graphProps.isExecuting ? 'Running' : failedCount > 0 ? 'Needs attention' : graphNodeCount > 0 ? 'Ready' : 'Idle';

  return (
    <div className="repropilot-app-shell" data-mobile-pane={mobilePane}>
      <WorkspaceHeader
        leftPanelWidth={layout.leftPanelWidth}
        taskTitle={taskTitle}
        stepCount={graphNodeCount}
        completedCount={completedCount}
        failedCount={failedCount}
        statusLabel={statusLabel}
        isExecuting={graphProps.isExecuting}
        requiresApproval={graphProps.requiresApproval}
        runnableCount={runnableCount}
        onRun={graphProps.onRunAll}
        onApproveAndRun={graphProps.onApproveAndRun}
        onCancel={graphProps.onCancel}
        onRetry={graphProps.onRetryFailed}
      />

      <div className="repropilot-workspace-body flex min-h-0 flex-1 overflow-hidden">
        <div className="repropilot-mobile-tabbar">
          <button type="button" onClick={() => onMobilePaneChange('chat')} className={mobilePane === 'chat' ? 'is-active' : ''}>
            <MessageSquareText className="h-4 w-4" /> Conversation
          </button>
          <button type="button" onClick={() => onMobilePaneChange('graph')} className={mobilePane === 'graph' ? 'is-active' : ''}>
            <GitBranch className="h-4 w-4" /> Workflow{graphNodeCount > 0 ? ` ${graphNodeCount}` : ''}
          </button>
        </div>

        {leftWorkspace}

        <div className={`repropilot-left-resize-handle workspace-resize-handle ${layout.isResizing ? 'is-resizing' : ''}`} onMouseDown={layout.startResizingLeftPanel} />

        <div className="repropilot-graph-workspace relative flex min-w-0 flex-1 overflow-hidden">
          <GraphPanel {...graphProps} />

          {graphExecutionViewModel.showExecutionResizeHandle && (
            <div className={`workspace-resize-handle z-20 ${layout.isResizingSidebar ? 'is-resizing' : ''}`} onMouseDown={layout.startResizingSidebar} />
          )}

          {graphExecutionViewModel.executionSidebarProps && <ExecutionSidebar {...graphExecutionViewModel.executionSidebarProps} />}
        </div>
      </div>
    </div>
  );
}

interface ReproPilotWorkspaceContentProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange<Node>;
  onEdgesChange: OnEdgesChange<Edge>;
  logsEndRef: RefObject<HTMLDivElement | null>;
  layout: ReturnType<typeof useReproPilotLayoutState>;
  chatFlow: {
    chatHistory: ReturnType<typeof useReproPilotChatFlow>['chatHistory'];
    loading: boolean;
    prompt: string;
    setPrompt: (value: string) => void;
    handleSendMessage: () => void;
	pendingAttachments: ReturnType<typeof useReproPilotChatFlow>['pendingAttachments'];
	uploadingAttachments: boolean;
	attachmentError: string;
	handleAttachFiles: (files: File[]) => void;
	handleRemoveAttachment: (uploadId: string) => void;
    intentContext: IntentContext | null;
    activePlanId: string | null;
	activePlanStatus: string | null;
    isLoggedIn: boolean;
    userId: string | null;
    loginInput: string;
    setLoginInput: (value: string) => void;
    activeSessionId: string | null;
    sessionSummaries: ReturnType<typeof useReproPilotChatFlow>['sessionSummaries'];
    handleLogin: () => void;
    handleCreateSession: () => void;
    handleSwitchSession: (sessionId: string) => void;
  };
  pdfFlow: ReturnType<typeof usePdfAssistFlow>;
  mobilePane: 'chat' | 'graph';
  onMobilePaneChange: (pane: 'chat' | 'graph') => void;
}

function ReproPilotWorkspaceContent(props: ReproPilotWorkspaceContentProps) {
  const { nodes, edges, onNodesChange, onEdgesChange, logsEndRef, layout, chatFlow, pdfFlow, mobilePane, onMobilePaneChange } = props;
  const runtime = useReproPilotRuntimeContext();
  const graphExecutionViewModel = useGraphExecutionViewModel({
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    intentContext: chatFlow.intentContext,
    activePlanId: chatFlow.activePlanId,
	activePlanStatus: chatFlow.activePlanStatus,
    layout,
    logsEndRef,
  });

  const leftWorkspace = pdfFlow.pdfUrl ? (
    <LeftWorkspacePdf
      width={layout.leftPanelWidth}
      pdfUrl={pdfFlow.pdfUrl}
      onClosePdf={() => pdfFlow.setPdfUrl(null)}
      onAskAI={pdfFlow.onAskAI}
    />
  ) : (
    <LeftWorkspaceChat
      width={layout.leftPanelWidth}
      state={{
        chatHistory: chatFlow.chatHistory,
        loading: chatFlow.loading,
        prompt: chatFlow.prompt,
        showSuggestions: pdfFlow.showSuggestions,
		pendingAttachments: chatFlow.pendingAttachments,
		uploadingAttachments: chatFlow.uploadingAttachments,
		attachmentError: chatFlow.attachmentError,
        isLoggedIn: chatFlow.isLoggedIn,
        userId: chatFlow.userId,
        loginInput: chatFlow.loginInput,
        activeSessionId: chatFlow.activeSessionId,
        sessions: chatFlow.sessionSummaries,
      }}
      chatActions={{
        setPrompt: chatFlow.setPrompt,
        setShowSuggestions: pdfFlow.setShowSuggestions,
        onSendMessage: chatFlow.handleSendMessage,
        setLoginInput: chatFlow.setLoginInput,
        onLogin: chatFlow.handleLogin,
        onCreateSession: chatFlow.handleCreateSession,
        onSwitchSession: chatFlow.handleSwitchSession,
		onAttachFiles: chatFlow.handleAttachFiles,
		onRemoveAttachment: chatFlow.handleRemoveAttachment,
      }}
      pdfActions={{
        onOpenPdf: (url?: string) => pdfFlow.setPdfUrl(url || getPdfProxyUrl('https://export.arxiv.org/pdf/1706.03762')),
        onClosePdf: () => pdfFlow.setPdfUrl(null),
      }}
      taskActions={{
        onOpenTaskView: runtime.actions.handleOpenTaskView,
      }}
    />
  );

  return (
    <ReproPilotAppShell
      layout={layout}
      leftWorkspace={leftWorkspace}
      graphExecutionViewModel={graphExecutionViewModel}
      mobilePane={mobilePane}
      onMobilePaneChange={onMobilePaneChange}
    />
  );
}

export default function ReproPilotApp() {
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>([]);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const [mobilePane, setMobilePane] = useState<'chat' | 'graph'>('chat');
  const logsEndRef = useRef<HTMLDivElement>(null);
  const layout = useReproPilotLayoutState();

  const handlePlanGraphChanged = useCallback(
    (planGraph: ReturnType<typeof useReproPilotChatFlow>['intentContext'] extends never ? never : Parameters<Parameters<typeof useReproPilotChatFlow>[0]['onPlanGraphChanged']>[0]) => {
      if (!planGraph) {
        setNodes([]);
        setEdges([]);
        setMobilePane('chat');
        return;
      }

      const graphLayout = buildGraphLayout(planGraph);
      setNodes(graphLayout.nodes);
      setEdges(graphLayout.edges);
      setMobilePane('graph');
    },
    [setEdges, setNodes],
  );

  const chatFlow = useReproPilotChatFlow({
    onPlanGraphChanged: handlePlanGraphChanged,
  });

  const runtime = useReproPilotRuntime({
    nodes,
    setNodes,
    appendChatMessage: chatFlow.appendChatMessage,
	identity: chatFlow.requestIdentity,
  });
  const { resetRuntimeState } = runtime;

  const pdfFlow = usePdfAssistFlow({
    setPrompt: chatFlow.setPrompt,
    appendSelectedTaskLog: runtime.appendSelectedTaskLog,
  });

  useEffect(() => {
    logsEndRef.current?.scrollIntoView({ behavior: 'smooth' });
  }, [runtime.selectedTaskState.logs]);

  useEffect(() => {
    resetRuntimeState();
  }, [chatFlow.activeSessionId, resetRuntimeState]);

  const runtimeContextValue = useMemo<ReproPilotRuntimeContextValue>(
    () => ({
      state: {
        executionState: runtime.executionState,
        selectedTaskState: runtime.selectedTaskState,
      },
      actions: {
        onNodeClick: runtime.onNodeClick,
        handleOpenTaskView: runtime.handleOpenTaskView,
        handleExecuteTask: runtime.handleExecuteTask,
        handleRunAllTasks: runtime.handleRunAllTasks,
		handleApproveAndRun: runtime.handleApproveAndRun,
		handleCancelPlan: runtime.handleCancelPlan,
		handleRetryFailedPlan: runtime.handleRetryFailedPlan,
        handleReassignTask: runtime.handleReassignTask,
        setDisplayMode: runtime.setDisplayMode,
        closeTaskPanel: runtime.closeTaskPanel,
        resetRuntimeState: runtime.resetRuntimeState,
      },
      meta: {
        appendSelectedTaskLog: runtime.appendSelectedTaskLog,
      },
    }),
    [runtime],
  );

  return (
    <ReproPilotRuntimeProvider value={runtimeContextValue}>
      <ReproPilotWorkspaceContent
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        logsEndRef={logsEndRef}
        layout={layout}
        chatFlow={{
          chatHistory: chatFlow.chatHistory,
          loading: chatFlow.loading,
          prompt: chatFlow.prompt,
          setPrompt: chatFlow.setPrompt,
          handleSendMessage: chatFlow.handleSendMessage,
		  pendingAttachments: chatFlow.pendingAttachments,
		  uploadingAttachments: chatFlow.uploadingAttachments,
		  attachmentError: chatFlow.attachmentError,
		  handleAttachFiles: chatFlow.handleAttachFiles,
		  handleRemoveAttachment: chatFlow.handleRemoveAttachment,
          intentContext: chatFlow.intentContext,
          activePlanId: chatFlow.activePlanId,
		  activePlanStatus: chatFlow.activePlanStatus,
          isLoggedIn: chatFlow.isLoggedIn,
          userId: chatFlow.userId,
          loginInput: chatFlow.loginInput,
          setLoginInput: chatFlow.setLoginInput,
          activeSessionId: chatFlow.activeSessionId,
          sessionSummaries: chatFlow.sessionSummaries,
          handleLogin: chatFlow.handleLogin,
          handleCreateSession: chatFlow.handleCreateSession,
          handleSwitchSession: chatFlow.handleSwitchSession,
        }}
        pdfFlow={pdfFlow}
        mobilePane={mobilePane}
        onMobilePaneChange={setMobilePane}
      />
    </ReproPilotRuntimeProvider>
  );
}
