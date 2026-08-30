/**
 * The claims the browser signs to bring a mandate into existence.
 *
 * The server checks these field by field against the mandate it is about to write, so
 * a shape that drifts here is a mandate the runtime refuses — not a page that silently
 * creates something weaker than what the person filled in. These tests pin the shape
 * against the Python verifier's expectations.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { mandateCreationClaims } from '../src/wallet/mandateCreation.ts';

const payload = {
  principal: { id: 'usr_marta', display_name: 'Marta Silva' },
  allowed_merchant_ids: ['vuelaya', 'andesair'],
  allowed_categories: ['travel'],
  limit: { minor_units: 20000, currency: 'USD', scale: 2 },
  ceiling: { minor_units: 50000, currency: 'USD', scale: 2 },
  expires_at: '2026-09-30T23:59:59.000Z',
  usage_limit: { max_uses: 3, window_seconds: 2592000 },
};

test('the claims name every term that decides what may be spent', () => {
  const claims = mandateCreationClaims(payload);

  assert.equal(claims.purpose, 'mandate_creation');
  assert.equal(claims.principal_id, 'usr_marta');
  assert.deepEqual(claims.allowed_merchant_ids, ['andesair', 'vuelaya']);
  assert.deepEqual(claims.allowed_categories, ['travel']);
  assert.equal(claims.limit_minor_units, 20000);
  assert.equal(claims.currency, 'USD');
  assert.equal(claims.scale, 2);
  assert.equal(claims.ceiling_minor_units, 50000);
  assert.equal(claims.max_uses, 3);
  assert.equal(claims.usage_window_seconds, 2592000);
  assert.equal(claims.expires_at, '2026-09-30T23:59:59.000Z');
});

test('an absent ceiling and frequency are signed as absent, never as zero', () => {
  const claims = mandateCreationClaims({
    ...payload,
    ceiling: undefined,
    usage_limit: undefined,
  });

  // A mandate with no ceiling is not a mandate with a ceiling of nothing: signing zero
  // would describe a mandate that authorizes no purchase at all.
  assert.equal(claims.ceiling_minor_units, null);
  assert.equal(claims.max_uses, null);
  assert.equal(claims.usage_window_seconds, null);
});

test('each creation carries its own nonce, because a replayed one mints a second mandate', () => {
  const first = mandateCreationClaims(payload).creation_nonce;
  const second = mandateCreationClaims(payload).creation_nonce;

  assert.notEqual(first, second);
  assert.match(first, /^mcn_[0-9a-f]{16}$/);
});
