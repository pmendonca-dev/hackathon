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

test('the emitted production artifact contains no mock, agent endpoint, or signing material', () => {
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

    const searchableFiles = walk(outputDirectory);
    const prohibited = [
      { label: 'mockAvalGateway module', pattern: /mockAvalGateway/ },
      { label: 'development mock workspace', pattern: /DevelopmentMockWorkspace|DADOS DE DEMONSTRAÇÃO \/ MOCK|mock_request_/i },
      { label: 'vault-token prefix', pattern: /vt_/ },
      { label: 'synthetic authorization proof', pattern: /\bproof_[A-Za-z0-9._~-]+\b/i },
      { label: 'private key material', pattern: /BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY|privateKey/i },
      { label: 'signed revocation field', pattern: /signed_revocation/i },
      { label: 'browser signing implementation', pattern: /subtle\.sign|createSign\(|Signature-Input|Content-Digest|\bJWS\b/i },
      { label: 'agent endpoint', pattern: /\/agentic_commerce\/|\/payment-captures|\/checkout-sessions|\/audit\/mandates/i },
      { label: 'persistent browser storage', pattern: /localStorage|sessionStorage|indexedDB|caches\.open/i },
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
