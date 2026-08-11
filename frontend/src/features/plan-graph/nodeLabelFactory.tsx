import { getAgentIcon } from '../shared/agentVisuals';

interface CreateTaskNodeLabelOptions {
  assignedTo: string;
  taskName: string;
  status: string;
  step?: number;
  unverifiedDemo?: boolean;
}

const agentLabels: Record<string, string> = {
  librarian_agent: '文献智能体',
  coder_agent: '代码智能体',
  sandbox_agent: '沙箱智能体',
  data_agent: '数据智能体',
  research_coding_agent: '科研 Coding 智能体',
  general_agent: '通用智能体',
};

const statusMeta: Record<string, { label: string; className: string }> = {
  pending: { label: '等待', className: 'is-pending' },
  ready: { label: '就绪', className: 'is-ready' },
  in_progress: { label: '运行中', className: 'is-running' },
  completed: { label: '已完成', className: 'is-completed' },
  unverified_demo: { label: '演示·未验证', className: 'is-unverified' },
  failed: { label: '失败', className: 'is-failed' },
  blocked: { label: '已阻塞', className: 'is-blocked' },
};

statusMeta.canceled = { label: '已取消', className: 'is-canceled' };

const getPrimaryTaskName = (taskName: string) => taskName.split(/\s+\/\s+/)[0]?.trim() || taskName;

export const createTaskNodeLabel = (options: CreateTaskNodeLabelOptions) => {
  const { assignedTo, taskName, status, step, unverifiedDemo = false } = options;
  const visualStatus = unverifiedDemo ? 'unverified_demo' : status;
  const statusState = statusMeta[visualStatus] ?? statusMeta.pending;

  return (
    <div className={`repropilot-node-card ${statusState.className}`}>
      <div className="repropilot-node-card__header">
        <div className="repropilot-node-card__agent">
          <span className="repropilot-node-card__agent-icon">{getAgentIcon(assignedTo)}</span>
          <span className="truncate">{agentLabels[assignedTo] ?? assignedTo}</span>
        </div>
        <span className="repropilot-node-card__status-dot" aria-label={statusState.label} title={statusState.label} />
      </div>

      <div className="repropilot-node-card__title" title={taskName}>
        {getPrimaryTaskName(taskName)}
      </div>

      <div className="repropilot-node-card__meta">
        {typeof step === 'number' && <span>Step {String(step).padStart(2, '0')}</span>}
        {typeof step === 'number' && <span className="repropilot-node-card__meta-divider" />}
        <span className="repropilot-node-card__status-label">{statusState.label}</span>
      </div>
    </div>
  );
};
