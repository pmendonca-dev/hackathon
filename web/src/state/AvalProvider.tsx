import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from 'react';

import type {
  AvalGateway,
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
  UiAuditProjection,
  UiBffGatewayContract,
  UiDisputeProjection,
  UiLoginRequest,
  UiRole,
  UiSessionMaterial,
  UiWorkspaceProjection,
} from '../contracts/avalGateway.ts';
import { createAvalGateway } from '../gateways/createAvalGateway.ts';
import { UiBffHttpError } from '../gateways/uiBffGateway.ts';
import {
  presentUnavailable,
  type AvalErrorPresentation,
} from '../errors/avalError.ts';
import { AvalContext, type AvalContextValue, type View } from './AvalContext.ts';
import { createSessionGeneration } from './sessionGeneration.ts';
import { sessionRecovery } from './sessionRecovery.ts';

type BrowserGateway = AvalGateway | UiBffGatewayContract;

const DEFAULT_AVAL_GATEWAY = createAvalGateway(import.meta.env);

function isUiBffGateway(gateway: BrowserGateway): gateway is UiBffGatewayContract {
  return 'login' in gateway;
}

function safeFailure(error: unknown, fallback: string): AvalErrorPresentation {
  return error instanceof UiBffHttpError
    ? error.presentation
    : presentUnavailable(fallback);
}

function defaultView(role: UiRole): View {
  if (role === 'merchant') return 'merchant';
  if (role === 'auditor') return 'auditor';
  if (role === 'operator') return 'trial';
  return 'human';
}

export function AvalProvider({
  children,
  gateway = DEFAULT_AVAL_GATEWAY,
}: {
  children: ReactNode;
  gateway?: BrowserGateway;
}) {
  const apiGateway = isUiBffGateway(gateway) ? gateway : null;
  const mockGateway = apiGateway ? null : gateway as AvalGateway;
  const dataSource = apiGateway ? 'api' : 'mock';
  const [snapshot, setSnapshot] = useState<AvalSnapshot | null>(null);
  const [workspace, setWorkspace] = useState<UiWorkspaceProjection | null>(null);
  const [audit, setAudit] = useState<UiAuditProjection | null>(null);
  const [dispute, setDispute] = useState<UiDisputeProjection | null>(null);
  const [session, setSession] = useState<UiSessionMaterial | null>(null);
  const [loading, setLoading] = useState(dataSource === 'mock');
  const [error, setError] = useState<AvalErrorPresentation | null>(null);
  const [view, setView] = useState<View>('human');
  const [lastCommandReceipt, setLastCommandReceipt] = useState<TrialCommandReceipt | null>(null);
  const sessionGeneration = useRef(createSessionGeneration()).current;

  const clearProtectedState = useCallback(() => {
    sessionGeneration.invalidate();
    setSession(null);
    setWorkspace(null);
    setAudit(null);
    setDispute(null);
    setLastCommandReceipt(null);
    setView('human');
  }, [sessionGeneration]);

  const handleFailure = useCallback((failure: unknown, fallback: string) => {
    const presentation = safeFailure(failure, fallback);
    if (apiGateway && sessionRecovery(presentation).clearSession) {
      clearProtectedState();
    }
    setError(presentation);
  }, [apiGateway, clearProtectedState]);

  const loadBffWorkspace = useCallback(async (
    role: UiRole,
    requestGeneration = sessionGeneration.current(),
  ) => {
    if (!apiGateway) return;
    try {
      const nextWorkspace = await apiGateway.loadWorkspace();
      if (nextWorkspace.role !== role) {
        throw new Error('BFF role projection mismatch.');
      }
      const mandateId = nextWorkspace.mandates[0]?.mandate_id;
      let nextAudit: UiAuditProjection | null = null;
      let nextDispute: UiDisputeProjection | null = null;
      if (mandateId && (role === 'holder' || role === 'auditor')) {
        [nextAudit, nextDispute] = await Promise.all([
          apiGateway.loadAudit(mandateId),
          apiGateway.loadDispute(mandateId),
        ]);
      }
      if (!sessionGeneration.isCurrent(requestGeneration)) return;
      setWorkspace(nextWorkspace);
      setAudit(nextAudit);
      setDispute(nextDispute);
    } catch (loadError) {
      if (!sessionGeneration.isCurrent(requestGeneration)) return;
      throw loadError;
    }
  }, [apiGateway, sessionGeneration]);

  const login = useCallback(async (request: UiLoginRequest) => {
    if (!apiGateway) return;
    setLoading(true);
    setError(null);
    try {
      const issuedSession = await apiGateway.login(request);
      const requestGeneration = sessionGeneration.invalidate();
      setSession(issuedSession);
      setView(defaultView(issuedSession.role));
      await loadBffWorkspace(issuedSession.role, requestGeneration);
    } catch (loginError) {
      handleFailure(loginError, 'Não foi possível iniciar a sessão local.');
    } finally {
      setLoading(false);
    }
  }, [apiGateway, handleFailure, loadBffWorkspace, sessionGeneration]);

  const logout = useCallback(async () => {
    if (!apiGateway || !session) return;
    const csrfToken = session.csrfToken;
    setLoading(true);
    setError(null);
    clearProtectedState();
    try {
      await apiGateway.logout(csrfToken);
    } catch (logoutError) {
      handleFailure(logoutError, 'A sessão local foi encerrada, mas o servidor não confirmou o logout.');
    } finally {
      setLoading(false);
    }
  }, [apiGateway, clearProtectedState, handleFailure, session]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      if (apiGateway) {
        if (!session) return;
        await loadBffWorkspace(session.role);
      } else {
        setSnapshot(await mockGateway!.loadWorkspace());
      }
    } catch (reloadError) {
      handleFailure(reloadError, 'Não foi possível carregar a projeção canônica.');
    } finally {
      setLoading(false);
    }
  }, [apiGateway, handleFailure, loadBffWorkspace, mockGateway, session]);

  useEffect(() => {
    if (apiGateway) return;
    let active = true;
    mockGateway!.loadWorkspace()
      .then((loadedSnapshot) => {
        if (active) setSnapshot(loadedSnapshot);
      })
      .catch((loadError: unknown) => {
        if (active) setError(safeFailure(loadError, 'Não foi possível carregar os dados de demonstração.'));
      })
      .finally(() => {
        if (active) setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [apiGateway, mockGateway]);

  const submitTrialCommand = useCallback(async (command: TrialCommand) => {
    const requestGeneration = sessionGeneration.current();
    setError(null);
    try {
      if (!apiGateway) {
        setLastCommandReceipt(await mockGateway!.submitTrialCommand(command));
        return;
      }
      if (!session || session.role !== 'operator' || command.kind !== 'revoke-mandate') {
        throw new Error('Operator session required.');
      }
      const result = await apiGateway.revokeMandate(
        command.targetId,
        command.idempotencyKey,
        session.csrfToken,
      );
      if (!sessionGeneration.isCurrent(requestGeneration)) return;
      setLastCommandReceipt({
        requestId: command.idempotencyKey,
        dataSource: 'api',
        outcome: 'accepted',
        canonicalStateChanged: true,
        effectiveAt: null,
        message: `O BFF confirmou o mandato ${result.mandate_id} como revogado.`,
      });
      await loadBffWorkspace(session.role, requestGeneration);
    } catch (commandError) {
      if (sessionGeneration.isCurrent(requestGeneration)) {
        handleFailure(commandError, 'O BFF não confirmou a revogação. Nenhuma alteração foi presumida pelo browser.');
      }
    }
  }, [apiGateway, handleFailure, loadBffWorkspace, mockGateway, session, sessionGeneration]);

  const sessionSummary = useMemo(
    () => session ? { role: session.role, expiresAt: session.expiresAt } : null,
    [session],
  );
  const value = useMemo<AvalContextValue>(() => ({
    snapshot,
    workspace,
    audit,
    dispute,
    session: sessionSummary,
    dataSource,
    loading,
    error,
    view,
    lastCommandReceipt,
    setView,
    login,
    logout,
    reload,
    submitTrialCommand,
  }), [
    snapshot,
    workspace,
    audit,
    dispute,
    sessionSummary,
    dataSource,
    loading,
    error,
    view,
    lastCommandReceipt,
    login,
    logout,
    reload,
    submitTrialCommand,
  ]);

  return <AvalContext.Provider value={value}>{children}</AvalContext.Provider>;
}
