import { MarkerType, Position, type Edge, type Node } from '@xyflow/react';
import type { GraphTask, PlanGraph, Task } from '../../contracts/api';
import { getTaskStyleByStatus } from '../shared/agentVisuals';
import { containsUnverifiedDemo } from '../shared/executionEvidence';
import { createTaskNodeLabel } from './nodeLabelFactory';

const NODE_WIDTH = 236;
const NODE_HEIGHT = 112;

const getCompactColumnCount = () => (typeof window !== 'undefined' && window.innerWidth < 640 ? 2 : 3);

const pairKey = (from: string, to: string) => `${from}->${to}`;

const selectVisibleEdges = (planGraph: PlanGraph) => {
  const controlEdges = planGraph.edges.filter(
    (edge) => edge.type === 'control' || edge.type === 'dependency',
  );
  const controlPairs = new Set(controlEdges.map((edge) => pairKey(edge.from, edge.to)));
  const adjacency = controlEdges.reduce<Record<string, string[]>>((result, edge) => {
    result[edge.from] = [...(result[edge.from] ?? []), edge.to];
    return result;
  }, {});

  const hasControlPath = (from: string, to: string) => {
    const queue = [...(adjacency[from] ?? [])];
    const visited = new Set<string>();
    while (queue.length > 0) {
      const current = queue.shift();
      if (!current || visited.has(current)) continue;
      if (current === to) return true;
      visited.add(current);
      queue.push(...(adjacency[current] ?? []));
    }
    return false;
  };

  const dataEdges = planGraph.edges.filter(
    (edge) =>
      edge.type === 'data' &&
      !controlPairs.has(pairKey(edge.from, edge.to)) &&
      !hasControlPath(edge.from, edge.to),
  );

  return [...controlEdges, ...dataEdges].filter(
    (edge, index, edges) =>
      edges.findIndex((candidate) => pairKey(candidate.from, candidate.to) === pairKey(edge.from, edge.to)) === index,
  );
};

export const graphTaskToTask = (task: GraphTask): Task => ({
  ID: task.id,
  Name: task.name,
  Type: task.type,
  Description: task.description,
  AssignedTo: task.assigned_to,
  Status: task.status,
  Dependencies: task.dependencies ?? [],
  Inputs: task.inputs,
  RequiredArtifacts: task.required_artifacts,
  OutputArtifacts: task.output_artifacts,
  Result: task.result,
  Code: task.code,
  StructuredData: task.structured_data,
  ImageBase64: task.image_base64 || task.image_base_64,
});

export const buildGraphLayout = (planGraph: PlanGraph): { nodes: Node[]; edges: Edge[] } => {
  const newNodes: Node[] = [];
  const newEdges: Edge[] = [];

  const levelMap: Record<string, number> = {};
  const laneOrder = ['librarian_agent', 'coder_agent', 'research_coding_agent', 'sandbox_agent', 'data_agent', 'general_agent'];
  const tasksById = Object.fromEntries(planGraph.nodes.map((task) => [task.id, task]));

  const resolveLevel = (task: GraphTask): number => {
    if (typeof levelMap[task.id] === 'number') return levelMap[task.id];
    if (!task.dependencies.length) {
      levelMap[task.id] = 0;
      return 0;
    }

    const level = Math.max(
      ...task.dependencies.map((depId) => {
        const dep = tasksById[depId];
        return dep ? resolveLevel(dep) + 1 : 1;
      }),
    );
    levelMap[task.id] = level;
    return level;
  };

  const sortedTasks = [...planGraph.nodes].sort((a, b) => {
    const levelDiff = resolveLevel(a) - resolveLevel(b);
    if (levelDiff !== 0) return levelDiff;
    return laneOrder.indexOf(a.assigned_to) - laneOrder.indexOf(b.assigned_to);
  });

  const maxLevel = sortedTasks.reduce((max, task) => Math.max(max, resolveLevel(task)), 0);
  const tasksPerLevel = sortedTasks.reduce<Record<number, number>>((counts, task) => {
    const level = resolveLevel(task);
    counts[level] = (counts[level] || 0) + 1;
    return counts;
  }, {});
  const maxTasksInLevel = Math.max(...Object.values(tasksPerLevel), 1);
  const useCompactLongChain = maxLevel >= 5 && maxTasksInLevel <= 2;
  const compactColumns = getCompactColumnCount();
  const compactStackGap = 132;
  const compactRowHeight = maxTasksInLevel > 1 ? 292 : 172;

  const levelCounts: Record<number, number> = {};
  sortedTasks.forEach((task, taskIndex) => {
    const level = resolveLevel(task);
    const stackIndex = levelCounts[level] || 0;
    levelCounts[level] = stackIndex + 1;
    const legacyTask = graphTaskToTask(task);
    const unverifiedDemo = containsUnverifiedDemo(task.result, task.code, task.structured_data);
    const styleState = getTaskStyleByStatus(unverifiedDemo ? 'unverified_demo' : task.status);

    let position = {
      x: 64 + level * 316,
      y: 82 + (stackIndex + (maxTasksInLevel - tasksPerLevel[level]) / 2) * 154,
    };
    let sourcePosition = Position.Right;
    let targetPosition = Position.Left;

    if (useCompactLongChain) {
      const row = Math.floor(level / compactColumns);
      const naturalColumn = level % compactColumns;
      const column = row % 2 === 0 ? naturalColumn : compactColumns - naturalColumn - 1;
      const startsNewRow = naturalColumn === 0 && row > 0;
      const endsRow = naturalColumn === compactColumns - 1 && level < maxLevel;
      const levelStackOffset = ((maxTasksInLevel - tasksPerLevel[level]) * compactStackGap) / 2;

      position = {
        x: 64 + column * 304,
        y: 82 + row * compactRowHeight + levelStackOffset + stackIndex * compactStackGap,
      };
      targetPosition = startsNewRow ? Position.Top : row % 2 === 0 ? Position.Left : Position.Right;
      sourcePosition = endsRow ? Position.Bottom : row % 2 === 0 ? Position.Right : Position.Left;
    }

    newNodes.push({
      id: task.id,
      position,
      sourcePosition,
      targetPosition,
      className: 'repropilot-task-node',
      data: {
        task: legacyTask,
        status: task.status,
        unverifiedDemo,
        step: taskIndex + 1,
        label: createTaskNodeLabel({
          assignedTo: task.assigned_to,
          taskName: task.name,
          status: task.status,
          step: taskIndex + 1,
          unverifiedDemo,
        }),
      },
      style: {
        borderRadius: '8px',
        backgroundColor: styleState.backgroundColor,
        border: '1px solid',
        borderColor: styleState.borderColor,
        boxShadow: 'none',
        cursor: 'pointer',
        overflow: 'hidden',
        padding: 0,
        width: NODE_WIDTH,
        minHeight: NODE_HEIGHT,
      },
    });
  });

  selectVisibleEdges(planGraph).forEach((edge) => {
    const isDataEdge = edge.type === 'data';
    newEdges.push({
      id: edge.id,
      source: edge.from,
      target: edge.to,
      type: 'smoothstep',
      animated: false,
      className: 'workflow-edge',
      data: { edgeType: edge.type },
      style: {
        stroke: '#c9c4ba',
        strokeWidth: 1.25,
        strokeDasharray: isDataEdge ? '5 5' : undefined,
      },
      markerEnd: {
        type: MarkerType.ArrowClosed,
        color: '#c9c4ba',
        width: 14,
        height: 14,
      },
    });
  });

  return { nodes: newNodes, edges: newEdges };
};
