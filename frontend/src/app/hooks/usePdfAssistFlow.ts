import { useCallback, useState } from 'react';

interface UsePdfAssistFlowOptions {
  setPrompt: (value: string) => void;
  appendSelectedTaskLog: (line: string) => void;
}

export function usePdfAssistFlow(options: UsePdfAssistFlowOptions) {
  const { setPrompt, appendSelectedTaskLog } = options;
  const [pdfUrl, setPdfUrl] = useState<string | null>(null);
  const [showSuggestions, setShowSuggestions] = useState(true);

  const handleAskAI = useCallback(
    (selectedText: string) => {
      setPrompt(`请帮我详细解释这篇文献中的这段内容：\n"${selectedText}"`);
      appendSelectedTaskLog('[System] 已获取划词内容，准备向 ReproPilot 发起追问...');
    },
    [appendSelectedTaskLog, setPrompt],
  );

  return {
    pdfUrl,
    setPdfUrl,
    showSuggestions,
    setShowSuggestions,
    onAskAI: handleAskAI,
  };
}
