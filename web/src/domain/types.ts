// ── Domain model ────────────────────────────────────────────────────────────
// Mirrors the canonical entities of the AVAL briefing (§5.1). Two independent
// state machines, never a third: a Mandate is authority, a Reservation is money.
//
//   Mandate      ACTIVE ──► REVOKED        (monotonic, irreversible)
//                   └────► EXPIRED
//   Reservation  PENDING ─► COMMITTED ─► SETTLED
//                   │            └─────► RELEASED   (settlement failed)
//                   └──────────────────► RELEASED   (rejected at commit)

export type MandateStatus = 'ACTIVE' | 'ESCALATED' | 'REVOKED' | 'EXPIRED';

export type Decision = 'ALLOW' | 'ESCALATE' | 'DENY';

export type PaymentStatus =
  | 'SETTLED'
  | 'ESCALATED'
  | 'DECLINED'
  | 'IN_DOUBT'
  | 'IN_CONFIRMATION'
  | 'RECONCILING'
  | 'COMPENSATED'
  | 'AWAITING_CAPTURE';

export type ReasonCode =
  | 'WITHIN_TRANSACTION_LIMIT'
  | 'EXCEEDS_TRANSACTION_LIMIT'
  | 'MANDATE_CEILING_EXCEEDED'
  | 'MONTHLY_BUDGET_EXCEEDED'
  | 'MANDATE_REVOKED'
  | 'MANDATE_EXPIRED'
  | 'MERCHANT_SCOPE_VIOLATION'
  | 'RESERVATION_LIMIT'
  | 'REQUEST_NONCE_REPLAY'
  | 'WEBHOOK_SIGNATURE_INVALID'
  | 'WEBHOOK_REPLAY'
  | 'PSP_NO_DEFINITIVE_RESPONSE'
  | 'PSP_DECLINED'
  | 'DEMO_ENDPOINT_NOT_AVAILABLE';

/** Human-facing gloss for each machine reason code. Never shown without it. */
export const REASON_TEXT: Record<ReasonCode, string> = {
  WITHIN_TRANSACTION_LIMIT: 'Amount sits inside the automatic authorization band.',
  EXCEEDS_TRANSACTION_LIMIT: 'Amount is above the per-transaction limit but below the mandate ceiling.',
  MANDATE_CEILING_EXCEEDED: 'Amount exceeds mandate ceiling.',
  MONTHLY_BUDGET_EXCEEDED: 'Amount would exceed the remaining monthly budget.',
  MANDATE_REVOKED: 'The mandate was revoked. It stays cryptographically valid but carries no authority.',
  MANDATE_EXPIRED: 'The mandate is past its validity window.',
  MERCHANT_SCOPE_VIOLATION: 'Merchant category falls outside the mandate scope.',
  RESERVATION_LIMIT: 'The mandate already holds its maximum number of live reservations.',
  REQUEST_NONCE_REPLAY: 'This request nonce was already spent.',
  WEBHOOK_SIGNATURE_INVALID: 'Webhook signature did not verify against the registered key.',
  WEBHOOK_REPLAY: 'Webhook event ID was already processed.',
  PSP_NO_DEFINITIVE_RESPONSE: 'The payment processor did not provide a definitive response.',
  PSP_DECLINED: 'The payment processor declined the charge.',
  DEMO_ENDPOINT_NOT_AVAILABLE: 'Clock control does not exist outside the demo build.',
};

export interface Mandate {
  id: string;
  principal: string;
  agent: string;
  status: MandateStatus;
  perTransaction: number;
  monthlyLimit: number;
  committed: number;
  reserved: number;
  uses: number;
  maxUses: number;
  category: string;
  destinations: string[];
  currency: string;
  maxLiveReservations: number;
  liveReservations: number;
  lastActivity: string;
  createdAt: string;
  expiresAt: string;
  revocation: {
    liveCheck: boolean;
    lastCheckedSeconds: number;
    revocationId: string;
    registry: string;
    epoch: number;
  };
  timeline: MandateEvent[];
}

export interface MandateEvent {
  label: string;
  at: string;
  done: boolean;
  tone?: 'allow' | 'deny' | 'neutral';
}

export interface Attempt {
  id: string;
  mandateId: string;
  agent: string;
  merchant: string;
  item: string;
  route?: string;
  amount: number;
  currency: string;
  decision: Decision;
  reason: ReasonCode;
  paymentId?: string;
  /** Set once a human has signed off on an escalated attempt. */
  approvedBy?: string;
  captured?: boolean;
  decisionHandle: string;
  termsHash: string;
  expiresIn: number;
}

export interface Payment {
  id: string;
  attemptId?: string;
  agent: string;
  merchant: string;
  amount: number;
  currency: string;
  status: PaymentStatus;
  note?: string;
}

export type LedgerStatus = 'OK' | 'HELD' | 'REJECTED';

export interface LedgerEvent {
  id: string;
  time: string;
  type: string;
  actor: string;
  txId: string;
  hash: string;
  status: LedgerStatus;
}

export interface Dispute {
  id: string;
  paymentId: string;
  merchant: string;
  amount: number;
  claim: string;
  verdict: 'UPHELD' | 'REJECTED' | 'UNDER_REVIEW';
  evidence: string[];
  openedAt: string;
}

export type JudgeOutcome = ReasonCode | 'IN_DOUBT' | 'DECLINED_COMPENSATED' | 'MANDATE_REVOKED';

export interface JudgeTest {
  id: string;
  name: string;
  description: string;
  expected: string;
  /** Tone of the expected outcome, so the grid reads before it is read. */
  tone: 'deny' | 'hold' | 'verify';
  state: 'idle' | 'running' | 'done';
  observed?: string;
  detail?: string;
}
