import { createContext, useContext } from 'react';

import type {
  AgentRun,
  Escalation,
  LedgerEntry,
  MandateView,
  Money,
} from '../gateways/authorizationGateway.ts';

export type View = 'human' | 'merchant' | 'auditor' | 'trial';

export interface ChainStatus {
  intact: boolean;
  checked: number;
  broken_at: number | null;
}

export interface CommandReceipt {
  label: string;
  outcome: 'accepted' | 'refused' | 'unreachable';
  reasonCode: string | null;
  message: string;
  at: string;
}

export interface AvalContextValue {
  /** Whose mandates this session is looking at. Every read is scoped to it. */
  principalId: string;
  /** The public half of the browser's holder key, once the wallet is ready. */
  holderKid: string | null;
  walletReady: boolean;
  view: View;
  loading: boolean;
  error: string | null;
  /** Present only when an operator token was configured for this session. */
  operatorAvailable: boolean;

  mandates: MandateView[];
  selectedMandateId: string | null;
  escalations: Escalation[];
  lastRun: AgentRun | null;
  humanEntries: LedgerEntry[];
  auditorEntries: LedgerEntry[];
  merchantEntries: LedgerEntry[];
  merchantRedactions: string[];
  chain: ChainStatus | null;
  receipts: CommandReceipt[];

  setView(view: View): void;
  setPrincipalId(principalId: string): void;
  selectMandate(mandateId: string): void;
  reload(): Promise<void>;

  createMandate(input: {
    displayName: string;
    merchants: string[];
    categories: string[];
    limit: Money;
    ceiling: Money | null;
    expiresAt: string;
    usageLimit: { max_uses: number; window_seconds: number } | null;
  }): Promise<void>;
  runAgent(instruction: string): Promise<void>;
  decideEscalation(escalationId: string, decision: 'approve' | 'deny'): Promise<void>;
  changeLimit(minorUnits: number): Promise<void>;
  revokeSelected(): Promise<void>;
  revokeEverything(): Promise<void>;
  setPspMode(mode: 'online' | 'offline' | 'decline'): Promise<void>;
  reconcile(): Promise<void>;
  advanceClock(seconds: number): Promise<void>;
  tamperLedger(sequence: number): Promise<void>;
}

export const AvalContext = createContext<AvalContextValue | null>(null);

export function useAval(): AvalContextValue {
  const context = useContext(AvalContext);
  if (!context) throw new Error('useAval must be used inside AvalProvider');
  return context;
}
