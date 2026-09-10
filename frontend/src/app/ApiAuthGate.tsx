import { type FormEvent, type ReactNode, useEffect, useState } from 'react';
import { KeyRound, RefreshCw } from 'lucide-react';
import { createApiAuthSession, getApiAuthStatus } from '../services/api/authApi';

interface ApiAuthGateProps {
  children: ReactNode;
}

type AuthGateState = 'checking' | 'ready' | 'required' | 'unavailable';

export function ApiAuthGate({ children }: ApiAuthGateProps) {
  const [state, setState] = useState<AuthGateState>('checking');
  const [token, setToken] = useState('');
  const [error, setError] = useState('');
  const [submitting, setSubmitting] = useState(false);

  const retryStatus = async () => {
    setState('checking');
    setError('');
    try {
      const status = await getApiAuthStatus();
      setState(status.enabled && !status.authenticated ? 'required' : 'ready');
    } catch {
      setState('unavailable');
    }
  };

  useEffect(() => {
    let active = true;
    void getApiAuthStatus()
      .then((status) => {
        if (active) setState(status.enabled && !status.authenticated ? 'required' : 'ready');
      })
      .catch(() => {
        if (active) setState('unavailable');
      });
    return () => {
      active = false;
    };
  }, []);

  const submitToken = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const trimmedToken = token.trim();
    if (!trimmedToken || submitting) return;

    setSubmitting(true);
    setError('');
    try {
      const status = await createApiAuthSession(trimmedToken);
      if (status.authenticated) {
        setToken('');
        setState('ready');
      }
    } catch {
      setError('Token 无效，请检查 API_AUTH_TOKEN 后重试。');
    } finally {
      setSubmitting(false);
    }
  };

  if (state === 'ready') return children;

  if (state === 'checking') {
    return (
      <main className="api-auth-gate" aria-live="polite">
        <section className="api-auth-card api-auth-card--status">
          <span className="repropilot-loading-dot" />
          <p>正在检查 Backend 认证状态…</p>
        </section>
      </main>
    );
  }

  if (state === 'unavailable') {
    return (
      <main className="api-auth-gate">
        <section className="api-auth-card">
          <div className="api-auth-card__icon"><RefreshCw aria-hidden="true" /></div>
          <p className="api-auth-card__eyebrow">Backend unavailable</p>
          <h1>无法连接 ReproPilot Backend</h1>
          <p className="api-auth-card__copy">请确认 Backend 已启动，然后重试连接。</p>
          <button type="button" className="workspace-button workspace-button-primary api-auth-card__submit" onClick={() => void retryStatus()}>
            重新连接
          </button>
        </section>
      </main>
    );
  }

  return (
    <main className="api-auth-gate">
      <form className="api-auth-card" onSubmit={(event) => void submitToken(event)}>
        <div className="api-auth-card__icon"><KeyRound aria-hidden="true" /></div>
        <p className="api-auth-card__eyebrow">Protected deployment</p>
        <h1>输入 API 访问 Token</h1>
        <p className="api-auth-card__copy">Backend 已启用 API_AUTH_TOKEN。Token 仅用于创建当前浏览器会话，不会写入前端存储。</p>
        <label className="api-auth-card__label" htmlFor="api-auth-token">API_AUTH_TOKEN</label>
        <input
          id="api-auth-token"
          className="api-auth-card__input"
          type="password"
          autoComplete="current-password"
          value={token}
          onChange={(event) => setToken(event.target.value)}
          disabled={submitting}
          autoFocus
        />
        {error && <p className="api-auth-card__error" role="alert">{error}</p>}
        <button type="submit" className="workspace-button workspace-button-primary api-auth-card__submit" disabled={!token.trim() || submitting}>
          {submitting ? '正在验证…' : '进入工作台'}
        </button>
      </form>
    </main>
  );
}
