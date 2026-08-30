import assert from 'node:assert/strict';
import test from 'node:test';

import { UiBffGateway } from '../src/gateways/uiBffGateway.ts';

test('login uses the same-origin BFF and returns the in-memory session material', async () => {
  const requests = [];
  const gateway = new UiBffGateway({
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json({
        role: 'operator',
        csrf_token: 'csrf-kept-only-in-react-memory',
        expires_at: '2026-08-30T12:00:00Z',
      });
    },
  });

  const session = await gateway.login({ role: 'operator', credential: 'one-time-local-login' });

  assert.deepEqual(session, {
    role: 'operator',
    csrfToken: 'csrf-kept-only-in-react-memory',
    expiresAt: '2026-08-30T12:00:00Z',
  });
  assert.equal(requests.length, 1);
  assert.equal(requests[0].input, '/ui-api/v1/session/login');
  assert.equal(requests[0].init.method, 'POST');
  assert.equal(requests[0].init.credentials, 'same-origin');
  assert.deepEqual(JSON.parse(requests[0].init.body), {
    role: 'operator',
    credential: 'one-time-local-login',
  });
  assert.equal(requests[0].init.headers.Authorization, undefined);
  assert.equal(requests[0].init.headers.Signature, undefined);
});

test('reads and mutations stay inside the BFF and mutations receive React-memory CSRF', async () => {
  const requests = [];
  const responses = new Map([
    ['/ui-api/v1/workspace', { role: 'operator', mandates: [{ mandate_id: 'mandate_01', status: 'active' }] }],
    ['/ui-api/v1/mandates/mandate_01/audit', { mandate_id: 'mandate_01', timeline: [] }],
    ['/ui-api/v1/mandates/mandate_01/dispute', { mandate_id: 'mandate_01', status: 'reconstructed', reason_code: 'evidence_complete', human_summary: 'Evidence complete.', post_commit_note: null, timeline: [] }],
    ['/ui-api/v1/mandates/mandate_01/revocations', { mandate_id: 'mandate_01', status: 'revoked' }],
  ]);
  const gateway = new UiBffGateway({
    fetch: async (input, init) => {
      requests.push({ input, init });
      if (input === '/ui-api/v1/session/logout') return new Response(null, { status: 204 });
      return Response.json(responses.get(input));
    },
  });

  await gateway.loadWorkspace();
  await gateway.loadAudit('mandate_01');
  await gateway.loadDispute('mandate_01');
  await gateway.revokeMandate('mandate_01', 'revoke-once', 'csrf-from-react-state');
  await gateway.logout('csrf-from-react-state');

  assert.deepEqual(requests.map(({ input }) => input), [
    '/ui-api/v1/workspace',
    '/ui-api/v1/mandates/mandate_01/audit',
    '/ui-api/v1/mandates/mandate_01/dispute',
    '/ui-api/v1/mandates/mandate_01/revocations',
    '/ui-api/v1/session/logout',
  ]);
  for (const request of requests) {
    assert.equal(request.init.credentials, 'same-origin');
    assert.match(request.input, /^\/ui-api\/v1\//);
    assert.equal(JSON.stringify(request).includes('Signature'), false);
    assert.equal(JSON.stringify(request).includes('Content-Digest'), false);
    assert.equal(JSON.stringify(request).includes('AuthorizationProof'), false);
  }

  const revocation = requests[3];
  assert.equal(revocation.init.method, 'POST');
  assert.equal(revocation.init.headers['X-AVAL-CSRF'], 'csrf-from-react-state');
  assert.equal(revocation.init.headers['Idempotency-Key'], 'revoke-once');
  assert.equal(revocation.init.body, '{}');

  const logout = requests[4];
  assert.equal(logout.init.method, 'POST');
  assert.equal(logout.init.headers['X-AVAL-CSRF'], 'csrf-from-react-state');
});
