import assert from 'node:assert/strict';
import { readFileSync, readdirSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { safeDisplayText } from '../src/utils/safePresentation.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function walk(path) {
  return readdirSync(path).flatMap((name) => {
    const entry = join(path, name);
    return statSync(entry).isDirectory() ? walk(entry) : [entry];
  });
}

test('untrusted runtime text is redacted before it reaches a role view', () => {
  const unsafe = [
    'PAN 4111 1111 1111 1111',
    'token vt_secret-value',
    'JWS eyJhbGciOiJFZERTQSJ9.eyJzdWIiOiJwcml2YXRlIn0.signature',
    'signed.revocation.jws',
    'proof checkout-issuer~checkout-kb',
    'proof proof_private-evidence',
  ];

  for (const value of unsafe) {
    const visible = safeDisplayText(value);
    assert.equal(visible.includes('4111'), false);
    assert.equal(visible.includes('vt_secret'), false);
    assert.equal(visible.includes('eyJhbGci'), false);
    assert.equal(visible.includes('proof_private'), false);
    assert.match(visible, /dado protegido/);
  }
});

test('role pages do not bind sensitive credential or proof fields to the DOM', () => {
  const roleSources = [
    'src/pages/HumanView.tsx',
    'src/pages/MerchantView.tsx',
    'src/pages/AuditorView.tsx',
    'src/pages/LiveHumanView.tsx',
    'src/pages/LiveMerchantView.tsx',
    'src/pages/LiveAuditorView.tsx',
  ].map((path) => readFileSync(join(root, path), 'utf8')).join('\n');

  for (const forbiddenBinding of [
    '.vaultToken',
    '.paymentToken',
    '.authorizationProofRef',
    'receipts.checkout_receipt',
    'receipts.payment_receipt',
  ]) {
    assert.equal(roleSources.includes(forbiddenBinding), false, `${forbiddenBinding} reaches a role view`);
  }
  assert.match(roleSources, /safeDisplayText/);
});

test('the trial console masks and clears signed administrative evidence', () => {
  const trialSource = readFileSync(join(root, 'src/pages/TrialConsole.tsx'), 'utf8');

  assert.match(trialSource, /type="password"/);
  assert.match(trialSource, /autoComplete="off"/);
  assert.match(trialSource, /setRequestedValue\(''\)/);
  assert.equal(trialSource.includes('console.'), false);
});

test('browser code never writes runtime payloads to the developer console', () => {
  const source = walk(join(root, 'src'))
    .filter((path) => /\.(ts|tsx)$/.test(path))
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n');

  assert.equal(source.includes('console.'), false);
});
