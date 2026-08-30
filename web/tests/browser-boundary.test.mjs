import assert from 'node:assert/strict';
import { existsSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function walk(path) {
  return readdirSync(path).flatMap((name) => {
    const entry = join(path, name);
    return statSync(entry).isDirectory() ? walk(entry) : [entry];
  });
}

test('browser source contains no client-side policy engine', () => {
  assert.equal(existsSync(join(root, 'src/domain/policy.ts')), false);
  assert.equal(existsSync(join(root, 'src/domain/store.tsx')), false);

  const source = walk(join(root, 'src'))
    .filter((path) => /\.(ts|tsx)$/.test(path))
    .map((path) => readFileSync(path, 'utf8'))
    .join('\n');

  for (const forbidden of ['calculateAllowance', 'authorizePayment', 'capturePayment', 'revocationReducer']) {
    assert.equal(source.includes(forbidden), false, `browser implements ${forbidden}`);
  }
});

test('browser source excludes the legacy agent-signing and persistent-wallet lane', () => {
  for (const legacyPath of [
    'src/components/EvaluationLadder.tsx',
    'src/components/LiveFooter.tsx',
    'src/gateways/authorizationGateway.ts',
    'src/pages/AuditorTrailView.tsx',
    'src/pages/HolderView.tsx',
    'src/pages/MerchantDeskView.tsx',
    'src/pages/TrialByFireConsole.tsx',
    'src/wallet/holderKey.ts',
    'src/wallet/walletStore.ts',
    'tests/authorization-gateway.test.mjs',
    'tests/holder-wallet.test.mjs',
    'tests/live-browser-journey.mjs',
  ]) {
    assert.equal(existsSync(join(root, legacyPath)), false, `legacy browser lane remains at ${legacyPath}`);
  }
});

test('provider creates the environment-selected gateway once outside renders', () => {
  const providerSource = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(providerSource, /const DEFAULT_AVAL_GATEWAY = createAvalGateway\(import\.meta\.env\);/);
  assert.match(providerSource, /gateway = DEFAULT_AVAL_GATEWAY/);
  assert.equal(providerSource.includes('gateway = createMockAvalGateway()'), false);
  assert.equal(providerSource.includes("from '../fixtures/mockAvalGateway.ts'"), false);
  assert.match(providerSource, /error instanceof UiBffHttpError/);
  assert.match(providerSource, /error\.presentation/);
  assert.equal(providerSource.includes('error instanceof Error ? error.message'), false);
  assert.match(providerSource, /apiGateway\.revokeMandate/);
  assert.match(providerSource, /command\.idempotencyKey/);
  assert.match(providerSource, /session\.csrfToken/);
  assert.match(providerSource, /await loadBffWorkspace\(session\.role\)/);
  assert.equal(providerSource.includes('export function useAval'), false);
});

test('application chrome makes mock data unmistakable and does not label live data as mock', () => {
  const shellSource = readFileSync(join(root, 'src/components/Shell.tsx'), 'utf8');
  const appSource = readFileSync(join(root, 'src/App.tsx'), 'utf8');

  assert.match(shellSource, /dataSource === 'mock'/);
  assert.match(shellSource, /BFF REAL/);
  assert.match(appSource, /DADOS DE DEMONSTRAÇÃO \/ MOCK/);
  assert.match(appSource, /não representam estado vivo/i);
  assert.equal(shellSource.includes('<Badge tone="escalate">MOCK</Badge>'), false);
  assert.equal(shellSource.includes('>SEM REDE</span>'), false);
  assert.equal(appSource.includes('Carregando snapshot mock'), false);
});

test('trial console enables only the published live revocation command', () => {
  const trialSource = readFileSync(join(root, 'src/pages/TrialConsole.tsx'), 'utf8');

  assert.match(trialSource, /dataSource === 'api' && kind === 'revoke-mandate'/);
  assert.match(trialSource, /Idempotency-Key/);
  assert.match(trialSource, /POST \/ui-api\/v1\/mandates/);
  assert.match(trialSource, /disabled={!commandAvailable/);
  assert.match(trialSource, /API administrativa não publicada/);
  assert.equal(trialSource.includes('signed_revocation'), false);
  assert.equal(trialSource.includes('Revogação assinada'), false);
  assert.equal(trialSource.includes('Contrato futuro'), false);
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
