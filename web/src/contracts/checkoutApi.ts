import type { Money } from './avalGateway.ts';

export const CHECKOUT_API_CONTRACT_VERSION = 'aval-checkout-api@9b9c86b' as const;

export const CHECKOUT_SESSION_STATUSES = [
  'ready_for_complete',
  'requires_escalation',
  'canceled',
] as const;

export type CheckoutSessionStatus = (typeof CHECKOUT_SESSION_STATUSES)[number];

export interface CheckoutApiMoney {
  amount: number;
  currency: string;
  scale: number;
}

export interface CheckoutLineItem {
  id: string;
  quantity: number;
  amount: number;
}

export interface CreateCheckoutSessionRequest {
  id: string;
  mandate_id: string;
  merchant_id: string;
  total: CheckoutApiMoney;
  line_items: CheckoutLineItem[];
  capabilities: string[];
}

export interface CheckoutSessionProjection {
  id: string;
  merchant_id: string;
  line_items: CheckoutLineItem[];
  totals: Array<{ type: 'total'; amount: number; currency: string }>;
  status: CheckoutSessionStatus;
  continue_url?: string;
  ap2?: { merchant_authorization: string };
}

export interface CompleteCheckoutSessionRequest {
  audience: string;
  nonce: string;
  ap2?: { checkout_mandate: string };
}

export interface CheckoutApiError {
  detail: { code: string };
}

/** Maps presentation money to the stable Laptop A HTTP shape. No policy is evaluated. */
export function toCheckoutApiMoney(money: Money): CheckoutApiMoney {
  if (!Number.isInteger(money.minorUnits)) {
    throw new TypeError('Checkout API money requires integer minor units.');
  }
  if (!Number.isInteger(money.scale)) {
    throw new TypeError('Checkout API money requires an integer scale.');
  }
  if (!/^[A-Z]{3}$/.test(money.currency)) {
    throw new TypeError('Checkout API money requires an uppercase ISO currency code.');
  }
  return { amount: money.minorUnits, currency: money.currency, scale: money.scale };
}
