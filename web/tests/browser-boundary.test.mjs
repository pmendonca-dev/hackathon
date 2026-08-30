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

/**
 * Read with line endings normalised.
 *
 * These assertions slice source on `}\n\n` to find where a method ends. On a Windows
 * checkout (`core.autocrlf=true`) the file arrives with CRLF, that marker is never
 * found, and the slice runs to the end of the file — which made the holder-authority
 * assertion fail and, worse, made the operator-authority assertion pass for the wrong
 * reason. A structural test must not depend on how the repository was checked out.
 */
function read(path) {
  return readFileSync(path, 'utf8').replace(/\r\n/g, '\n');
}

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
  return sourceFiles().map(read).join('\n');
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

  const holderKey = read(join(root, 'src/wallet/holderKey.ts'));
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
  const providerSource = read(join(root, 'src/state/AvalProvider.tsx'));

  assert.match(providerSource, /const DEFAULT_GATEWAY = new AuthorizationGateway\(/);
  assert.match(providerSource, /gateway = DEFAULT_GATEWAY/);
  // No fixture module survives, so a page that cannot reach the runtime has nothing
  // to render in its place — which is the intended outcome, not a gap.
  assert.equal(existsSync(join(root, 'src/fixtures')), false);
  assert.equal(providerSource.includes('mockAvalGateway'), false);
});

test('an unreachable runtime is surfaced as unreachable rather than as a refusal', () => {
  const gatewaySource = read(join(root, 'src/gateways/authorizationGateway.ts'));
  const appSource = read(join(root, 'src/App.tsx'));

  assert.match(gatewaySource, /runtime_unreachable/);
  assert.match(appSource, /Runtime indisponível/);
  assert.equal(appSource.includes('DADOS DE DEMONSTRAÇÃO'), false);
});

test('the operator token is confined to routes that cannot move money', () => {
  const gatewaySource = read(join(root, 'src/gateways/authorizationGateway.ts'));

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
  const ladder = read(join(root, 'src/components/EvaluationLadder.tsx'));

  // A refusal that stopped early must look like an early answer, not a shorter rule
  // set. Dropping the unwalked rungs would erase the ordering the trace exists to show.
  assert.match(ladder, /nunca consultado/);
  assert.match(ladder, /autoridade · abaixo: dinheiro/);
});

test('a standing order is reachable from the holder page, not only over HTTP', () => {
  // The agent that keeps working after you stop typing is the one part of the system
  // where the buyer is not a person pressing pay — which is the premise of the case.
  // Shipping it as endpoints nobody can reach from the demo hides the whole argument.
  const holder = read(join(root, 'src/pages/HolderView.tsx'));
  const provider = read(join(root, 'src/state/AvalProvider.tsx'));

  assert.match(provider, /gateway\.registerWatch\(/);
  assert.match(provider, /gateway\.listWatches\(/);
  assert.match(provider, /gateway\.tickWatches\(/);
  assert.match(holder, /watches/);
});

test('the standing order is offered, never opened on the buyer behalf', () => {
  // "Nothing matches yet" must not silently become a live spending order. The system
  // already refuses to guess an ambiguous instruction; guessing a standing one would
  // be the same mistake with a longer fuse.
  const provider = read(join(root, 'src/state/AvalProvider.tsx'));

  const runAgent = provider.slice(provider.indexOf('async runAgent('));
  const body = runAgent.slice(0, runAgent.indexOf('},\n\n'));
  assert.equal(
    body.includes('registerWatch'),
    false,
    'a purchase that found nothing opens a standing order by itself',
  );
});

test('the mandate form dates itself from the runtime clock, not from this laptop', () => {
  // A judge may move the demo clock forward at any moment. A form carrying a literal
  // date would then create mandates that are already expired, and every creation after
  // that is a 422 the judge did not cause and cannot explain.
  const holder = read(join(root, 'src/pages/HolderView.tsx'));

  assert.equal(holder.includes("'2026-09-30T23:59:59Z'"), false);
  assert.match(holder, /serverNow|expiryDefault/);
});

test('watching costs no authority the typed instruction did not already have', () => {
  const gatewaySource = read(join(root, 'src/gateways/authorizationGateway.ts'));

  for (const method of ['registerWatch', 'tickWatches', 'listWatches']) {
    const body = gatewaySource.slice(gatewaySource.indexOf(`  ${method}(`));
    const request = body.slice(0, body.indexOf('}\n\n'));
    assert.equal(request.includes('operator: true'), false, `${method} asks for operator authority`);
  }
});

test('the judge can end the waiting from the console, on the operator side', () => {
  // A standing order nobody can trigger is a claim, not a demonstration. The control
  // that ends the waiting belongs with the processor switch: it moves the catalogue,
  // which authorizes nothing — the woken watch still faces the same mandate.
  const console_ = read(join(root, 'src/pages/TrialByFireConsole.tsx'));
  const provider = read(join(root, 'src/state/AvalProvider.tsx'));

  assert.match(provider, /gateway\.repriceOffer\(/);
  assert.match(console_, /repriceOffer/);
  // The two columns are the page's argument. Slice the holder one — between its own
  // heading and the operator heading that follows it — and assert the control is not
  // rendered there. Slicing from the top of the file would catch the destructuring,
  // which says nothing about where the button ended up.
  const holderColumn = console_.slice(
    console_.indexOf('Provado pela chave do titular'),
    console_.indexOf('Provado pelo token de operador'),
  );
  assert.equal(holderColumn.includes('repriceOffer'), false);
});
