import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');
const read = (path) => readFileSync(join(root, path), 'utf8');

test('login and operator mutation controls expose explicit accessible names and busy state', () => {
  const login = read('src/pages/LoginView.tsx');
  const trial = read('src/pages/TrialConsole.tsx');

  assert.match(login, /htmlFor="login-role"/);
  assert.match(login, /id="login-role"/);
  assert.match(login, /htmlFor="login-credential"/);
  assert.match(login, /id="login-credential"/);
  assert.match(login, /aria-describedby="login-credential-help"/);
  assert.match(login, /aria-busy={loading}/);
  assert.match(login, /roleSelectRef\.current\?\.focus\(\)/);

  assert.match(trial, /htmlFor="trial-target-id"/);
  assert.match(trial, /id="trial-target-id"/);
  assert.match(trial, /htmlFor="trial-idempotency-key"/);
  assert.match(trial, /id="trial-idempotency-key"/);
  assert.match(trial, /aria-busy={submitting}/);
  assert.match(trial, /role="status"/);
  assert.match(trial, /aria-live="polite"/);
});

test('errors receive focus and status changes use intentional live regions', () => {
  const failure = read('src/components/RuntimeFailure.tsx');
  const app = read('src/App.tsx');

  assert.match(failure, /useEffect/);
  assert.match(failure, /focus\(\)/);
  assert.match(failure, /tabIndex={-1}/);
  assert.match(failure, /role="alert"/);
  assert.match(failure, /aria-live="assertive"/);
  assert.match(failure, /aria-atomic="true"/);
  assert.match(failure, /aria-labelledby=/);
  assert.match(failure, /aria-describedby=/);
  assert.match(app, /role="status"/);
  assert.match(app, /aria-live="polite"/);
});

test('keyboard navigation has a content target, visible focus, and clear disabled states', () => {
  const shell = read('src/components/Shell.tsx');
  const styles = read('src/index.css');
  const browserUi = [
    shell,
    read('src/pages/LoginView.tsx'),
    read('src/pages/TrialConsole.tsx'),
  ].join('\n');

  assert.match(shell, /href="#main-content"/);
  assert.match(shell, /tabIndex={-1}/);
  assert.match(shell, /mainContentRef\.current\?\.focus\(\)/);
  assert.match(styles, /:focus-visible/);
  assert.match(styles, /box-shadow:/);
  assert.match(styles, /:disabled/);
  assert.match(styles, /@media \(forced-colors: active\)/);
  assert.match(styles, /@media \(prefers-reduced-motion: reduce\)/);
  assert.equal(browserUi.includes('tabIndex={1}'), false);
});
