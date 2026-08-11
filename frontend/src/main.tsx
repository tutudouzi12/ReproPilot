import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import { AppErrorBoundary } from './app/AppErrorBoundary.tsx'
import { AppProviders } from './app/AppProviders.tsx'
import ReproPilotApp from './app/ReproPilotApp.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <AppErrorBoundary>
      <AppProviders>
        <ReproPilotApp />
      </AppProviders>
    </AppErrorBoundary>
  </StrictMode>,
)
