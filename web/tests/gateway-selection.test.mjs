import assert from 'node:assert/strict';
import test from 'node:test';

import { HttpAvalGateway } from '../src/gateways/httpAvalGateway.ts';
import { createAvalGateway } from '../src/gateways/createAvalGateway.ts';

test('HTTP is the default gateway and mock requires an explicit development flag', async () => {
  const defaultGateway = createAvalGateway({});
  assert.equal(defaultGateway instanceof HttpAvalGateway, true);

  const falseGateway = createAvalGateway({ VITE_AVAL_USE_MOCK: 'false' });
  assert.equal(falseGateway instanceof HttpAvalGateway, true);

  const productionGateway = createAvalGateway({ DEV: false, VITE_AVAL_USE_MOCK: 'true' });
  assert.equal(productionGateway instanceof HttpAvalGateway, true);

  const mockGateway = createAvalGateway({ DEV: true, VITE_AVAL_USE_MOCK: 'true' });
  const snapshot = await mockGateway.loadWorkspace();
  assert.equal(snapshot.meta.dataSource, 'mock');
  assert.equal(snapshot.meta.networkUsed, false);
});
