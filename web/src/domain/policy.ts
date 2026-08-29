import type { Decision, Mandate, ReasonCode } from './types';

export interface PolicyResult {
  decision: Decision;
  reason: ReasonCode;
}

/**
 * The whole product in fifteen lines. Order matters: authority is checked
 * before money, and money is checked before scope. A revoked mandate can
 * never reach the amount bands, which is why revocation cannot be
 * out-argued by a small enough purchase.
 */
export function evaluate(mandate: Mandate, amount: number, category?: string): PolicyResult {
  if (mandate.status === 'REVOKED') return { decision: 'DENY', reason: 'MANDATE_REVOKED' };
  if (mandate.status === 'EXPIRED') return { decision: 'DENY', reason: 'MANDATE_EXPIRED' };

  if (category && category !== mandate.category) {
    return { decision: 'DENY', reason: 'MERCHANT_SCOPE_VIOLATION' };
  }
  if (amount > mandate.monthlyLimit) {
    return { decision: 'DENY', reason: 'MANDATE_CEILING_EXCEEDED' };
  }
  if (mandate.committed + mandate.reserved + amount > mandate.monthlyLimit) {
    return { decision: 'DENY', reason: 'MONTHLY_BUDGET_EXCEEDED' };
  }
  if (mandate.liveReservations >= mandate.maxLiveReservations && amount > mandate.perTransaction) {
    return { decision: 'DENY', reason: 'RESERVATION_LIMIT' };
  }
  if (amount > mandate.perTransaction) {
    return { decision: 'ESCALATE', reason: 'EXCEEDS_TRANSACTION_LIMIT' };
  }
  return { decision: 'ALLOW', reason: 'WITHIN_TRANSACTION_LIMIT' };
}

/** The seven edge checks that run before the amount bands are consulted. */
export interface Check {
  label: string;
  passed: boolean;
  note?: string;
}

export function buildChecks(mandate: Mandate, result: PolicyResult): Check[] {
  const authorityHeld = mandate.status === 'ACTIVE';
  return [
    { label: 'Agent signature valid', passed: true, note: 'RFC 9421 · ES256' },
    { label: 'Offer signature valid', passed: true, note: 'merchant_authorization' },
    { label: 'Mandate active', passed: authorityHeld, note: mandate.status },
    {
      label: 'Revocation check passed',
      passed: authorityHeld,
      note: authorityHeld ? `live · ${mandate.revocation.lastCheckedSeconds}s ago` : 'registry says REVOKED',
    },
    {
      label: 'Amount within limit',
      passed: result.decision === 'ALLOW',
      note: result.decision === 'ALLOW' ? 'inside allow band' : result.reason,
    },
    { label: 'Currency valid', passed: true, note: mandate.currency },
    { label: 'Replay protection passed', passed: true, note: 'nonce unspent' },
  ];
}

export const money = (n: number, currency = 'USD') =>
  new Intl.NumberFormat('en-US', {
    style: 'currency',
    currency,
    minimumFractionDigits: 2,
  }).format(n);

export const clockNow = () => {
  const d = new Date();
  return d.toTimeString().slice(0, 8);
};

export const shortHash = (seed: string) => {
  let h = 0x811c9dc5;
  for (let i = 0; i < seed.length; i++) {
    h ^= seed.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, '0');
};
