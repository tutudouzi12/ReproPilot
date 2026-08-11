import { useCallback, useRef, useState } from 'react';
import { FileUp, MessageSquare, Minus, Plus, Sparkles, X } from 'lucide-react';
import { Document, Page, pdfjs } from 'react-pdf';
import type { ChatResponse } from '../../contracts/api';
import { httpClient } from '../../services/api/httpClient';
import 'react-pdf/dist/Page/AnnotationLayer.css';
import 'react-pdf/dist/Page/TextLayer.css';

const pdfWorkerUrl = new URL('pdfjs-dist/build/pdf.worker.min.mjs', import.meta.url);
pdfWorkerUrl.searchParams.set('repropilot-worker', '1');
pdfjs.GlobalWorkerOptions.workerSrc = pdfWorkerUrl.toString();

interface PdfPanelProps {
  pdfUrl: string;
  onAskAI: (text: string) => void;
}

interface TextSelection {
  text: string;
  left: number;
  top: number;
}

const translationErrorMessage = (error: unknown): string => {
  if (!error || typeof error !== 'object') return '请求 AI 翻译失败，请重试。';
  const response = (error as { response?: { data?: { detail?: unknown } } }).response;
  const detail = response?.data?.detail;
  return typeof detail === 'string' && detail.trim()
    ? `翻译暂不可用：${detail}`
    : '请求 AI 翻译失败，请检查后端服务后重试。';
};

export function PdfPanel({ pdfUrl, onAskAI }: PdfPanelProps) {
  const contentRef = useRef<HTMLDivElement>(null);
  const [numPages, setNumPages] = useState(0);
  const [scale, setScale] = useState(1);
  const [loadError, setLoadError] = useState('');
  const [selection, setSelection] = useState<TextSelection | null>(null);
  const [translatedText, setTranslatedText] = useState('');
  const [isTranslating, setIsTranslating] = useState(false);

  const closeAssistant = useCallback(() => {
    setSelection(null);
    setTranslatedText('');
    setIsTranslating(false);
    window.getSelection()?.removeAllRanges();
  }, []);

  const handleTextSelection = useCallback(() => {
    const browserSelection = window.getSelection();
    const text = browserSelection?.toString().trim() ?? '';
    const anchor = browserSelection?.anchorNode;
    const anchorElement = anchor instanceof Element ? anchor : anchor?.parentElement;
    if (!text || !anchorElement || !contentRef.current?.contains(anchorElement)) {
      return;
    }
    const range = browserSelection?.rangeCount ? browserSelection.getRangeAt(0) : null;
    const rect = range?.getBoundingClientRect();
    if (!rect) return;
    setTranslatedText('');
    setSelection({
      text,
      left: Math.max(16, Math.min(rect.left, window.innerWidth - 344)),
      top: Math.max(16, Math.min(rect.bottom + 8, window.innerHeight - 260)),
    });
  }, []);

  const fetchTranslation = useCallback(async () => {
    if (!selection?.text) return;
    setIsTranslating(true);
    setTranslatedText('');
    try {
      const response = await httpClient.post<ChatResponse>('/api/chat', {
        message: `请把下面的论文片段准确翻译成中文。保留公式、数字、引用和专业术语，不添加原文没有的结论：\n\n${selection.text}`,
      });
      setTranslatedText(response.data.response);
    } catch (error: unknown) {
      setTranslatedText(translationErrorMessage(error));
    } finally {
      setIsTranslating(false);
    }
  }, [selection]);

  return (
    <div className="pdf-workspace">
      <div className="pdf-toolbar">
        <span>正在阅读论文 PDF</span>
        <div>
          <button
            type="button"
            aria-label="缩小 PDF"
            onClick={() => setScale((value) => Math.max(0.6, Number((value - 0.1).toFixed(1))))}
            className="pdf-toolbar-button"
          >
            <Minus className="w-3 h-3" />
          </button>
          <span>{Math.round(scale * 100)}% · {numPages || '-'} 页</span>
          <button
            type="button"
            aria-label="放大 PDF"
            onClick={() => setScale((value) => Math.min(2, Number((value + 0.1).toFixed(1))))}
            className="pdf-toolbar-button"
          >
            <Plus className="w-3 h-3" />
          </button>
          <span className="pdf-toolbar-meta">
            <FileUp className="w-3 h-3" /> 切换文档
          </span>
        </div>
      </div>

      <div ref={contentRef} onMouseUp={handleTextSelection} className="pdf-canvas">
        <Document
          file={pdfUrl}
          loading={<div className="p-6 text-center text-sm text-gray-500">正在加载 PDF...</div>}
          error={<div className="p-6 text-center text-sm text-red-600">{loadError || 'PDF 加载失败'}</div>}
          onLoadSuccess={({ numPages: loadedPages }) => {
            setNumPages(loadedPages);
            setLoadError('');
          }}
          onLoadError={(error) => setLoadError(error.message)}
        >
          {Array.from({ length: numPages }, (_, index) => (
            <div key={`page-${index + 1}`} className="pdf-page">
              <Page
                pageNumber={index + 1}
                scale={scale}
                renderAnnotationLayer
                renderTextLayer
              />
            </div>
          ))}
        </Document>
      </div>

      {selection && (
        <div
          style={{ position: 'fixed', left: selection.left, top: selection.top, zIndex: 120, width: 328 }}
          className="pdf-assistant"
        >
          <div className="pdf-assistant__header">
            <span>
              <Sparkles className="h-3 w-3" /> AI 论文助手
            </span>
            <button type="button" onClick={closeAssistant} aria-label="关闭 AI 论文助手">
              <X className="h-4 w-4" />
            </button>
          </div>
          <div className="pdf-assistant__body">
            <p className="pdf-assistant__quote">{selection.text}</p>
            {!translatedText && !isTranslating && (
              <button
                type="button"
                onClick={fetchTranslation}
                className="workspace-button workspace-button-primary w-full"
              >
                AI 翻译至中文
              </button>
            )}
            {isTranslating && (
              <div className="pdf-assistant__loading">
                <span className="repropilot-loading-dot" /> 正在请求 ReproPilot 翻译...
              </div>
            )}
            {translatedText && <p className="pdf-assistant__translation">{translatedText}</p>}
            <button
              type="button"
              onClick={() => {
                onAskAI(selection.text);
                closeAssistant();
              }}
              className="workspace-button workspace-button-secondary w-full"
            >
              <MessageSquare className="h-3 w-3" /> 针对此段落向 ReproPilot 追问
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
