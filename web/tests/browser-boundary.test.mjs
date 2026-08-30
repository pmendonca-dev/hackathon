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

test('the authority atlas and every attack scenario remain visible on the holder BFF page', () => {
  const holder = readFileSync(join(root, 'src/pages/HumanView.tsx'), 'utf8');
  const attacks = readFileSync(join(root, 'src/components/AttackScenarios.tsx'), 'utf8');

  assert.match(holder, /<AuthorityAtlas/);
  assert.match(holder, /<AttackScenarios/);
  for (const scenario of ['within-mandate', 'category-scope', 'merchant-scope', 'ceiling', 'revoked']) {
    assert.match(attacks, new RegExp(`id: '${scenario}'`));
  }
});

test('adapted authority components consume safe BFF projections only', () => {
  const atlas = readFileSync(join(root, 'src/components/AuthorityAtlas.tsx'), 'utf8');
  const attacks = readFileSync(join(root, 'src/components/AttackScenarios.tsx'), 'utf8');

  for (const source of [atlas, attacks]) {
    assert.equal(source.includes('authorizationGateway'), false);
    assert.equal(source.includes('authorization_proof'), false);
    assert.equal(source.includes('settlement_reference'), false);
    assert.equal(source.includes("'/agent/"), false);
    assert.equal(source.includes("'/admin/"), false);
  }
  assert.match(atlas, /UiMandateProjection/);
  assert.match(atlas, /UiAuditProjection/);
});

test('unpublished standing-order and purchase commands are visible but never simulated', () => {
  const holder = readFileSync(join(root, 'src/pages/HumanView.tsx'), 'utf8');
  const attacks = readFileSync(join(root, 'src/components/AttackScenarios.tsx'), 'utf8');
  const provider = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(holder, /Vigília autônoma/);
  assert.match(holder, /BFF ainda não publica/);
  assert.match(attacks, /Indisponível no BFF/);
  assert.equal(attacks.includes('onRun'), false);
  for (const directCommand of ['registerWatch', 'listWatches', 'tickWatches', 'repriceOffer', 'runAgent']) {
    assert.equal(provider.includes(directCommand), false, `provider exposes ${directCommand}`);
  }
});
