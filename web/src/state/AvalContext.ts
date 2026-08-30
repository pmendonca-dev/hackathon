import { createContext, useContext } from 'react';

import type {
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
  UiAuditProjection,
  UiDisputeProjection,
  UiLoginRequest,
  UiRole,
  UiWorkspaceProjection,
} from '../contracts/avalGateway.ts';
import type { AvalErrorPresentation } from '../errors/avalError.ts';

export type View = 'human' | 'merchant' | 'auditor' | 'trial';

export interface AvalContextValue {
  snapshot: AvalSnapshot | null;
  workspace: UiWorkspaceProjection | null;
  audit: UiAuditProjection | null;
  dispute: UiDisputeProjection | null;
  session: { role: UiRole; expiresAt: string } | null;
  dataSource: 'mock' | 'api';
  loading: boolean;
  error: AvalErrorPresentation | null;
  view: View;
  lastCommandReceipt: TrialCommandReceipt | null;
  setView(view: View): void;
  login(request: UiLoginRequest): Promise<void>;
  logout(): Promise<void>;
  reload(): Promise<void>;
  submitTrialCommand(command: TrialCommand): Promise<void>;
}

export const AvalContext = createContext<AvalContextValue | null>(null);

export function useAval(): AvalContextValue {
  const context = useContext(AvalContext);
  if (!context) throw new Error('useAval must be used inside AvalProvider');
  return context;
}
