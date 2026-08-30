/**
 * The claims a holder signs to bring a mandate into existence.
 *
 * The mandate is born signed by the same key that will be able to revoke it. Without
 * this the server would be taking the page's word that this browser speaks for this
 * person, and a dispute months later — *"I never created that mandate"* — would have
 * nothing to read. With it, position 0 of the mandate's own hash chain is the holder's
 * signature over the terms it was born with.
 *
 * The runtime checks these fields one by one against the mandate it is about to write,
 * so this shape is a contract, not a convenience: a claim that drifts from
 * `AuthorizationCore._verified_creation` produces a refusal, never a weaker mandate.
 * `web/tests/mandate-creation.test.mjs` pins it.
 */

export interface MandateCreationPayload {
  principal: { id: string; display_name: string };
  allowed_merchant_ids: string[];
  allowed_categories: string[];
  limit: { minor_units: number; currency: string; scale: number };
  ceiling?: { minor_units: number; currency: string; scale: number } | null;
  usage_limit?: { max_uses: number; window_seconds: number } | null;
  expires_at: string;
}

/**
 * A nonce for one creation.
 *
 * A revocation is irreversible, so replaying one changes nothing. A creation is
 * additive: the same signature sent twice would mint a second mandate carrying the same
 * terms and double what the agent may spend, without the holder ever signing twice.
 */
function creationNonce(): string {
  const bytes = crypto.getRandomValues(new Uint8Array(8));
  return `mcn_${Array.from(bytes, (byte) => byte.toString(16).padStart(2, '0')).join('')}`;
}

export function mandateCreationClaims(
  payload: MandateCreationPayload,
): Record<string, unknown> {
  const ceiling = payload.ceiling ?? null;
  const usageLimit = payload.usage_limit ?? null;
  return {
    purpose: 'mandate_creation',
    principal_id: payload.principal.id,
    // Sorted because the server compares sorted sets: two pages listing the same
    // merchants in a different order describe the same authority.
    allowed_merchant_ids: [...payload.allowed_merchant_ids].sort(),
    allowed_categories: [...payload.allowed_categories].sort(),
    limit_minor_units: payload.limit.minor_units,
    currency: payload.limit.currency,
    scale: payload.limit.scale,
    // Absent, not zero: a mandate with no ceiling is unbounded above the budget, and a
    // signed zero would describe one that authorizes nothing.
    ceiling_minor_units: ceiling === null ? null : ceiling.minor_units,
    max_uses: usageLimit === null ? null : usageLimit.max_uses,
    usage_window_seconds: usageLimit === null ? null : usageLimit.window_seconds,
    expires_at: payload.expires_at,
    creation_nonce: creationNonce(),
  };
}
