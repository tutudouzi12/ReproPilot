import { Bot, Code, Database, FileText, TerminalSquare, Wrench } from 'lucide-react';

export const getAgentIcon = (agentName: string) => {
  switch (agentName) {
    case 'librarian_agent':
      return <FileText className="h-4 w-4" />;
    case 'coder_agent':
      return <Code className="h-4 w-4" />;
    case 'sandbox_agent':
      return <TerminalSquare className="h-4 w-4" />;
    case 'data_agent':
      return <Database className="h-4 w-4" />;
    case 'research_coding_agent':
      return <Wrench className="h-4 w-4" />;
    default:
      return <Bot className="h-4 w-4" />;
  }
};

export const getTaskStyleByStatus = (status?: string) => {
  switch (status) {
    case 'ready':
      return { borderColor: '#d8b8a9', backgroundColor: '#fffdfa' };
    case 'in_progress':
      return { borderColor: '#b65f3c', backgroundColor: '#fbf3ee' };
    case 'completed':
      return { borderColor: '#b9c1b2', backgroundColor: '#fbfcfa' };
    case 'unverified_demo':
      return { borderColor: '#c7b8c2', backgroundColor: '#fcfafb' };
    case 'failed':
      return { borderColor: '#cba9a4', backgroundColor: '#fdf9f8' };
    case 'blocked':
      return { borderColor: '#d2cec6', backgroundColor: '#f2f0eb' };
    default:
      return { borderColor: '#ddd9d1', backgroundColor: '#fffefa' };
  }
};
