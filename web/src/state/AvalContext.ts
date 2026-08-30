import { createContext, useContext } from 'react';

import type {
  AgentRun,
  CatalogOffer,
  Escalation,
  LedgerEntry,
  MandateView,
  Metrics,
  Money,
  Watch,
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
  /** Instance-wide counters, read from the runtime. Null when it did not answer. */
  metrics: Metrics | null;
  /** Standing orders on the selected mandate — the agent still working unwatched. */
  watches: Watch[];
  /** The merchant's signed offers, so a judge can pick the price to drop. */
  offers: CatalogOffer[];
  /**
   * The instant the runtime reads validity against, which a judge can move. Null when
   * it did not answer; the form then falls back to this browser's clock and says so.
   */
  serverNow: string | null;

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
  /**
   * Keep the instruction standing, so the agent retries it after the person stops
   * typing. Always an explicit act: a purchase that found nothing never opens one by
   * itself, because a standing spending order nobody asked for is worse than a "no".
   */
  watchInstruction(instruction: string): Promise<void>;
  /** Try every open standing order on the selected mandate once. */
  tickWatches(): Promise<void>;
  decideEscalation(escalationId: string, decision: 'approve' | 'deny'): Promise<void>;
  changeLimit(minorUnits: number): Promise<void>;
  revokeSelected(): Promise<void>;
  revokeEverything(): Promise<void>;
  setPspMode(mode: 'online' | 'offline' | 'decline'): Promise<void>;
  reconcile(): Promise<void>;
  advanceClock(seconds: number): Promise<void>;
  /**
   * Move a catalogue price. It ends a standing order's waiting and authorizes nothing:
   * the watch it wakes faces the same mandate a typed instruction would.
   */
  repriceOffer(sku: string, minorUnits: number): Promise<void>;
  tamperLedger(sequence: number): Promise<void>;
}

export const AvalContext = createContext<AvalContextValue | null>(null);

export function useAval(): AvalContextValue {
  const context = useContext(AvalContext);
  if (!context) throw new Error('useAval must be used inside AvalProvider');
  return context;
}
