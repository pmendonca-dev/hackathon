import assert from 'node:assert/strict';
import test from 'node:test';

import { AuthorizationGateway } from '../src/gateways/authorizationGateway.ts';

function recordingFetch(responses) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, method: init.method ?? 'GET', headers: init.headers ?? {}, body: init.body });
    const next = responses.shift() ?? { status: 200, body: {} };
    return {
      ok: next.status < 400,
      status: next.status,
      json: async () => next.body,
      text: async () => JSON.stringify(next.body),
    };
  };
  return { fetch, calls };
}

function gatewayWith(responses, options = {}) {
  const { fetch, calls } = recordingFetch(responses);
  return {
    calls,
    gateway: new AuthorizationGateway({ baseUrl: 'http://api.test', fetch, ...options }),
  };
}

test('mandates are always listed under a principal scope', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { mandates: [] } }]);

  await gateway.listMandates('usr_marta');

  assert.equal(calls[0].url, 'http://api.test/mandates?principal_id=usr_marta');
  assert.equal(calls[0].method, 'GET');
});

test('a free-text purchase goes to the agent surface and returns the ladder', async () => {
  const trace = [{ check: 'below_ceiling', passed: false, detail: 'valor 90000 acima do teto 50000' }];
  const { gateway, calls } = gatewayWith([
    { status: 200, body: { outcome: 'rejected', reason_code: 'mandate_ceiling', evaluation_trace: trace } },
  ]);

  const run = await gateway.agentPurchase('mandate_1', 'compre a executiva');

  assert.equal(calls[0].url, 'http://api.test/agent/purchase');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), {
    mandate_id: 'mandate_1',
    instruction: 'compre a executiva',
  });
  assert.deepEqual(run.evaluation_trace, trace);
});

test('the operator token travels only on operator routes', async () => {
  const { gateway, calls } = gatewayWith(
    [{ status: 200, body: { mandates: [] } }, { status: 200, body: { mode: 'offline' } }],
    { operatorToken: 'demo-token' },
  );

  await gateway.listMandates('usr_marta');
  await gateway.setPspMode('offline');

  assert.equal('X-Aval-Operator' in calls[0].headers, false);
  assert.equal(calls[1].headers['X-Aval-Operator'], 'demo-token');
});

test('an operator command without a configured token fails before it is sent', async () => {
  const { gateway, calls } = gatewayWith([]);

  await assert.rejects(() => gateway.setPspMode('offline'), /operador/i);
  assert.equal(calls.length, 0);
});

test('a refusal surfaces the reason code the runtime returned', async () => {
  const { gateway } = gatewayWith([
    { status: 403, body: { reason_code: 'limit_change_unsigned', human_summary: 'Exige assinatura.' } },
  ]);

  await assert.rejects(
    () => gateway.changeLimit('mandate_1', { minor_units: 100, currency: 'USD', scale: 2 }, 'jws'),
    (error) => {
      assert.equal(error.reasonCode, 'limit_change_unsigned');
      assert.equal(error.message, 'Exige assinatura.');
      return true;
    },
  );
});

test('a signed revocation is posted as the token the holder produced', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { revoked: true, epoch: 1 } }]);

  await gateway.revokeMandate('mandate_1', 'eyJhbGciOiJFUzI1NiJ9.x.y');

  assert.equal(calls[0].url, 'http://api.test/mandates/mandate_1/revocation');
  assert.deepEqual(JSON.parse(calls[0].body), { token: 'eyJhbGciOiJFUzI1NiJ9.x.y' });
});

test('the merchant view is fetched by merchant id and never by mandate id', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { entries: [] } }]);

  await gateway.merchantLedger('vuelaya');

  assert.equal(calls[0].url, 'http://api.test/ledger?view=merchant&merchant_id=vuelaya');
  assert.equal(calls[0].url.includes('mandate_id'), false);
});

test('an unreachable runtime is reported as unreachable, never as a refusal', async () => {
  const gateway = new AuthorizationGateway({
    baseUrl: 'http://api.test',
    fetch: async () => {
      throw new TypeError('fetch failed');
    },
  });

  await assert.rejects(
    () => gateway.listMandates('usr_marta'),
    (error) => {
      assert.equal(error.reasonCode, 'runtime_unreachable');
      return true;
    },
  );
});
