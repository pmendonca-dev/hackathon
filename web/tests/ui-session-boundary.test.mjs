import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('session and CSRF remain in React memory and operator UI submits intent only', () => {
  const provider = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');
  const trial = readFileSync(join(root, 'src/pages/TrialConsole.tsx'), 'utf8');
  const app = readFileSync(join(root, 'src/App.tsx'), 'utf8');
  const productionUi = `${provider}\n${trial}\n${app}`;

  assert.match(provider, /useState<UiSessionMaterial \| null>/);
  assert.match(provider, /setSession\(null\)/);
  assert.match(provider, /apiGateway\.logout\(session\.csrfToken\)/);
  assert.match(provider, /apiGateway\.revokeMandate\([\s\S]*session\.csrfToken/);
  assert.match(provider, /nextWorkspace\.role !== role/);

  assert.match(trial, /Idempotency-Key/);
  assert.match(trial, /\/ui-api\/v1\/mandates/);
  for (const forbidden of [
    'localStorage',
    'sessionStorage',
    'indexedDB',
    'caches.open',
    'signed_revocation',
    'AuthorizationProof',
    'Revogação assinada (JWS)',
  ]) {
    assert.equal(productionUi.includes(forbidden), false, `${forbidden} reached the production UI boundary`);
  }
});
