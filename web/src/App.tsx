import { lazy, Suspense } from 'react';
import { LoaderCircle } from 'lucide-react';

import { RuntimeFailure } from './components/RuntimeFailure.tsx';
import { Shell } from './components/Shell.tsx';
import { AuditorView } from './pages/AuditorView.tsx';
import { HumanView } from './pages/HumanView.tsx';
import { LoginView } from './pages/LoginView.tsx';
import { MerchantView } from './pages/MerchantView.tsx';
import { TrialConsole } from './pages/TrialConsole.tsx';
import { useAval } from './state/AvalContext.ts';
import { AvalProvider } from './state/AvalProvider.tsx';

const DevelopmentMockWorkspace = import.meta.env.DEV
  ? lazy(() => import('./pages/DevelopmentMockWorkspace.tsx'))
  : null;

function LoadingState({ message }: { message: string }) {
  return (
    <div className="flex min-h-[70vh] items-center justify-center" role="status" aria-live="polite">
      <LoaderCircle className="animate-spin text-allow" size={24} aria-hidden="true" />
      <span className="ml-3 text-sm text-fg-mute">{message}</span>
    </div>
  );
}

function Workspace() {
  const {
    snapshot,
    workspace,
    audit,
    dispute,
    session,
    dataSource,
    loading,
    error,
    view,
    login,
    reload,
    lastCommandReceipt,
    submitTrialCommand,
  } = useAval();

  if (dataSource === 'api' && !session) {
    return <LoginView loading={loading} error={error} onLogin={login} />;
  }

  if (loading && !workspace && !snapshot) {
    return <Shell><LoadingState message="Carregando projeção do BFF…" /></Shell>;
  }

  if (error && !workspace && !snapshot) {
    return (
      <Shell>
        <div className="mx-auto flex min-h-[70vh] max-w-2xl items-center px-6">
          <RuntimeFailure error={error} onAction={() => void reload()} />
        </div>
      </Shell>
    );
  }

  if (dataSource === 'mock' && snapshot && DevelopmentMockWorkspace) {
    if (!('human' in snapshot)) return null;
    return (
      <Shell>
        <div
          className="sticky top-[57px] z-10 border-b border-escalate/40 bg-escalate-dk px-5 py-2 text-center font-mono text-[11px] font-semibold tracking-wide text-escalate"
          role="status"
        >
          DADOS DE DEMONSTRAÇÃO / MOCK — estas projeções não representam estado vivo nem comprovam execução do runtime.
        </div>
        <Suspense fallback={<LoadingState message="Carregando fixture de desenvolvimento…" />}>
          <DevelopmentMockWorkspace
            snapshot={snapshot}
            view={view}
            receipt={lastCommandReceipt}
            onSubmit={submitTrialCommand}
          />
        </Suspense>
      </Shell>
    );
  }

  if (!workspace || !session) return null;

  return (
    <Shell>
      {(error || loading) && (
        <div className="mx-auto mt-4 max-w-[1180px] px-5">
          {error ? (
            <RuntimeFailure error={error} compact onAction={() => void reload()} />
          ) : (
            <div className="flex items-center gap-2 rounded-xl border border-line bg-ink-850 px-4 py-3 text-[12px] text-fg-mute" role="status" aria-live="polite">
              <LoaderCircle className="animate-spin text-verify" size={14} aria-hidden="true" />
              Atualizando a projeção autorizada…
            </div>
          )}
        </div>
      )}
      {session.role === 'holder' && (
        <HumanView workspace={workspace} audit={audit} dispute={dispute} />
      )}
      {session.role === 'merchant' && <MerchantView workspace={workspace} />}
      {session.role === 'auditor' && (
        <AuditorView workspace={workspace} audit={audit} dispute={dispute} />
      )}
      {session.role === 'operator' && (
        <TrialConsole
          mandateId={workspace.mandates[0]?.mandate_id ?? ''}
          dataSource="api"
          receipt={lastCommandReceipt}
          onSubmit={submitTrialCommand}
        />
      )}
    </Shell>
  );
}

export default function App() {
  return (
    <AvalProvider>
      <Workspace />
    </AvalProvider>
  );
}
