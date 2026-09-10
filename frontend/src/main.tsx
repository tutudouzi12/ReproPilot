import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { ApiAuthGate } from './app/ApiAuthGate.tsx'
import { AppErrorBoundary } from './app/AppErrorBoundary.tsx'
import { AppProviders } from './app/AppProviders.tsx'
import ReproPilotApp from './app/ReproPilotApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <ApiAuthGate>
        <AppProviders>
          <ReproPilotApp />
        </AppProviders>
      </ApiAuthGate>
    </AppErrorBoundary>
  </StrictMode>,
)
