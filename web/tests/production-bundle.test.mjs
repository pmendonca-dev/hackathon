import assert from 'node:assert/strict';
import { execFileSync } from 'node:child_process';
import {
  mkdtempSync,
  readFileSync,
  readdirSync,
  rmSync,
  statSync,
} from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, relative } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

function walk(path) {
  return readdirSync(path).flatMap((name) => {
    const entry = join(path, name);
    return statSync(entry).isDirectory() ? walk(entry) : [entry];
  });
}

test('the emitted production artifact excludes every development mock value', () => {
  const outputDirectory = mkdtempSync(join(tmpdir(), 'aval-web-production-'));

  try {
    execFileSync(
      process.execPath,
      [
        join(root, 'node_modules/vite/bin/vite.js'),
        'build',
        '--outDir',
        outputDirectory,
        '--emptyOutDir',
      ],
      {
        cwd: root,
        env: {
          ...process.env,
          NODE_ENV: 'production',
          VITE_AVAL_USE_MOCK: 'true',
        },
        stdio: 'pipe',
      },
    );

    const searchableFiles = walk(outputDirectory)
      .filter((path) => /\.(?:css|html|js|json)$/.test(path));
    const prohibited = [
      { label: 'mockAvalGateway module', pattern: /mockAvalGateway/ },
      { label: 'synthetic vault token', pattern: /\bvt_[A-Za-z0-9._~-]+\b/ },
      { label: 'synthetic authorization proof', pattern: /\bproof_[A-Za-z0-9._~-]+\b/i },
    ];
    const violations = searchableFiles.flatMap((path) => {
      const artifact = readFileSync(path, 'utf8');
      return prohibited
        .filter(({ pattern }) => pattern.test(artifact) || pattern.test(relative(outputDirectory, path)))
        .map(({ label }) => `${relative(outputDirectory, path)}: ${label}`);
    });

    assert.deepEqual(violations, []);
  } finally {
    rmSync(outputDirectory, { recursive: true, force: true });
  }
});
