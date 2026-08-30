import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const root = join(dirname(fileURLToPath(import.meta.url)), '..');

test('live views consume the canonical runtime workspace instead of fixture projections', () => {
  const app = readFileSync(join(root, 'src/App.tsx'), 'utf8');
  const human = readFileSync(join(root, 'src/pages/LiveHumanView.tsx'), 'utf8');
  const merchant = readFileSync(join(root, 'src/pages/LiveMerchantView.tsx'), 'utf8');
  const auditor = readFileSync(join(root, 'src/pages/LiveAuditorView.tsx'), 'utf8');

  assert.match(app, /snapshot\.meta\.dataSource === 'api'/);
  assert.match(app, /<LiveHumanView data={liveSnapshot\.live}/);
  assert.match(app, /<LiveMerchantView capture={liveSnapshot\.live\.capture} receipts={liveSnapshot\.live\.receipts}/);
  assert.match(app, /<LiveAuditorView audit={liveSnapshot\.live\.audit} dispute={liveSnapshot\.live\.dispute}/);

  assert.match(human, /reason_code/);
  assert.match(auditor, /timeline/);
  assert.match(auditor, /post_commit_note/);
  for (const forbidden of [
    'principalName',
    'perTransactionLimit',
    'ceiling',
    'liveAllowance',
    'vaultToken',
    'mandateId',
    'monthlyBudget',
  ]) {
    assert.equal(merchant.includes(forbidden), false, `live merchant view references ${forbidden}`);
  }
});
