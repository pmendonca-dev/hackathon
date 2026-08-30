import {
  useCallback,
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
import { createAvalGateway } from '../gateways/createAvalGateway.ts';
import { AvalHttpError } from '../gateways/httpAvalGateway.ts';
import {
  presentUnavailable,
  type AvalErrorPresentation,
} from '../errors/avalError.ts';
import { AvalContext, type AvalContextValue, type View } from './AvalContext.ts';
const DEFAULT_AVAL_GATEWAY = createAvalGateway(import.meta.env);

function safeFailure(error: unknown, fallback: string): AvalErrorPresentation {
  return error instanceof AvalHttpError
    ? error.presentation
    : presentUnavailable(fallback);
}

export function AvalProvider({
  children,
  gateway = DEFAULT_AVAL_GATEWAY,
}: {
  children: ReactNode;
  gateway?: AvalGateway;
}) {
  const [snapshot, setSnapshot] = useState<AvalSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<AvalErrorPresentation | null>(null);
  const [view, setView] = useState<View>('human');
  const [lastCommandReceipt, setLastCommandReceipt] = useState<TrialCommandReceipt | null>(null);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setSnapshot(await gateway.loadWorkspace());
    } catch (error) {
      setError(safeFailure(error, 'Não foi possível carregar a projeção canônica.'));
    } finally {
      setLoading(false);
    }
  }, [gateway]);

  useEffect(() => {
    let active = true;

    async function loadInitialSnapshot() {
      try {
        const loadedSnapshot = await gateway.loadWorkspace();
        if (active) setSnapshot(loadedSnapshot);
      } catch (error) {
        if (active) {
          setError(safeFailure(error, 'Não foi possível carregar a projeção canônica.'));
        }
      } finally {
        if (active) setLoading(false);
      }
    }

    void loadInitialSnapshot();
    return () => {
      active = false;
    };
  }, [gateway]);

  const submitTrialCommand = useCallback(
    async (command: TrialCommand) => {
      setError(null);
      try {
        const receipt = await gateway.submitTrialCommand(command);
        setLastCommandReceipt(receipt);
        if (receipt.dataSource === 'api') {
          setSnapshot(await gateway.loadWorkspace());
        }
      } catch (error) {
        setError(safeFailure(error, 'A boundary não confirmou o comando. Nenhuma alteração foi presumida pelo browser.'));
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
