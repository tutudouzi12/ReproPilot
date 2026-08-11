import { useState } from 'react';
import { ChevronDown, ChevronUp, LogIn, MessageSquarePlus, UserRound } from 'lucide-react';

interface SessionSummary {
  id: string;
  title: string;
  updatedAt: string;
  messageCount: number;
}

interface SessionManagerState {
  isLoggedIn: boolean;
  userId: string | null;
  loginInput: string;
  activeSessionId: string | null;
  sessions: SessionSummary[];
  loading: boolean;
}

interface SessionManagerActions {
  setLoginInput: (value: string) => void;
  onLogin: () => void;
  onCreateSession: () => void;
  onSwitchSession: (sessionId: string) => void;
}

interface ChatSessionManagerProps {
  state: SessionManagerState;
  actions: SessionManagerActions;
}

const formatTime = (value: string) => {
  const time = new Date(value);
  if (Number.isNaN(time.getTime())) return '--';
  return time.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
};

export function ChatSessionManager(props: ChatSessionManagerProps) {
  const { state, actions } = props;
  const [showAccount, setShowAccount] = useState(false);

  return (
    <div className="research-session-manager">
      <div className="research-session-actions">
        <div>
          <div className="research-session-title">Research</div>
          <div className="research-session-caption">Sessions and source context</div>
        </div>
        <button
          onClick={actions.onCreateSession}
          disabled={state.loading}
          className="new-research-button"
        >
          <MessageSquarePlus className="h-3.5 w-3.5" />
          New Research
        </button>
      </div>

      <div className="research-session-label">Recent</div>
      <div className="research-session-list">
        {state.sessions.map((session) => {
          const isActive = session.id === state.activeSessionId;
          return (
            <button
              key={session.id}
              onClick={() => actions.onSwitchSession(session.id)}
              className={`research-session-item ${isActive ? 'is-active' : ''}`}
            >
              <div className="flex items-center justify-between gap-3">
                <div className="research-session-item__title">{session.title}</div>
                <div className="research-session-item__count">{session.messageCount}</div>
              </div>
              <div className="research-session-item__meta">
                <span className="truncate">Research session</span>
                <span className="shrink-0">{formatTime(session.updatedAt)}</span>
              </div>
            </button>
          );
        })}
      </div>

      <div className="research-account">
        <button
          type="button"
          onClick={() => setShowAccount((value) => !value)}
          className="research-account__toggle"
        >
          <span className="flex min-w-0 items-center gap-2">
            <UserRound className="h-3.5 w-3.5" />
            <span className="truncate">{state.isLoggedIn ? state.userId : 'Guest workspace'}</span>
          </span>
          {showAccount ? <ChevronUp className="h-3.5 w-3.5" /> : <ChevronDown className="h-3.5 w-3.5" />}
        </button>

        {showAccount && !state.isLoggedIn && (
          <div className="research-account__login">
            <input
              value={state.loginInput}
              onChange={(event) => actions.setLoginInput(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === 'Enter') {
                  event.preventDefault();
                  actions.onLogin();
                }
              }}
              placeholder="User ID"
              className="research-account__input"
            />
            <button
              onClick={actions.onLogin}
              disabled={state.loading || !state.loginInput.trim()}
              className="workspace-button workspace-button-graphite"
            >
              <LogIn className="h-3.5 w-3.5" />
              Save
            </button>
          </div>
        )}
      </div>
    </div>
  );
}
