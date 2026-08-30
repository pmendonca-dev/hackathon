import assert from 'node:assert/strict';
import test from 'node:test';

import {
  parseAvalErrorEnvelope,
  presentAvalError,
} from '../src/errors/avalError.ts';

test('the runtime error parser accepts only the stable code envelope', () => {
  assert.equal(
    parseAvalErrorEnvelope({ detail: { code: 'mandate_revoked' } }),
    'mandate_revoked',
  );
  for (const payload of [
    null,
    { detail: 'mandate_revoked' },
    { detail: { code: '' } },
    { detail: { code: 'vt_secret-value' } },
    { detail: { code: 'vt_secret_value' } },
    { detail: { code: 'proof_private_evidence' } },
    { detail: [{ code: 'request_invalid', input: '4242424242424242' }] },
  ]) {
    assert.equal(parseAvalErrorEnvelope(payload), 'request_invalid');
  }
});

test('every published runtime error has clear Portuguese guidance', () => {
  const expectedCopy = {
    mandate_revoked: /mandato foi revogado/i,
    mandate_expired: /mandato expirou/i,
    merchant_out_of_scope: /merchant.*fora do escopo/i,
    policy_denied: /política viva recusou/i,
    revocation_unavailable: /bloqueio seguro/i,
    idempotency_in_flight: /operação original.*andamento/i,
    idempotency_key_reused: /chave de idempotência.*outra solicitação/i,
    transaction_already_captured: /compra já foi capturada/i,
    authorization_proof_invalid: /prova de autorização.*inválida/i,
    vault_token_invalid: /token de pagamento.*inválido/i,
    request_invalid: /solicitação foi rejeitada/i,
    reader_not_authorized: /sem autorização para consultar/i,
    signature_invalid: /assinatura da solicitação.*inválida/i,
    profile_not_trusted: /perfil.*não é confiável/i,
  };

  for (const [code, copy] of Object.entries(expectedCopy)) {
    const presentation = presentAvalError({ status: 422, code });
    assert.match(`${presentation.title} ${presentation.message} ${presentation.recovery}`, copy);
  }
});

test('browser BFF session, role, audit, and idempotency failures have safe guidance', () => {
  const expectedCopy = {
    ui_login_invalid: /credencial local.*inválida/i,
    ui_session_required: /sessão.*necessária/i,
    csrf_invalid: /proteção da sessão.*inválida/i,
    ui_role_not_authorized: /papel.*não possui acesso/i,
    idempotency_unavailable: /idempotência.*indisponível/i,
    audit_unavailable: /trilha de auditoria.*indisponível/i,
  };

  for (const [code, copy] of Object.entries(expectedCopy)) {
    const presentation = presentAvalError({
      status: code.endsWith('unavailable') ? 503 : code === 'ui_login_invalid' || code === 'ui_session_required' ? 401 : 403,
      code,
    });
    assert.match(`${presentation.title} ${presentation.message} ${presentation.recovery}`, copy);
  }
});

test('session recovery copy directs a fresh login without suggesting mutation replay', () => {
  for (const [status, code] of [[401, 'ui_session_required'], [403, 'csrf_invalid']]) {
    const presentation = presentAvalError({ status, code });
    assert.match(presentation.recovery, /sessão local.*descartada/i);
    assert.match(presentation.recovery, /entre novamente/i);
    assert.doesNotMatch(presentation.recovery, /tente novamente|repita|reenvie/i);
    assert.equal(presentation.action, 'none');
  }
});

test('503, 409, and 422 prescribe safe and distinct next actions', () => {
  const unavailable = presentAvalError({ status: 503, code: 'revocation_unavailable' });
  assert.equal(unavailable.action, 'check-availability');
  assert.match(unavailable.message, /nenhum pagamento foi iniciado/i);
  assert.match(unavailable.recovery, /não repita.*pagamento/i);

  const conflict = presentAvalError({ status: 409, code: 'transaction_already_captured' });
  assert.equal(conflict.action, 'check-status');
  assert.match(conflict.recovery, /status.*recibo/i);

  const reusedKey = presentAvalError({ status: 409, code: 'idempotency_key_reused' });
  assert.equal(reusedKey.title, 'Operação preservada');
  assert.equal(reusedKey.action, 'check-status');
  assert.match(reusedKey.recovery, /status.*recibo/i);

  const rejected = presentAvalError({ status: 422, code: 'request_invalid' });
  assert.equal(rejected.action, 'none');
  assert.match(rejected.title, /solicitação rejeitada/i);

  const visible = JSON.stringify([unavailable, conflict, rejected]);
  for (const secret of [
    '4242424242424242',
    'vt_private-token',
    'eyJhbGciOiJFUzI1NiJ9.eyJhdWQiOiJtZXJjaGFudCJ9.signature',
    'proof_private',
  ]) {
    assert.equal(visible.includes(secret), false);
  }
});
