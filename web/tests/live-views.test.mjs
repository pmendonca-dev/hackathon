import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('BFF views consume only their role-scoped projections', () => {
  const app = readFileSync(join(root, 'src/App.tsx'), 'utf8');
  const human = readFileSync(join(root, 'src/pages/HumanView.tsx'), 'utf8');
  const merchant = readFileSync(join(root, 'src/pages/MerchantView.tsx'), 'utf8');
  const auditor = readFileSync(join(root, 'src/pages/AuditorView.tsx'), 'utf8');

  assert.match(app, /session\.role === 'holder'/);
  assert.match(app, /session\.role === 'merchant'/);
  assert.match(app, /session\.role === 'auditor'/);
  assert.match(app, /session\.role === 'operator'/);
  assert.match(app, /<HumanView workspace={workspace} audit={audit} dispute={dispute}/);
  assert.match(app, /<MerchantView workspace={workspace}/);
  assert.match(app, /<AuditorView workspace={workspace} audit={audit} dispute={dispute}/);

  assert.match(human, /available_amount/);
  assert.match(auditor, /timeline/);
  assert.match(auditor, /post_commit_note/);
  for (const forbidden of [
    'principalName',
    'perTransactionLimit',
    'ceiling',
    'liveAllowance',
    'vaultToken',
    'available_amount',
    'currency',
    'audit',
    'dispute',
  ]) {
    assert.equal(merchant.includes(forbidden), false, `merchant view references ${forbidden}`);
  }
});
