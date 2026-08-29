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

test('default gateway identity is stable across provider renders', () => {
  const providerSource = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(providerSource, /const DEFAULT_AVAL_GATEWAY = createMockAvalGateway\(\);/);
  assert.match(providerSource, /gateway = DEFAULT_AVAL_GATEWAY/);
  assert.equal(providerSource.includes('gateway = createMockAvalGateway()'), false);
  assert.equal(providerSource.includes('void reload();'), false);
  assert.equal(providerSource.includes('export function useAval'), false);
});
