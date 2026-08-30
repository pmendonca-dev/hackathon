import assert from 'node:assert/strict';
import test from 'node:test';

import {
  CHECKOUT_API_CONTRACT_VERSION,
  CHECKOUT_SESSION_STATUSES,
  toCheckoutApiMoney,
} from '../src/contracts/checkoutApi.ts';
import { createMockAvalGateway } from '../src/fixtures/mockAvalGateway.ts';

test('fixture boundary identifies mock data over the integrated Laptop A contract', async () => {
  const gateway = createMockAvalGateway();
  const snapshot = await gateway.loadWorkspace();

  assert.equal(snapshot.meta.dataSource, 'mock');
  assert.equal(snapshot.meta.contractStatus, 'integrated');
  assert.equal(snapshot.meta.contractVersion, CHECKOUT_API_CONTRACT_VERSION);
  assert.match(snapshot.meta.fixtureId, /^mock_/);
  assert.equal(snapshot.meta.networkUsed, false);
});

test('checkout transport uses Laptop A money and status shapes without floats', () => {
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

test('all monetary values use integer minor units and explicit scale', async () => {
  const snapshot = await createMockAvalGateway().loadWorkspace();
  const monies = [
    snapshot.human.mandate.perTransactionLimit,
    snapshot.human.mandate.ceiling,
    snapshot.human.mandate.liveAllowance,
    ...snapshot.human.receipts.map((receipt) => receipt.amount),
    snapshot.merchant.receipt.amount,
    snapshot.auditor.dispute.amount,
  ];

  for (const money of monies) {
    assert.equal(Number.isInteger(money.minorUnits), true);
    assert.equal(Number.isInteger(money.scale), true);
    assert.match(money.currency, /^[A-Z]{3}$/);
  }
});

test('development fixture projections contain no payment or authorization secrets', async () => {
  const snapshot = await createMockAvalGateway().loadWorkspace();
  const payload = JSON.stringify(snapshot).toLowerCase();

  for (const forbidden of [
    'pan',
    'card_number',
    'principalid',
    'monthlybudget',
    'vaulttoken',
    'paymenttoken',
    'authorizationproof',
  ]) {
    assert.equal(payload.includes(forbidden), false, `merchant payload leaked ${forbidden}`);
  }
  assert.equal(/\bvt_[a-z0-9._~-]+\b/.test(payload), false);
  assert.equal(/\bproof_[a-z0-9._~-]+\b/.test(payload), false);
});

test('trial command boundary returns a fixture receipt without changing canonical state', async () => {
  const gateway = createMockAvalGateway();
  const before = await gateway.loadWorkspace();
  const receipt = await gateway.submitTrialCommand({
    kind: 'revoke-mandate',
    targetId: before.human.mandate.id,
    requestedValue: 'revoked',
  });
  const after = await gateway.loadWorkspace();

  assert.equal(receipt.dataSource, 'mock');
  assert.equal(receipt.outcome, 'fixture-only');
  assert.equal(receipt.canonicalStateChanged, false);
  assert.deepEqual(after, before);
});
