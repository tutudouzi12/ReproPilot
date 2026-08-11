import type { PropsWithChildren } from 'react';
import { ReproPilotRuntimeContext, type ReproPilotRuntimeContextValue } from './ReproPilotRuntimeContext';

interface ReproPilotRuntimeProviderProps extends PropsWithChildren {
  value: ReproPilotRuntimeContextValue;
}

export function ReproPilotRuntimeProvider({ value, children }: ReproPilotRuntimeProviderProps) {
  return <ReproPilotRuntimeContext.Provider value={value}>{children}</ReproPilotRuntimeContext.Provider>;
}
