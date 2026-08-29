export type DataSource = 'mock' | 'api';
export type Tone = 'allow' | 'escalate' | 'deny' | 'verify' | 'hold' | 'neutral';

export interface Money {
  minorUnits: number;
  currency: string;
  scale: number;
}

export interface SnapshotMeta {
  dataSource: DataSource;
  fixtureId: `mock_${string}`;
  contractStatus: 'integrated';
  contractVersion: string;
  generatedAt: string;
  networkUsed: boolean;
}

export interface AuthorityRailProjection {
  maximumMinorUnits: number;
  zones: Array<{
    label: string;
    fromMinorUnits: number;
    toMinorUnits: number;
    tone: Tone;
  }>;
  marker: {
    label: string;
    atMinorUnits: number;
    tone: Tone;
  };
}

export interface ReceiptProjection {
  id: string;
  merchant: string;
  item: string;
  amount: Money;
  status: 'settled' | 'awaiting_human' | 'rejected';
  humanSummary: string;
  occurredAt: string;
  receiptHash: string;
}

export interface HumanViewProjection {
  principalName: string;
  mandate: {
    id: string;
    status: 'active' | 'revoked' | 'expired';
    agentName: string;
    purpose: string;
    perTransactionLimit: Money;
    ceiling: Money;
    liveAllowance: Money;
    allowanceCheckedAt: string;
    scopes: string[];
    vaultToken: `vt_${string}`;
    revocation: {
      state: 'clear' | 'revoked' | 'unavailable';
      checkedAt: string;
      epoch: number;
    };
    authorityRail: AuthorityRailProjection;
  };
  latestDecision: {
    status: 'authorized' | 'awaiting_human' | 'rejected';
    reasonCode: string;
    humanSummary: string;
    reservationState: 'pending' | 'committed' | 'settled' | 'released';
    policyVersion: string;
    evidenceRef: string;
  };
  receipts: ReceiptProjection[];
}

export interface MerchantViewProjection {
  merchantName: string;
  receipt: {
    receiptId: string;
    transactionRef: string;
    amount: Money;
    status: 'settled';
    paymentToken: `vt_${string}`;
    itemSummary: string;
    occurredAt: string;
  };
  checks: Array<{
    label: string;
    result: 'verified' | 'not-shared';
    detail: string;
  }>;
  signedEvidence: {
    ap2Version: 'v0.2';
    checkoutReceiptHash: string;
    paymentReceiptHash: string;
    authorizationProofRef: string;
  };
}

export interface AuditEventProjection {
  sequence: number;
  id: string;
  occurredAt: string;
  actor: string;
  actorRole: string;
  eventType: string;
  reasonCode: string;
  humanSummary: string;
  reservationState: 'pending' | 'committed' | 'settled' | 'released';
  evidenceRef: string;
  integrityHash: string;
}

export interface AuditorViewProjection {
  chainStatus: 'verified' | 'broken';
  chainHead: string;
  events: AuditEventProjection[];
  dispute: {
    id: string;
    status: 'reconstructed' | 'under_review';
    merchant: string;
    amount: Money;
    claim: string;
    verdictSummary: string;
    evidenceRefs: string[];
  };
}

export interface AvalSnapshot {
  meta: SnapshotMeta;
  human: HumanViewProjection;
  merchant: MerchantViewProjection;
  auditor: AuditorViewProjection;
}

export type TrialCommandKind =
  | 'lower-limit'
  | 'change-scope'
  | 'budget-zero'
  | 'revoke-mandate';

export interface TrialCommand {
  kind: TrialCommandKind;
  targetId: string;
  requestedValue: string;
}

export interface TrialCommandReceipt {
  requestId: string;
  dataSource: DataSource;
  outcome: 'fixture-only' | 'accepted' | 'rejected';
  canonicalStateChanged: boolean;
  effectiveAt: string | null;
  message: string;
}

/**
 * Only replaceable seam between browser and AVAL. Implementations transport
 * snapshots and commands; they never own authorization policy or payment state.
 */
export interface AvalGateway {
  loadWorkspace(): Promise<AvalSnapshot>;
  submitTrialCommand(command: TrialCommand): Promise<TrialCommandReceipt>;
}
