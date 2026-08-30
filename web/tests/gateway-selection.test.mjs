import assert from 'node:assert/strict';
import test from 'node:test';

import { createAvalGateway } from '../src/gateways/createAvalGateway.ts';
import { UiBffGateway } from '../src/gateways/uiBffGateway.ts';

test('the same-origin BFF is default and mock requires an explicit development flag', async () => {
  const defaultGateway = createAvalGateway({});
  assert.equal(defaultGateway instanceof UiBffGateway, true);

  const falseGateway = createAvalGateway({ VITE_AVAL_USE_MOCK: 'false' });
  assert.equal(falseGateway instanceof UiBffGateway, true);

  const productionGateway = createAvalGateway({ DEV: false, VITE_AVAL_USE_MOCK: 'true' });
  assert.equal(productionGateway instanceof UiBffGateway, true);

  const mockGateway = createAvalGateway({ DEV: true, VITE_AVAL_USE_MOCK: 'true' });
  const snapshot = await mockGateway.loadWorkspace();
  assert.equal(snapshot.meta.dataSource, 'mock');
  assert.equal(snapshot.meta.networkUsed, false);
});
