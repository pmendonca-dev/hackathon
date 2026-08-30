export const PAYMENT_RUNTIME_API_CONTRACT_VERSION = 'aval-payment-runtime-api@3191d3e' as const;

export interface DelegatePaymentRequest {
  mandate_id: string;
  checkout_session_id: string;
  merchant_id: string;
  payment_method: { card_number: string };
}

export interface DelegatePaymentResponse {
  token: `vt_${string}`;
  allowance: {
    reason: 'one_time';
    max_amount: number;
    currency: string;
    checkout_session_id: string;
    merchant_id: string;
    expires_at: string;
  };
}

export interface CreatePaymentCaptureRequest {
  checkout_session_id: string;
  token: `vt_${string}`;
  audience: string;
  nonce: string;
  ap2: {
    checkout_mandate: string;
  };
}

export interface PaymentCaptureProjection {
  capture_id: string;
  reservation_id: string;
  status: 'settled' | 'pending_reconciliation';
  settlement_reference: string;
  receipt_url?: string;
}

export interface PaymentReceiptsProjection {
  capture_id: string;
  checkout_receipt: string;
  payment_receipt: string;
}

export interface AuditTimelineEvent {
  id: string;
  mandate_id: string;
  event_type: string;
  reason_code: string;
  human_summary: string;
  actor: string;
  occurred_at: string;
  evidence_hash: string;
  revocation_epoch: number;
}

export interface AuditVerdictProjection {
  status: string;
  reason_code: string;
  human_summary: string;
  post_commit_note: string | null;
  timeline: AuditTimelineEvent[];
}

export interface CreateRevocationRequest {
  signed_revocation: string;
}

export interface RevocationProjection {
  mandate_id: string;
  status: 'revoked';
}
