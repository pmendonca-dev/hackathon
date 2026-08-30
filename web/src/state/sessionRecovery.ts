export interface SessionFailure {
  status: number | null;
  code: string;
}

export interface SessionRecovery {
  clearSession: boolean;
  returnToLogin: boolean;
  retry: false;
}

export function sessionRecovery(failure: SessionFailure): SessionRecovery {
  const requiresFreshLogin =
    failure.code === 'ui_session_required'
    || failure.code === 'csrf_invalid';

  return {
    clearSession: requiresFreshLogin,
    returnToLogin: requiresFreshLogin,
    retry: false,
  };
}
