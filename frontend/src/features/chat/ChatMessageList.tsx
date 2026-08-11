import { Activity, Bot, CircleAlert, FileText, GitBranch, Maximize2, Microscope, Search, X } from 'lucide-react';
import type { ReactNode } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { ChatMessage } from '../../contracts/api';

interface PdfActions {
  onOpenPdf: (url?: string) => void;
  onClosePdf: () => void;
}

interface TaskActions {
  onOpenTaskView: (taskId: string, mode: 'plot' | 'report') => void;
}

interface ChatMessageListProps {
  chatHistory: ChatMessage[];
  loading: boolean;
  isLoggedIn: boolean;
  pdfActions: PdfActions;
  taskActions: TaskActions;
}

interface AssistantPresentation {
  label: string;
  icon: typeof Bot;
  className: string;
}

const resolveAssistantPresentation = (message: ChatMessage): AssistantPresentation => {
  const normalizedText = message.text.trim().toLowerCase();
  if (message.text.includes('请求未完成')) {
    return { label: 'Needs attention', icon: CircleAlert, className: 'is-failed' };
  }
  if (message.actions?.includes('view_plot') || message.actions?.includes('view_report')) {
    return { label: 'Result', icon: FileText, className: 'is-completed' };
  }
  if (message.text.includes('执行计划')) {
    return { label: 'Planning', icon: GitBranch, className: 'is-running' };
  }
  if (normalizedText.startsWith('[searching]') || message.text.startsWith('正在搜索')) {
    return { label: 'Searching', icon: Search, className: 'is-running' };
  }
  if (normalizedText.startsWith('[running]') || message.text.startsWith('正在运行')) {
    return { label: 'Running', icon: Activity, className: 'is-running' };
  }
  if (normalizedText.startsWith('[analyzing]') || message.text.startsWith('正在分析')) {
    return { label: 'Analyzing', icon: Microscope, className: 'is-running' };
  }
  return { label: 'Research response', icon: Bot, className: 'is-neutral' };
};

export function ChatMessageList(props: ChatMessageListProps) {
  const { chatHistory, loading, isLoggedIn, pdfActions, taskActions } = props;

  return (
    <div className="research-conversation">
      <div className="research-conversation-stream" data-guest={!isLoggedIn || undefined}>
        {chatHistory.map((message, index) =>
          message.role === 'user' ? (
            <UserMessage key={index} message={message} />
          ) : (
            <AssistantMessage
              key={index}
              message={message}
              pdfActions={pdfActions}
              taskActions={taskActions}
            />
          ),
        )}

        {loading && <PlanningActivity />}
      </div>
    </div>
  );
}

function UserMessage({ message }: { message: ChatMessage }) {
  return (
    <article className="repropilot-chat-message research-user-message">
      <div className="research-message-author">You</div>
      <div className="research-user-message__body">
        {message.text}
      </div>
    </article>
  );
}

function AssistantMessage({
  message,
  pdfActions,
  taskActions,
}: {
  message: ChatMessage;
  pdfActions: PdfActions;
  taskActions: TaskActions;
}) {
  const presentation = resolveAssistantPresentation(message);
  const PresentationIcon = presentation.icon;

  return (
    <article className="repropilot-chat-message research-agent-message">
      <header className="research-agent-message__header">
        <div className="research-agent-identity">
          <Bot />
          <span>ReproPilot</span>
        </div>
        <span className={`research-message-state ${presentation.className}`}>
          <PresentationIcon />
          {presentation.label}
        </span>
      </header>

      <div className="research-agent-message__body">
        <div className="research-message-prose prose max-w-none">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{message.text}</ReactMarkdown>
        </div>

        {message.actions && message.actions.length > 0 && (
          <MessageActions message={message} pdfActions={pdfActions} taskActions={taskActions} />
        )}
      </div>
    </article>
  );
}

function MessageActions({
  message,
  pdfActions,
  taskActions,
}: {
  message: ChatMessage;
  pdfActions: PdfActions;
  taskActions: TaskActions;
}) {
  return (
    <div className="research-message-actions">
      {message.actions?.includes('open_pdf') && (
        <ActionButton label="打开论文原文" icon={<FileText className="h-3 w-3" />} onClick={() => pdfActions.onOpenPdf(message.pdfUrl)} />
      )}
      {message.actions?.includes('close_pdf') && (
        <ActionButton label="关闭阅读器" icon={<X className="h-3 w-3" />} onClick={pdfActions.onClosePdf} />
      )}
      {message.actions?.includes('view_plot') && message.taskId && (
        <ActionButton
          label="查看生成的图表"
          icon={<Maximize2 className="h-3 w-3" />}
          onClick={() => taskActions.onOpenTaskView(message.taskId as string, 'plot')}
        />
      )}
      {message.actions?.includes('view_report') && message.taskId && (
        <ActionButton
          label="查看分析报告"
          icon={<FileText className="h-3 w-3" />}
          onClick={() => taskActions.onOpenTaskView(message.taskId as string, 'report')}
        />
      )}
    </div>
  );
}

function ActionButton({ label, icon, onClick }: { label: string; icon: ReactNode; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="research-message-action"
    >
      {icon}
      {label}
    </button>
  );
}

function PlanningActivity() {
  return (
    <details open className="repropilot-planning-activity" aria-live="polite">
      <summary>
        <span className="flex items-center gap-2">
          <span className="repropilot-loading-dot" />
          Planning workflow
        </span>
        <span className="research-message-state is-running">Running</span>
      </summary>
      <div className="repropilot-disclosure-content">
        Planner is structuring the multi-agent task graph. The workflow will appear in the center canvas when ready.
      </div>
    </details>
  );
}
