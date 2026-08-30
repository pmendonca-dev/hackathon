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

test('provider creates the environment-selected gateway once outside renders', () => {
  const providerSource = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(providerSource, /const DEFAULT_AVAL_GATEWAY = createAvalGateway\(import\.meta\.env\);/);
  assert.match(providerSource, /gateway = DEFAULT_AVAL_GATEWAY/);
  assert.equal(providerSource.includes('gateway = createMockAvalGateway()'), false);
  assert.equal(providerSource.includes("from '../fixtures/mockAvalGateway.ts'"), false);
  assert.match(providerSource, /error instanceof Error \? error\.message/);
  assert.match(providerSource, /const receipt = await gateway\.submitTrialCommand\(command\)/);
  assert.match(providerSource, /receipt\.dataSource === 'api'/);
  assert.match(providerSource, /setSnapshot\(await gateway\.loadWorkspace\(\)\)/);
  assert.equal(providerSource.includes('void reload();'), false);
  assert.equal(providerSource.includes('export function useAval'), false);
});

test('application chrome makes mock data unmistakable and does not label live data as mock', () => {
  const shellSource = readFileSync(join(root, 'src/components/Shell.tsx'), 'utf8');
  const appSource = readFileSync(join(root, 'src/App.tsx'), 'utf8');

  assert.match(shellSource, /snapshot\?\.meta\.dataSource === 'mock'/);
  assert.match(shellSource, /API REAL/);
  assert.match(appSource, /DADOS DE DEMONSTRAÇÃO \/ MOCK/);
  assert.match(appSource, /não representam estado vivo/i);
  assert.equal(shellSource.includes('<Badge tone="escalate">MOCK</Badge>'), false);
  assert.equal(shellSource.includes('>SEM REDE</span>'), false);
  assert.equal(appSource.includes('Carregando snapshot mock'), false);
});

test('trial console enables only the published live revocation command', () => {
  const trialSource = readFileSync(join(root, 'src/pages/TrialConsole.tsx'), 'utf8');

  assert.match(trialSource, /dataSource === 'api' && kind === 'revoke-mandate'/);
  assert.match(trialSource, /Revogação assinada \(JWS\)/);
  assert.match(trialSource, /disabled={!commandAvailable/);
  assert.match(trialSource, /API administrativa não publicada/);
  assert.equal(trialSource.includes('Contrato futuro'), false);
});
