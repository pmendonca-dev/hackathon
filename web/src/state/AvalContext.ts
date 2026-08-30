import { createContext, useContext } from 'react';

import type {
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
} from '../contracts/avalGateway.ts';

export type View = 'human' | 'merchant' | 'auditor' | 'trial';

export interface AvalContextValue {
  snapshot: AvalSnapshot | null;
  loading: boolean;
  error: string | null;
  view: View;
  lastCommandReceipt: TrialCommandReceipt | null;
  setView(view: View): void;
  reload(): Promise<void>;
  submitTrialCommand(command: TrialCommand): Promise<void>;
}

export const AvalContext = createContext<AvalContextValue | null>(null);

export function useAval(): AvalContextValue {
  const context = useContext(AvalContext);
  if (!context) throw new Error('useAval must be used inside AvalProvider');
  return context;
}
