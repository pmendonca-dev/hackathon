import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('provider stores safe structured failures instead of raw exception messages', () => {
  const source = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(source, /AvalErrorPresentation/);
  assert.match(source, /error instanceof AvalHttpError/);
  assert.match(source, /error\.presentation/);
  assert.match(source, /presentUnavailable/);
  assert.equal(source.includes('error instanceof Error ? error.message'), false);
});

test('workspace renders one operational failure rail with explicit safe actions', () => {
  const app = readFileSync(join(root, 'src/App.tsx'), 'utf8');
  const failure = readFileSync(join(root, 'src/components/RuntimeFailure.tsx'), 'utf8');

  assert.match(app, /<RuntimeFailure/);
  assert.match(failure, /check-status/);
  assert.match(failure, /Consultar status e recibo/);
  assert.match(failure, /check-availability/);
  assert.match(failure, /Verificar disponibilidade/);
  assert.equal(failure.includes('Tentar pagamento novamente'), false);
  assert.match(failure, /error\.status === 409/);
  assert.match(failure, /error\.status === 503/);
});
