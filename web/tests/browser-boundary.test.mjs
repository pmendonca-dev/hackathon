import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

/**
 * Structural invariants for the browser lane.
 *
 * These are the properties that are cheap to break by accident and expensive to notice
 * later: a policy rule creeping into the page, a private key gaining an export path, a
 * fixture quietly standing in for a runtime that never answered.
 */

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function sourceFiles() {
  function walk(path) {
    return readdirSync(path).flatMap((name) => {
      const entry = join(path, name);
      return statSync(entry).isDirectory() ? walk(entry) : [entry];
    });
  }
  return walk(join(root, 'src')).filter((path) => /\.(ts|tsx)$/.test(path));
}

function allSource() {
  return sourceFiles().map((path) => readFileSync(path, 'utf8')).join('\n');
}

test('browser source contains no client-side policy engine', () => {
  assert.equal(existsSync(join(root, 'src/domain/policy.ts')), false);
  assert.equal(existsSync(join(root, 'src/domain/store.tsx')), false);

  const source = allSource();
  for (const forbidden of [
    'calculateAllowance',
    'authorizePayment',
    'capturePayment',
    'revocationReducer',
  ]) {
    assert.equal(source.includes(forbidden), false, `browser implements ${forbidden}`);
  }
});

test('the holder private key has no export path anywhere in the browser source', () => {
  const source = allSource();

  // Exporting the private half is the single change that would turn a locally-held
  // key into a key that can be exfiltrated. `exportKey` is legitimate for the public
  // JWK, so the assertion is on the private handle never reaching it.
  assert.equal(source.includes("exportKey('jwk', pair.privateKey)"), false);
  assert.equal(source.includes('exportKey("jwk", pair.privateKey)'), false);

  const holderKey = readFileSync(join(root, 'src/wallet/holderKey.ts'), 'utf8');
  // Generated non-extractable. The `false` argument is the whole guarantee.
  assert.match(holderKey, /generateKey\(ES256, false, \['sign', 'verify'\]\)/);
});

test('the wallet is never uploaded, logged, or placed in a request body', () => {
  const source = allSource();

  assert.equal(/body:\s*JSON\.stringify\([^)]*privateKey/.test(source), false);
  assert.equal(source.includes('console.log(wallet'), false);
  // An allowlist rather than a pattern: both surviving bindings hold the opaque
  // CryptoKey handle, and any new one has to be looked at, because a `privateKey:`
  // bound to anything serialisable would mean the key had been exported.
  const declarations = new Set(source.match(/privateKey:\s*[^;,\n]+/g) ?? []);
  assert.deepEqual([...declarations].sort(), [
    'privateKey: CryptoKey',
    'privateKey: pair.privateKey',
  ]);
});

test('provider builds one gateway outside render and never falls back to fixtures', () => {
  const providerSource = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(providerSource, /const DEFAULT_GATEWAY = new AuthorizationGateway\(/);
  assert.match(providerSource, /gateway = DEFAULT_GATEWAY/);
  // No fixture module survives, so a page that cannot reach the runtime has nothing
  // to render in its place — which is the intended outcome, not a gap.
  assert.equal(existsSync(join(root, 'src/fixtures')), false);
  assert.equal(providerSource.includes('mockAvalGateway'), false);
});

test('an unreachable runtime is surfaced as unreachable rather than as a refusal', () => {
  const gatewaySource = readFileSync(join(root, 'src/gateways/authorizationGateway.ts'), 'utf8');
  const appSource = readFileSync(join(root, 'src/App.tsx'), 'utf8');

  assert.match(gatewaySource, /runtime_unreachable/);
  assert.match(appSource, /Runtime indisponível/);
  assert.equal(appSource.includes('DADOS DE DEMONSTRAÇÃO'), false);
});

test('the operator token is confined to routes that cannot move money', () => {
  const gatewaySource = readFileSync(join(root, 'src/gateways/authorizationGateway.ts'), 'utf8');

  // Every holder-signed command must carry a JWS argument and must not request the
  // operator header. If one of these ever flips to `operator: true`, an operator
  // credential would have become able to change what a mandate may spend.
  for (const method of ['changeLimit', 'revokeMandate', 'revokeEverything', 'decideEscalation']) {
    const body = gatewaySource.slice(gatewaySource.indexOf(`${method}(`));
    const request = body.slice(0, body.indexOf('}\n\n'));
    assert.equal(request.includes('operator: true'), false, `${method} asks for operator authority`);
  }

  for (const method of ['setPspMode', 'reconcile', 'advanceClock', 'tamperLedger']) {
    const body = gatewaySource.slice(gatewaySource.indexOf(`  ${method}(`));
    const request = body.slice(0, body.indexOf('}\n\n') + 1 || body.length);
    assert.equal(request.includes('operator: true'), true, `${method} runs unauthenticated`);
  }
});

test('the evaluation ladder shows unreached rungs instead of hiding them', () => {
  const ladder = readFileSync(join(root, 'src/components/EvaluationLadder.tsx'), 'utf8');

  // A refusal that stopped early must look like an early answer, not a shorter rule
  // set. Dropping the unwalked rungs would erase the ordering the trace exists to show.
  assert.match(ladder, /nunca consultado/);
  assert.match(ladder, /autoridade · abaixo: dinheiro/);
});
