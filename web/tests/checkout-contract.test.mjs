import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHECKOUT_API_CONTRACT_VERSION,
  CHECKOUT_SESSION_STATUSES,
  toCheckoutApiMoney,
} from '../src/contracts/checkoutApi.ts';

/**
 * The protocol lane's checkout types. The browser demo drives the authorization lane,
 * but these shapes still describe the UCP contract, so the money invariant is kept
 * where it was: integers and an explicit scale, never a float.
 */

test('checkout transport uses the published money and status shapes without floats', () => {
  assert.deepEqual(
    toCheckoutApiMoney({ minorUnits: 18490, currency: 'BRL', scale: 2 }),
    { amount: 18490, currency: 'BRL', scale: 2 },
  );
  assert.deepEqual(CHECKOUT_SESSION_STATUSES, [
    'ready_for_complete',
    'requires_escalation',
    'canceled',
  ]);
  assert.throws(
    () => toCheckoutApiMoney({ minorUnits: 184.9, currency: 'BRL', scale: 2 }),
    /integer minor units/,
  );
});

test('the contract version is pinned rather than inferred at runtime', () => {
  assert.equal(typeof CHECKOUT_API_CONTRACT_VERSION, 'string');
  assert.notEqual(CHECKOUT_API_CONTRACT_VERSION.length, 0);
});
