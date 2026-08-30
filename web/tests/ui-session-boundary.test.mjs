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
  assert.match(provider, /const csrfToken = session\.csrfToken/);
  assert.match(provider, /apiGateway\.logout\(csrfToken\)/);
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

test('provider clears every protected projection on logout and reauthentication failures', () => {
  const provider = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(provider, /sessionRecovery\(presentation\)/);
  assert.match(provider, /const clearProtectedState = useCallback/);
  for (const clear of [
    'setSession(null)',
    'setWorkspace(null)',
    'setAudit(null)',
    'setDispute(null)',
    'setLastCommandReceipt(null)',
    "setView('human')",
  ]) {
    assert.match(provider, new RegExp(clear.replace(/[()]/g, '\\$&')));
  }
  assert.match(provider, /const csrfToken = session\.csrfToken;[\s\S]*clearProtectedState\(\);[\s\S]*apiGateway\.logout\(csrfToken\)/);
  assert.match(provider, /handleFailure\(reloadError/);
  assert.match(provider, /handleFailure\(commandError/);
});
