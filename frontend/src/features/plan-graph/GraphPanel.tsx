import { Background, Controls, MarkerType, ReactFlow } from '@xyflow/react';
import type { Edge, Node, OnEdgesChange, OnNodesChange } from '@xyflow/react';
import { CheckCircle2, GitBranch, Waypoints } from 'lucide-react';
import { useMemo } from 'react';
import type { IntentContext } from '../../contracts/api';

interface GraphPanelProps {
  nodes: Node[];
  edges: Edge[];
  onNodesChange: OnNodesChange<Node>;
  onEdgesChange: OnEdgesChange<Edge>;
  onNodeClick: (_: unknown, node: Node) => void;
  intentContext: IntentContext | null;
  runAllText: string;
  graphTitle: string;
  graphHint: string;
  isExecuting: boolean;
	requiresApproval: boolean;
  onRunAll: () => void;
	onApproveAndRun: () => void;
	onCancel: () => void;
	onRetryFailed: () => void;
}

const intentLabels: Record<string, string> = {
  Paper_Reproduction: '论文复现',
  Framework_Comparison: '框架对比',
  Code_Execution: '代码执行',
  General: '通用任务',
};

export function GraphPanel(props: GraphPanelProps) {
  const {
    nodes,
    edges,
    onNodesChange,
    onEdgesChange,
    onNodeClick,
    intentContext,
    graphTitle,
    graphHint,
  } = props;
  const completedCount = nodes.filter((node) => node.data.status === 'completed' && !node.data.unverifiedDemo).length;
  const demoCount = nodes.filter((node) => Boolean(node.data.unverifiedDemo)).length;
  const runningCount = nodes.filter((node) => node.data.status === 'in_progress').length;
	const failedCount = nodes.filter((node) => node.data.status === 'failed').length;
  const intentLabel = intentContext ? intentLabels[intentContext.intent_type] ?? intentContext.intent_type : null;
  const subtitle = intentContext?.raw_intent || graphHint;
  const visualEdges = useMemo(() => {
    const nodeStateById = new Map(
      nodes.map((node) => [
        node.id,
        {
          status: String(node.data.status ?? 'pending'),
          unverifiedDemo: Boolean(node.data.unverifiedDemo),
        },
      ]),
    );

    return edges.map((edge) => {
      const targetState = nodeStateById.get(edge.target);
      const isDataEdge = edge.data?.edgeType === 'data';
      let stroke = '#c9c4ba';
      let stateClass = 'is-neutral';
      let animated = false;

      if (targetState?.unverifiedDemo) {
        stroke = '#7a6474';
        stateClass = 'is-unverified';
      } else if (targetState?.status === 'in_progress') {
        stroke = '#b65f3c';
        stateClass = 'is-running';
        animated = true;
      } else if (targetState?.status === 'completed') {
        stroke = '#68745c';
        stateClass = 'is-completed';
      } else if (targetState?.status === 'failed') {
        stroke = '#945c55';
        stateClass = 'is-failed';
      }

      return {
        ...edge,
        animated,
        className: `workflow-edge ${stateClass}`,
        style: {
          ...edge.style,
          stroke,
          strokeWidth: stateClass === 'is-neutral' ? 1.25 : 1.6,
          strokeDasharray: isDataEdge ? '5 5' : undefined,
        },
        markerEnd: {
          type: MarkerType.ArrowClosed,
          color: stroke,
          width: 14,
          height: 14,
        },
      };
    });
  }, [edges, nodes]);

  return (
    <div className="workflow-workspace">
      <div className="workflow-canvas-stage">
        <div className="workflow-canvas-toolbar">
          <div className="workflow-canvas-toolbar__identity">
            <span className="workflow-canvas-toolbar__icon"><GitBranch /></span>
            <div className="min-w-0">
              <h2>{graphTitle}</h2>
              <p title={subtitle}>{subtitle}</p>
            </div>
          </div>
          <div className="workflow-canvas-toolbar__meta">
            {intentLabel && <span>{intentLabel}</span>}
            <span>{nodes.length} steps</span>
            <span className="workflow-complete-count"><CheckCircle2 /> {completedCount}/{nodes.length}</span>
            {demoCount > 0 && <span className="is-unverified">{demoCount} unverified</span>}
            {runningCount > 0 && <span className="is-running"><span className="repropilot-loading-dot" /> {runningCount} running</span>}
            {failedCount > 0 && <span className="is-failed">{failedCount} failed</span>}
          </div>
        </div>

        {nodes.length === 0 && (
          <div className="workflow-empty-state" aria-hidden="true">
            <Waypoints />
            <div>
              <strong>Your research workflow will appear here</strong>
              <span>Start with a question, paper, repository, or dataset.</span>
            </div>
          </div>
        )}

        <ReactFlow
          nodes={nodes}
          edges={visualEdges}
          onNodesChange={onNodesChange}
          onEdgesChange={onEdgesChange}
          onNodeClick={onNodeClick}
          nodesConnectable={false}
          nodesDraggable={false}
          fitView
          fitViewOptions={{ padding: 0.22, maxZoom: 1.04 }}
          className="workflow-canvas"
          proOptions={{ hideAttribution: true }}
        >
          <Background color="#bdb8af" gap={24} size={0.8} />
          <Controls showInteractive={false} position="bottom-left" />
        </ReactFlow>
      </div>
    </div>
  );
}
