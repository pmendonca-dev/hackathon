import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react';

import type {
  AvalGateway,
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
} from '../contracts/avalGateway.ts';
import { createMockAvalGateway } from '../fixtures/mockAvalGateway.ts';

export type View = 'human' | 'merchant' | 'auditor' | 'trial';

interface AvalContextValue {
  snapshot: AvalSnapshot | null;
  loading: boolean;
  error: string | null;
  view: View;
  lastCommandReceipt: TrialCommandReceipt | null;
  setView(view: View): void;
  reload(): Promise<void>;
  submitTrialCommand(command: TrialCommand): Promise<void>;
}

const AvalContext = createContext<AvalContextValue | null>(null);
const DEFAULT_AVAL_GATEWAY = createMockAvalGateway();

export function AvalProvider({
  children,
  gateway = DEFAULT_AVAL_GATEWAY,
}: {
  children: ReactNode;
  gateway?: AvalGateway;
}) {
  const [snapshot, setSnapshot] = useState<AvalSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [view, setView] = useState<View>('human');
  const [lastCommandReceipt, setLastCommandReceipt] = useState<TrialCommandReceipt | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await gateway.loadWorkspace());
    } catch {
      setError('Não foi possível carregar o snapshot. Verifique a boundary configurada.');
    } finally {
      setLoading(false);
    }
  }, [gateway]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const submitTrialCommand = useCallback(
    async (command: TrialCommand) => {
      setError(null);
      try {
        setLastCommandReceipt(await gateway.submitTrialCommand(command));
      } catch {
        setError('A boundary recusou o comando. Nenhuma alteração foi presumida pelo browser.');
      }
    },
    [gateway],
  );

  const value = useMemo<AvalContextValue>(
    () => ({
      snapshot,
      loading,
      error,
      view,
      lastCommandReceipt,
      setView,
      reload,
      submitTrialCommand,
    }),
    [snapshot, loading, error, view, lastCommandReceipt, reload, submitTrialCommand],
  );

  return <AvalContext.Provider value={value}>{children}</AvalContext.Provider>;
}

export function useAval(): AvalContextValue {
  const context = useContext(AvalContext);
  if (!context) throw new Error('useAval must be used inside AvalProvider');
  return context;
}
