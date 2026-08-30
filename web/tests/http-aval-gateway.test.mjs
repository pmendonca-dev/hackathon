import assert from 'node:assert/strict';
import test from 'node:test';

import { AvalHttpError, HttpAvalGateway } from '../src/gateways/httpAvalGateway.ts';

test('create checkout uses the documented public HTTP endpoint', async () => {
  const requests = [];
  const projection = {
    id: 'chi_live_1',
    merchant_id: 'merchant_01',
    line_items: [{ id: 'coffee', quantity: 1, amount: 500 }],
    totals: [{ type: 'total', amount: 500, currency: 'BRL' }],
    status: 'ready_for_complete',
    ap2: { merchant_authorization: 'protected..signature' },
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example/api/',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return new Response(JSON.stringify(projection), {
        status: 201,
        headers: { 'content-type': 'application/json' },
      });
    },
  });
  const request = {
    id: 'chi_live_1',
    mandate_id: 'mandate_01',
    merchant_id: 'merchant_01',
    total: { amount: 500, currency: 'BRL', scale: 2 },
    line_items: [{ id: 'coffee', quantity: 1, amount: 500 }],
    capabilities: [
      'dev.ucp.shopping.checkout',
      'dev.ucp.common.payment.ap2_mandate',
    ],
  };

  assert.deepEqual(await gateway.createCheckout(request), projection);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].input, 'https://aval.example/api/checkout-sessions');
  assert.equal(requests[0].init.method, 'POST');
  assert.equal(requests[0].init.credentials, 'include');
  assert.equal(new Headers(requests[0].init.headers).get('content-type'), 'application/json');
  assert.deepEqual(JSON.parse(requests[0].init.body), request);
});

test('complete checkout sends AP2 evidence with an idempotency key', async () => {
  const requests = [];
  const projection = {
    id: 'chi_live_1',
    merchant_id: 'merchant_01',
    line_items: [{ id: 'coffee', quantity: 1, amount: 500 }],
    totals: [{ type: 'total', amount: 500, currency: 'BRL' }],
    status: 'ready_for_complete',
    ap2: { merchant_authorization: 'protected..signature' },
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(projection);
    },
  });
  const request = {
    audience: 'merchant_01',
    nonce: 'merchant-challenge-value',
    ap2: { checkout_mandate: 'issuer-jwt~kb-jwt' },
  };

  assert.deepEqual(
    await gateway.completeCheckout('chi_live_1', request, 'complete-live-1'),
    projection,
  );
  assert.equal(
    requests[0].input,
    'https://aval.example/checkout-sessions/chi_live_1/complete',
  );
  assert.equal(requests[0].init.method, 'POST');
  const headers = new Headers(requests[0].init.headers);
  assert.equal(headers.get('idempotency-key'), 'complete-live-1');
  assert.deepEqual(JSON.parse(requests[0].init.body), request);
});

test('protocol failures preserve the stable HTTP status and error code', async () => {
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async () => Response.json(
      { detail: { code: 'mandate_expired' } },
      { status: 422 },
    ),
  });

  await assert.rejects(
    gateway.completeCheckout(
      'chi_live_1',
      { audience: 'merchant_01', nonce: 'challenge' },
      'complete-live-1',
    ),
    (error) => {
      assert.equal(error instanceof AvalHttpError, true);
      assert.equal(error.status, 422);
      assert.equal(error.code, 'mandate_expired');
      return true;
    },
  );
});

test('delegate payment calls the authenticated ACP runtime endpoint', async () => {
  const requests = [];
  const delegated = {
    token: 'vt_local_opaque_value',
    allowance: {
      reason: 'one_time',
      max_amount: 500,
      currency: 'brl',
      checkout_session_id: 'chi_01',
      merchant_id: 'merchant_01',
      expires_at: '2026-08-30T12:00:00Z',
    },
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(delegated, { status: 201 });
    },
  });
  const request = {
    mandate_id: 'mandate_01',
    checkout_session_id: 'chi_01',
    merchant_id: 'merchant_01',
    payment_method: { card_number: '4242424242424242' },
  };

  assert.deepEqual(await gateway.delegatePayment(request, 'delegate-live-1'), delegated);
  assert.equal(requests[0].input, 'https://aval.example/agentic_commerce/delegate_payment');
  assert.equal(requests[0].init.credentials, 'include');
  assert.equal(new Headers(requests[0].init.headers).get('idempotency-key'), 'delegate-live-1');
  assert.deepEqual(JSON.parse(requests[0].init.body), request);
});

test('capture payment posts the opaque token and AP2 evidence idempotently', async () => {
  const requests = [];
  const capture = {
    capture_id: 'cap_01',
    reservation_id: 'rsv_01',
    status: 'settled',
    settlement_reference: 'psp_mock_abc123',
    receipt_url: '/payment-captures/cap_01/receipts',
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(capture, { status: 201 });
    },
  });
  const request = {
    mandate_id: 'mandate_01',
    checkout_session_id: 'chi_01',
    merchant_id: 'merchant_01',
    token: 'vt_local_opaque_value',
    amount: { amount: 500, currency: 'BRL', scale: 2 },
    ap2: {
      checkout_mandate: 'checkout-issuer~checkout-kb',
      payment_mandate: 'payment-issuer~payment-kb',
    },
  };

  assert.deepEqual(await gateway.createPaymentCapture(request, 'capture-live-1'), capture);
  assert.equal(requests[0].input, 'https://aval.example/payment-captures');
  assert.equal(new Headers(requests[0].init.headers).get('idempotency-key'), 'capture-live-1');
  assert.deepEqual(JSON.parse(requests[0].init.body), request);
});

test('capture state is read from its canonical read-only endpoint', async () => {
  const requests = [];
  const capture = {
    capture_id: 'cap_01',
    reservation_id: 'rsv_01',
    status: 'settled',
    settlement_reference: 'psp_mock_abc123',
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(capture);
    },
  });

  assert.deepEqual(await gateway.getPaymentCapture('cap_01'), capture);
  assert.equal(requests[0].input, 'https://aval.example/payment-captures/cap_01');
  assert.equal(requests[0].init.method, 'GET');
  assert.equal(requests[0].init.credentials, 'include');
  assert.equal(new Headers(requests[0].init.headers).has('idempotency-key'), false);
});

test('settled receipts are read from the capture receipt endpoint', async () => {
  const requests = [];
  const receipts = {
    capture_id: 'cap_01',
    checkout_receipt: 'checkout.receipt.jwt',
    payment_receipt: 'payment.receipt.jwt',
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(receipts);
    },
  });

  assert.deepEqual(await gateway.getPaymentReceipts('cap_01'), receipts);
  assert.equal(
    requests[0].input,
    'https://aval.example/payment-captures/cap_01/receipts',
  );
  assert.equal(requests[0].init.method, 'GET');
  assert.equal(requests[0].init.credentials, 'include');
});

test('audit timeline is read through the authenticated mandate endpoint', async () => {
  const requests = [];
  const audit = {
    status: 'reconstructed',
    reason_code: 'evidence_complete',
    human_summary: 'The durable evidence chain is complete.',
    post_commit_note: null,
    timeline: [{
      id: 'evt_01',
      mandate_id: 'mandate_01',
      event_type: 'settlement.confirmed',
      reason_code: 'psp_approved',
      human_summary: 'Settlement was confirmed.',
      actor: 'mock-card-psp',
      occurred_at: '2026-08-30T12:00:00Z',
      evidence_hash: 'sha256:audit',
      revocation_epoch: 4,
    }],
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(audit);
    },
  });

  assert.deepEqual(await gateway.getAuditTimeline('mandate_01'), audit);
  assert.equal(requests[0].input, 'https://aval.example/audit/mandates/mandate_01');
  assert.equal(requests[0].init.credentials, 'include');
});

test('dispute reconstruction uses the canonical mandate dispute endpoint', async () => {
  const requests = [];
  const dispute = {
    status: 'reconstructed',
    reason_code: 'revoked_after_commit',
    human_summary: 'The capture remains settled.',
    post_commit_note: 'The revocation blocks future authority only.',
    timeline: [],
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(dispute);
    },
  });

  assert.deepEqual(await gateway.getDispute('mandate_01'), dispute);
  assert.equal(
    requests[0].input,
    'https://aval.example/audit/mandates/mandate_01/dispute',
  );
  assert.equal(requests[0].init.credentials, 'include');
});

test('signed revocation is submitted to the authority endpoint without local mutation', async () => {
  const requests = [];
  const accepted = { mandate_id: 'mandate_01', status: 'revoked' };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json(accepted, { status: 202 });
    },
  });

  assert.deepEqual(
    await gateway.revokeMandate('mandate_01', 'signed.revocation.jws', 'revoke-live-1'),
    accepted,
  );
  assert.equal(
    requests[0].input,
    'https://aval.example/mandates/mandate_01/revocations',
  );
  assert.equal(new Headers(requests[0].init.headers).get('idempotency-key'), 'revoke-live-1');
  assert.deepEqual(
    JSON.parse(requests[0].init.body),
    { signed_revocation: 'signed.revocation.jws' },
  );
  assert.equal(JSON.stringify(accepted).includes('signed.revocation.jws'), false);
});
