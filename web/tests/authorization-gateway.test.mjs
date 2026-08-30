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

test('a mandate listing carries the principal scope and the holder signature', async () => {
  // The principal id is a guessable name, so the key is what decides what comes back.
  // A listing that travelled without the signature would be the hole this closes.
  //
  // The signature travels in a header and must never be in the URL: query strings are
  // written to access logs, kept in browser history and handed to third parties in
  // `Referer`, and this JWS is portable proof of authority over the mandate.
  const { gateway, calls } = gatewayWith([{ status: 200, body: { mandates: [] } }]);

  await gateway.listMandates('usr_marta', 'eyJhbGciOiJFUzI1NiJ9.e30.sig');

  assert.equal(calls[0].url, 'http://api.test/mandates?principal_id=usr_marta');
  assert.equal(calls[0].headers['X-Aval-Authorization'], 'eyJhbGciOiJFUzI1NiJ9.e30.sig');
  assert.ok(!calls[0].url.includes('eyJhbGciOiJFUzI1NiJ9'));
  assert.equal(calls[0].method, 'GET');
});

test('polling pending approvals carries the same signature', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { escalations: [] } }]);

  await gateway.listEscalations('usr_marta', 'eyJhbGciOiJFUzI1NiJ9.e30.sig');

  assert.equal(calls[0].url, 'http://api.test/escalations?principal_id=usr_marta');
  assert.equal(calls[0].headers['X-Aval-Authorization'], 'eyJhbGciOiJFUzI1NiJ9.e30.sig');
  assert.ok(!calls[0].url.includes('eyJhbGciOiJFUzI1NiJ9'));
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

test('the operator credential travels only on operator routes', async () => {
  const { gateway, calls } = gatewayWith([
    { status: 201, body: { session_id: 'ops_1', session_token: 'ops_1.secret', expires_at: 'x' } },
    { status: 200, body: { mandates: [] } },
    { status: 200, body: { mode: 'offline' } },
  ]);
  await gateway.openOperatorSession('demo-token');

  await gateway.listMandates('usr_marta');
  await gateway.setPspMode('offline');

  // The holder's own listing must never carry an operator credential: the two lanes
  // answer different questions, and a page that mixed them would be claiming that
  // running the instance is a way of seeing someone's mandates.
  assert.equal('X-Aval-Operator-Session' in calls[1].headers, false);
  assert.equal(calls[2].headers['X-Aval-Operator-Session'], 'ops_1.secret');
  // And the permanent token appears once, in the exchange, and never again.
  assert.equal(calls[0].headers['X-Aval-Operator'], 'demo-token');
  assert.equal('X-Aval-Operator' in calls[2].headers, false);
});

test('an operator command without a configured token fails before it is sent', async () => {
  const { gateway, calls } = gatewayWith([]);

  await assert.rejects(() => gateway.setPspMode('offline'), /operator/i);
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

test('the live footer is read from the runtime, never assembled in the page', async () => {
  // The decision counts are aggregates of the hash-chained trail. A page that added
  // them up itself could disagree with the auditor tab standing next to it.
  const { gateway, calls } = gatewayWith([
    {
      status: 200,
      body: {
        decisions: { authorized: 3, awaiting_human: 1, rejected: 2 },
        spend_outside_mandate: { minor_units: 0, currency: 'USD', scale: 2 },
      },
    },
  ]);

  const body = await gateway.metrics();

  assert.equal(calls[0].url, 'http://api.test/metrics');
  assert.equal(body.decisions.authorized, 3);
  assert.equal(body.spend_outside_mandate.minor_units, 0);
});

test('the footer carries no operator token, because it decides nothing', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: {} }], {
    operatorToken: 'demo-token',
  });

  await gateway.metrics();

  assert.equal(calls[0].headers['X-Aval-Operator'], undefined);
});

test('a standing order carries the same free text a person would have typed', async () => {
  // The watch is the instruction kept for later, not a new kind of authority: it fires
  // by calling the very same purchase path, so a revoked mandate refuses it identically.
  const { gateway, calls } = gatewayWith([
    { status: 201, body: { watch_id: 'wch_1', status: 'OPEN' } },
  ]);

  await gateway.registerWatch('mandate_1', 'buy a nonstop flight to Córdoba under $100');

  assert.equal(calls[0].url, 'http://api.test/agent/watches');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), {
    mandate_id: 'mandate_1',
    instruction: 'buy a nonstop flight to Córdoba under $100',
  });
});

test('standing orders are read scoped to one mandate', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { watches: [] } }]);

  await gateway.listWatches('mandate_1');

  assert.equal(calls[0].url, 'http://api.test/agent/watches?mandate_id=mandate_1');
  assert.equal(calls[0].method, 'GET');
});

test('a tick names the mandate whose watches are being tried', async () => {
  const { gateway, calls } = gatewayWith([{ status: 200, body: { fired: [] } }]);

  await gateway.tickWatches('mandate_1');

  assert.equal(calls[0].url, 'http://api.test/agent/watches/tick');
  assert.equal(calls[0].method, 'POST');
  assert.deepEqual(JSON.parse(calls[0].body), { mandate_id: 'mandate_1' });
});

test('the page reads validity from the runtime clock, never from the browser', async () => {
  // A judge who advances the demo clock a month would otherwise get an already-expired
  // mandate from a form that dated itself off the laptop's wall clock.
  const { gateway, calls } = gatewayWith([
    { status: 200, body: { status: 'ok', now: '2026-09-29T12:00:00+00:00' } },
  ]);

  const now = await gateway.serverNow();

  assert.equal(calls[0].url, 'http://api.test/health');
  assert.equal(now, '2026-09-29T12:00:00+00:00');
});

test('dropping a catalogue price is an operator action, never a holder one', async () => {
  // The standing order needs something that ends the waiting. Repricing sells nothing
  // and authorizes nothing — it moves the catalogue, which is why it sits with the
  // processor switch and not with the holder key.
  const { gateway, calls } = gatewayWith([
    { status: 201, body: { session_id: 'ops_1', session_token: 'ops_1.secret', expires_at: 'x' } },
    { status: 200, body: { sku: 'FL-SAO-COR-0918', minor_units: 9000 } },
  ]);
  await gateway.openOperatorSession('demo-token');

  await gateway.repriceOffer('FL-SAO-COR-0918', 9000);

  assert.equal(calls[1].url, 'http://api.test/admin/catalog/price');
  assert.equal(calls[1].method, 'POST');
  assert.equal(calls[1].headers['X-Aval-Operator-Session'], 'ops_1.secret');
  assert.deepEqual(JSON.parse(calls[1].body), { sku: 'FL-SAO-COR-0918', minor_units: 9000 });
});
