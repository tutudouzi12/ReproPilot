import type { ReactNode } from 'react';
import { FileText, X } from 'lucide-react';
import { ChatPanel } from '../../features/chat/ChatPanel';
import { PdfPanel } from '../../features/pdf-viewer/PdfPanel';
import type { ChatMessage, UploadedFile } from '../../contracts/api';

interface LeftWorkspaceShellProps {
  width: number;
  showClosePdf: boolean;
  onClosePdf: () => void;
  children: ReactNode;
}

function LeftWorkspaceShell(props: LeftWorkspaceShellProps) {
  const { width, showClosePdf, onClosePdf, children } = props;

  return (
    <div
      style={{ width: `${width}px` }}
      className="repropilot-left-workspace relative z-10 flex flex-shrink-0 flex-col overflow-hidden"
    >
      {showClosePdf && (
        <div className="paper-workspace-header">
          <div className="flex items-center gap-2 text-xs font-semibold">
            <FileText className="h-4 w-4" />
            Paper viewer
          </div>
          <button onClick={onClosePdf} className="workspace-icon-button" aria-label="关闭论文阅读器">
            <X className="w-5 h-5" />
          </button>
        </div>
      )}
      {children}
    </div>
  );
}

interface LeftWorkspaceChatProps {
  width: number;
  state: {
    chatHistory: ChatMessage[];
    loading: boolean;
    prompt: string;
    showSuggestions: boolean;
	pendingAttachments: UploadedFile[];
	uploadingAttachments: boolean;
	attachmentError: string;
    isLoggedIn: boolean;
    userId: string | null;
    loginInput: string;
    activeSessionId: string | null;
    sessions: Array<{
      id: string;
      title: string;
      createdAt: string;
      updatedAt: string;
      messageCount: number;
    }>;
  };
  chatActions: {
    setPrompt: (value: string) => void;
    setShowSuggestions: (next: boolean) => void;
    onSendMessage: () => void;
    setLoginInput: (value: string) => void;
    onLogin: () => void;
    onCreateSession: () => void;
    onSwitchSession: (sessionId: string) => void;
	onAttachFiles: (files: File[]) => void;
	onRemoveAttachment: (uploadId: string) => void;
  };
  pdfActions: {
    onOpenPdf: (url?: string) => void;
    onClosePdf: () => void;
  };
  taskActions: {
    onOpenTaskView: (taskId: string, mode: 'plot' | 'report') => void;
  };
}

export function LeftWorkspaceChat(props: LeftWorkspaceChatProps) {
  const { width, state, chatActions, pdfActions, taskActions } = props;
  return (
    <LeftWorkspaceShell width={width} showClosePdf={false} onClosePdf={pdfActions.onClosePdf}>
      <ChatPanel state={state} chatActions={chatActions} pdfActions={pdfActions} taskActions={taskActions} />
    </LeftWorkspaceShell>
  );
}

interface LeftWorkspacePdfProps {
  width: number;
  pdfUrl: string;
  onClosePdf: () => void;
  onAskAI: (text: string) => void;
}

export function LeftWorkspacePdf(props: LeftWorkspacePdfProps) {
  const { width, pdfUrl, onClosePdf, onAskAI } = props;
  return (
    <LeftWorkspaceShell width={width} showClosePdf onClosePdf={onClosePdf}>
      <PdfPanel
        pdfUrl={pdfUrl}
        onAskAI={onAskAI}
      />
    </LeftWorkspaceShell>
  );
}
