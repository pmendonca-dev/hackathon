/**
 * The console stops carrying a permanent secret.
 *
 * The operator token used to be built into the bundle through `VITE_AVAL_OPERATOR_TOKEN`,
 * which means anyone who opened devtools on the demo page walked away with the processor
 * switch, the clock and the price knob — permanently. Now the token is typed once into
 * the console, exchanged for a session that expires on its own, and the page holds only
 * that. Nothing here can move money either way: the operator lane never could.
 */

import assert from 'node:assert/strict';
import test from 'node:test';

import { AuthorizationGateway, GatewayError } from '../src/gateways/authorizationGateway.ts';

function stubFetch(handler) {
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, init });
    const { status = 200, payload = {} } = handler(url, init) ?? {};
    return {
      ok: status < 400,
      status,
      json: async () => payload,
    };
  };
  return { fetch, calls };
}

test('the gateway starts with no operator credential at all', () => {
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch: async () => {} });

  assert.equal(gateway.hasOperatorSession, false);
});

test('the typed token is exchanged for a session and never sent again', async () => {
  const { fetch, calls } = stubFetch((url) =>
    url.endsWith('/admin/operator/sessions')
      ? {
          status: 201,
          payload: {
            session_id: 'ops_1',
            session_token: 'ops_1.secret',
            expires_at: '2026-08-30T13:00:00+00:00',
          },
        }
      : { payload: { mode: 'offline' } },
  );
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch });

  await gateway.openOperatorSession('the-typed-token');
  await gateway.setPspMode('offline');

  assert.equal(gateway.hasOperatorSession, true);
  // The raw token appears exactly once: in the exchange. Every later call carries the
  // session, so a page left open does not keep re-presenting the permanent secret.
  assert.equal(calls[0].init.headers['X-Aval-Operator'], 'the-typed-token');
  assert.equal(calls[1].init.headers['X-Aval-Operator-Session'], 'ops_1.secret');
  assert.equal(calls[1].init.headers['X-Aval-Operator'], undefined);
});

test('an operator command without a session is refused before it reaches the runtime', async () => {
  const { fetch, calls } = stubFetch(() => ({ payload: {} }));
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch });

  await assert.rejects(
    () => gateway.setPspMode('offline'),
    (error) => error instanceof GatewayError && error.reasonCode === 'operator_session_missing',
  );
  assert.equal(calls.length, 0);
});

test('closing the session forgets it, so the next command asks for the token again', async () => {
  const { fetch } = stubFetch((url) =>
    url.endsWith('/admin/operator/sessions')
      ? {
          status: 201,
          payload: { session_id: 'ops_1', session_token: 'ops_1.secret', expires_at: 'x' },
        }
      : { payload: {} },
  );
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch });
  await gateway.openOperatorSession('the-typed-token');

  await gateway.closeOperatorSession();

  assert.equal(gateway.hasOperatorSession, false);
});

test('a session that the runtime says expired is dropped rather than retried', async () => {
  const { fetch } = stubFetch((url) =>
    url.endsWith('/admin/operator/sessions')
      ? {
          status: 201,
          payload: { session_id: 'ops_1', session_token: 'ops_1.secret', expires_at: 'x' },
        }
      : { status: 403, payload: { reason_code: 'operator_session_expired' } },
  );
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch });
  await gateway.openOperatorSession('the-typed-token');

  await assert.rejects(() => gateway.setPspMode('offline'));

  // The console has to ask for the token again instead of pretending it is still
  // operating with a credential the runtime has already stopped honouring.
  assert.equal(gateway.hasOperatorSession, false);
});

test('the journal is read with the session, and reads never claim to be actions', async () => {
  const { fetch, calls } = stubFetch((url) =>
    url.endsWith('/admin/operator/sessions')
      ? {
          status: 201,
          payload: { session_id: 'ops_1', session_token: 'ops_1.secret', expires_at: 'x' },
        }
      : { payload: { entries: [], chain: { intact: true, checked: 0, broken_at: null } } },
  );
  const gateway = new AuthorizationGateway({ baseUrl: 'http://runtime', fetch });
  await gateway.openOperatorSession('the-typed-token');

  const journal = await gateway.operatorJournal();

  assert.equal(journal.chain.intact, true);
  assert.equal(calls[1].init.method ?? 'GET', 'GET');
});
