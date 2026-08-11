import { useEffect, useRef } from 'react';
import { ChevronDown, ChevronUp, FileText, Paperclip, Send, Sparkles, X } from 'lucide-react';
import type { UploadedFile } from '../../contracts/api';

interface ChatComposerProps {
  prompt: string;
  loading: boolean;
  isLoggedIn: boolean;
  showSuggestions: boolean;
  isEmptyConversation: boolean;
  pendingAttachments: UploadedFile[];
  uploadingAttachments: boolean;
  attachmentError: string;
  setPrompt: (value: string) => void;
  setShowSuggestions: (next: boolean) => void;
  onSendMessage: () => void;
  onAttachFiles: (files: File[]) => void;
  onRemoveAttachment: (uploadId: string) => void;
}

const suggestions = [
  '帮我画一个正弦函数和余弦函数的对比图',
  '复现一下 Transformer 论文的核心架构并跑通测试',
  '对比一下 LangChain 和 LlamaIndex 的 RAG 性能',
  '分析一下这篇论文的主要创新点和局限性',
  '帮我复现 Attention Is All You Need 论文的代码',
];

export function ChatComposer(props: ChatComposerProps) {
  const {
    prompt,
    loading,
    isLoggedIn,
    showSuggestions,
    isEmptyConversation,
    pendingAttachments,
    uploadingAttachments,
    attachmentError,
    setPrompt,
    setShowSuggestions,
    onSendMessage,
    onAttachFiles,
    onRemoveAttachment,
  } = props;
  const fileInputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    if (!isEmptyConversation && showSuggestions) setShowSuggestions(false);
  }, [isEmptyConversation, setShowSuggestions, showSuggestions]);

  return (
    <div className="research-composer">
      <button
        type="button"
        onClick={() => setShowSuggestions(!showSuggestions)}
        className="research-suggestion-toggle"
        aria-expanded={showSuggestions}
      >
        <span className="flex items-center gap-1.5">
          <Sparkles />
          Research prompts
        </span>
        {showSuggestions ? <ChevronUp /> : <ChevronDown />}
      </button>

      {showSuggestions && (
        <div className="repropilot-suggestions-panel">
          {suggestions.map((text) => (
            <button
              key={text}
              type="button"
              onClick={() => setPrompt(text)}
              className="research-suggestion-item"
            >
              {text}
            </button>
          ))}
        </div>
      )}

      {(pendingAttachments.length > 0 || uploadingAttachments || attachmentError) && (
        <div className="mb-2 space-y-1.5" aria-live="polite">
          {pendingAttachments.map((attachment) => (
            <div key={attachment.id} className="flex max-w-full items-center gap-1.5 rounded-md border border-slate-200 bg-slate-50 px-2 py-1.5 text-[10px] text-slate-700">
              <FileText className="h-3.5 w-3.5 shrink-0 text-amber-700" />
              <span className="min-w-0 flex-1 truncate">{attachment.name}</span>
              <span className="shrink-0 font-mono text-[9px] text-slate-400">{Math.max(1, Math.round(attachment.size / 1024))} KB</span>
              <button
                type="button"
                onClick={() => onRemoveAttachment(attachment.id)}
                className="rounded p-0.5 text-slate-400 hover:bg-slate-200 hover:text-slate-700"
                title="移除附件"
                aria-label={`移除 ${attachment.name}`}
              >
                <X className="h-3.5 w-3.5" />
              </button>
            </div>
          ))}
          {uploadingAttachments && (
            <span className="flex items-center gap-1 text-[10px] text-amber-800">
              <span className="repropilot-loading-dot" />
              正在上传
            </span>
          )}
          {attachmentError && <span className="block text-[10px] leading-4 text-rose-600">{attachmentError}</span>}
        </div>
      )}

      <input
        ref={fileInputRef}
        type="file"
        multiple
        accept=".pdf,.txt,.md,.json,.jsonl,.yaml,.yml,.toml,.py,.ipynb,.csv,.tsv"
        className="hidden"
        onChange={(event) => {
          onAttachFiles(Array.from(event.target.files ?? []));
          event.target.value = '';
        }}
      />

      <div className="research-composer-box">
        <textarea
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === 'Enter' && !event.shiftKey) {
              event.preventDefault();
              onSendMessage();
            }
          }}
          placeholder="Describe a research task or attach source material…"
          aria-label="Research task"
          className="research-composer-input"
          rows={3}
        />
        <div className="research-composer-tools">
          <div className="flex items-center gap-1.5">
            <button
              type="button"
              onClick={() => fileInputRef.current?.click()}
              disabled={loading || uploadingAttachments || pendingAttachments.length >= 8}
              className="research-composer-attach"
              title="添加论文、数据或实验配置"
              aria-label="添加附件"
            >
              {uploadingAttachments ? <span className="repropilot-loading-dot" /> : <Paperclip className="h-4 w-4" />}
            </button>
            <span className="research-composer-session">{isLoggedIn ? 'Saved session' : 'Guest session'}</span>
          </div>
          <button
            type="button"
            onClick={onSendMessage}
            disabled={loading || uploadingAttachments || (!prompt.trim() && pendingAttachments.length === 0)}
            className="research-composer-send"
            title="发送消息"
            aria-label="发送消息"
          >
            <Send className="h-3.5 w-3.5" />
          </button>
        </div>
      </div>
      <div className="research-composer-hint">Enter to send · Shift + Enter for a new line</div>
    </div>
  );
}
