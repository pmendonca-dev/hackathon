/**
 * The operator credential must not survive into a production build.
 *
 * `VITE_*` values are compiled into the JavaScript every visitor downloads. The operator
 * token switches off the processor, moves the demo clock, reconciles and — with
 * `AVAL_DEMO_TAMPER` on — corrupts the audit trail. A bundle carrying one hands the
 * operator role to anyone who opens the page, which is the separation the trial-by-fire
 * console exists to demonstrate.
 *
 * The build is run *with* the variable set on purpose: a test that only builds without
 * it proves nothing, because the leak it is looking for only happens when a value exists
 * to leak. This caught a real one — `const environment = import.meta.env` inlines the
 * whole env object, so the token shipped even though the only code reading it sat behind
 * a `DEV` branch that had been eliminated.
 */
import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, readdirSync, readFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const WEB_ROOT = fileURLToPath(new URL('..', import.meta.url));
const CANARY = 'operator-token-canary-must-not-ship';
// Vite's own entry, run by the Node already running this test, instead of `npx`. The
// bare name resolves no extensions on Windows (ENOENT), and `npx.cmd` is refused by
// `execFileSync` without a shell since Node's CVE-2024-27980 fix (EINVAL). Neither is
// worth a `shell: true`: a test that cannot run is a test that proves nothing, and this
// one guards the token that switches off the processor.
const VITE = fileURLToPath(new URL('../node_modules/vite/bin/vite.js', import.meta.url));

test('a production build never carries VITE_AVAL_OPERATOR_TOKEN', () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), 'aval-bundle-'));
  try {
    execFileSync(process.execPath, [VITE, 'build', '--outDir', outputDirectory, '--emptyOutDir'], {
      cwd: WEB_ROOT,
      env: { ...process.env, VITE_AVAL_OPERATOR_TOKEN: CANARY },
      stdio: 'pipe',
    });

    const leaked = filesUnder(outputDirectory).filter((file) =>
      readFileSync(file, 'utf8').includes(CANARY),
    );
    assert.deepEqual(
      leaked,
      [],
      `the operator token reached the shipped bundle in: ${leaked.join(', ')}`,
    );
  } finally {
    rmSync(outputDirectory, { recursive: true, force: true });
  }
});

function filesUnder(directory) {
  return readdirSync(directory, { withFileTypes: true }).flatMap((entry) => {
    const path = join(directory, entry.name);
    return entry.isDirectory() ? filesUnder(path) : [path];
  });
}
