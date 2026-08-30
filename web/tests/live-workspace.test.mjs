import assert from 'node:assert/strict';
import test from 'node:test';

import { HttpAvalGateway } from '../src/gateways/httpAvalGateway.ts';

test('live workspace composes only canonical runtime read endpoints', async () => {
  const requested = [];
  const capture = {
    capture_id: 'cap_01',
    reservation_id: 'rsv_01',
    status: 'settled',
    settlement_reference: 'psp_mock_abc123',
  };
  const receipts = {
    capture_id: 'cap_01',
    checkout_receipt: 'checkout.receipt.jwt',
    payment_receipt: 'payment.receipt.jwt',
  };
  const audit = {
    status: 'reconstructed',
    reason_code: 'evidence_complete',
    human_summary: 'The durable evidence chain is complete.',
    post_commit_note: null,
    timeline: [],
  };
  const dispute = {
    ...audit,
    reason_code: 'revoked_after_commit',
    post_commit_note: 'The revocation blocks future authority only.',
  };
  const responses = new Map([
    ['/payment-captures/cap_01', capture],
    ['/payment-captures/cap_01/receipts', receipts],
    ['/audit/mandates/mandate_01', audit],
    ['/audit/mandates/mandate_01/dispute', dispute],
  ]);
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    mandateId: 'mandate_01',
    captureId: 'cap_01',
    fetch: async (input) => {
      const path = new URL(input).pathname;
      requested.push(path);
      return Response.json(responses.get(path));
    },
  });

  const workspace = await gateway.loadWorkspace();

  assert.equal(workspace.meta.dataSource, 'api');
  assert.equal(workspace.meta.networkUsed, true);
  assert.equal(workspace.live.mandateId, 'mandate_01');
  assert.deepEqual(workspace.live.capture, capture);
  assert.deepEqual(workspace.live.receipts, receipts);
  assert.deepEqual(workspace.live.audit, audit);
  assert.deepEqual(workspace.live.dispute, dispute);
  assert.deepEqual(requested.sort(), [...responses.keys()].sort());
  assert.equal(JSON.stringify(workspace).includes('card_number'), false);
  assert.equal(JSON.stringify(workspace).includes('monthlybudget'), false);
});

test('trial revocation has a real authenticated audited boundary and unsupported commands fail', async () => {
  const requests = [];
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    mandateId: 'mandate_01',
    createIdempotencyKey: () => 'trial-revoke-1',
    fetch: async (input, init) => {
      requests.push({ input, init });
      return Response.json({ mandate_id: 'mandate_01', status: 'revoked' }, { status: 202 });
    },
  });

  const receipt = await gateway.submitTrialCommand({
    kind: 'revoke-mandate',
    targetId: 'mandate_01',
    requestedValue: 'signed.revocation.jws',
  });

  assert.equal(receipt.dataSource, 'api');
  assert.equal(receipt.outcome, 'accepted');
  assert.equal(receipt.canonicalStateChanged, true);
  assert.equal(receipt.requestId, 'trial-revoke-1');
  assert.equal(JSON.stringify(receipt).includes('signed.revocation.jws'), false);
  assert.equal(new Headers(requests[0].init.headers).get('idempotency-key'), 'trial-revoke-1');
  await assert.rejects(
    gateway.submitTrialCommand({
      kind: 'lower-limit',
      targetId: 'mandate_01',
      requestedValue: '500',
    }),
    /não está publicado/i,
  );
  assert.equal(requests.length, 1);
});

test('workspace keeps canonical capture and audit when receipts are not available yet', async () => {
  const capture = {
    capture_id: 'cap_pending',
    reservation_id: 'rsv_pending',
    status: 'pending_reconciliation',
    settlement_reference: 'psp_pending',
  };
  const verdict = {
    status: 'under_review',
    reason_code: 'settlement_pending',
    human_summary: 'Settlement reconciliation is still pending.',
    post_commit_note: null,
    timeline: [],
  };
  const gateway = new HttpAvalGateway({
    baseUrl: 'https://aval.example',
    mandateId: 'mandate_01',
    captureId: 'cap_pending',
    fetch: async (input) => {
      const path = new URL(input).pathname;
      if (path.endsWith('/receipts')) {
        return Response.json(
          { detail: { code: 'receipts_not_available' } },
          { status: 409 },
        );
      }
      if (path === '/payment-captures/cap_pending') return Response.json(capture);
      return Response.json(verdict);
    },
  });

  const workspace = await gateway.loadWorkspace();
  assert.deepEqual(workspace.live.capture, capture);
  assert.equal(workspace.live.receipts, null);
  assert.deepEqual(workspace.live.audit, verdict);
});
