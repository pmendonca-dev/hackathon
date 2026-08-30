import assert from 'node:assert/strict';
import test from 'node:test';

import {
  generateHolderKeyPair,
  signCompactJws,
  base64UrlEncode,
} from '../src/wallet/holderKey.ts';

test('the generated private key can never be read back out of the browser', async () => {
  const wallet = await generateHolderKeyPair('usr_marta_k1');

  // This is the whole security argument for signing in the browser. The key is
  // persisted and used, but no code path — ours, an extension's, or an injected
  // script's — can serialise it and send it anywhere.
  await assert.rejects(
    () => crypto.subtle.exportKey('jwk', wallet.privateKey),
    /extractable|not extractable|InvalidAccessError/i,
  );
});

test('the public JWK is a P-256 key carrying the kid the mandate will register', async () => {
  const wallet = await generateHolderKeyPair('usr_marta_k1');

  assert.equal(wallet.publicJwk.kty, 'EC');
  assert.equal(wallet.publicJwk.crv, 'P-256');
  assert.equal(wallet.publicJwk.kid, 'usr_marta_k1');
  assert.equal(typeof wallet.publicJwk.x, 'string');
  assert.equal(typeof wallet.publicJwk.y, 'string');
  // A public JWK that leaked the private scalar would defeat the point.
  assert.equal('d' in wallet.publicJwk, false);
});

test('a signed revocation verifies against the published public key', async () => {
  const wallet = await generateHolderKeyPair('usr_marta_k1');
  const claims = { mandate_id: 'mandate_1', scope: 'mandate', reason: 'teste', epoch: 1 };

  const token = await signCompactJws(claims, wallet);

  const [header, payload, signature] = token.split('.');
  assert.equal(JSON.parse(Buffer.from(header, 'base64url').toString()).alg, 'ES256');
  assert.equal(JSON.parse(Buffer.from(header, 'base64url').toString()).kid, 'usr_marta_k1');
  assert.deepEqual(JSON.parse(Buffer.from(payload, 'base64url').toString()), claims);

  const verifier = await crypto.subtle.importKey(
    'jwk',
    wallet.publicJwk,
    { name: 'ECDSA', namedCurve: 'P-256' },
    false,
    ['verify'],
  );
  const verified = await crypto.subtle.verify(
    { name: 'ECDSA', hash: 'SHA-256' },
    verifier,
    Buffer.from(signature, 'base64url'),
    new TextEncoder().encode(`${header}.${payload}`),
  );
  assert.equal(verified, true);
});

test('the signature is raw r||s, the 64 bytes ES256 requires', async () => {
  const wallet = await generateHolderKeyPair('k1');

  const token = await signCompactJws({ a: 1 }, wallet);

  // A DER-wrapped signature is the classic ES256 interop bug: it verifies in the
  // library that produced it and nowhere else. The Python verifier expects r||s.
  assert.equal(Buffer.from(token.split('.')[2], 'base64url').length, 64);
});

test('base64url output carries no padding and no url-unsafe characters', () => {
  const encoded = base64UrlEncode(new TextEncoder().encode('a?b>c~d'.repeat(5)));

  assert.equal(/^[A-Za-z0-9_-]+$/.test(encoded), true);
});
