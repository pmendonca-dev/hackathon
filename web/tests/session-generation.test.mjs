import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

import { createSessionGeneration } from '../src/state/sessionGeneration.ts';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('invalidating a session generation rejects a response started by the prior session', () => {
  const generation = createSessionGeneration();
  const sessionA = generation.current();

  generation.invalidate();
  const sessionB = generation.current();

  assert.equal(generation.isCurrent(sessionA), false);
  assert.equal(generation.isCurrent(sessionB), true);
});

test('the provider guards BFF workspace writes with the active session generation', () => {
  const provider = readFileSync(join(root, 'src/state/AvalProvider.tsx'), 'utf8');

  assert.match(provider, /useRef\(createSessionGeneration\(\)\)/);
  assert.match(provider, /sessionGeneration\.invalidate\(\)/);
  assert.match(provider, /sessionGeneration\.isCurrent\(requestGeneration\)/);
});
