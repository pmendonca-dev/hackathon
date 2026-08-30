import assert from 'node:assert/strict';
import test from 'node:test';

import { sessionRecovery } from '../src/state/sessionRecovery.ts';

test('expired sessions and invalid CSRF require a fresh login without retrying the operation', () => {
  assert.deepEqual(
    sessionRecovery({ status: 401, code: 'ui_session_required' }),
    { clearSession: true, returnToLogin: true, retry: false },
  );
  assert.deepEqual(
    sessionRecovery({ status: 403, code: 'csrf_invalid' }),
    { clearSession: true, returnToLogin: true, retry: false },
  );
});

test('authorization and availability failures preserve an otherwise valid session', () => {
  for (const failure of [
    { status: 403, code: 'ui_role_not_authorized' },
    { status: 503, code: 'audit_unavailable' },
    { status: null, code: 'runtime_unavailable' },
  ]) {
    assert.deepEqual(
      sessionRecovery(failure),
      { clearSession: false, returnToLogin: false, retry: false },
    );
  }
});
