import { AlertTriangle, LoaderCircle } from 'lucide-react';

import { Shell } from './components/Shell.tsx';
import { Button } from './components/ui.tsx';
import { HumanView } from './pages/HumanView.tsx';
import { MerchantView } from './pages/MerchantView.tsx';
import { AuditorView } from './pages/AuditorView.tsx';
import { LiveAuditorView } from './pages/LiveAuditorView.tsx';
import { LiveHumanView } from './pages/LiveHumanView.tsx';
import { LiveMerchantView } from './pages/LiveMerchantView.tsx';
import { TrialConsole } from './pages/TrialConsole.tsx';
import { useAval } from './state/AvalContext.ts';
import { AvalProvider } from './state/AvalProvider.tsx';

function Workspace() {
  const { snapshot, loading, error, view, reload, lastCommandReceipt, submitTrialCommand } = useAval();

  if (loading && !snapshot) {
    return (
      <Shell>
        <div className="flex min-h-[70vh] items-center justify-center" role="status">
          <LoaderCircle className="animate-spin text-allow" size={24} aria-hidden="true" />
          <span className="ml-3 text-sm text-fg-mute">Carregando estado da API…</span>
        </div>
      </Shell>
    );
  }

  if (error || !snapshot) {
    return (
      <Shell>
        <div className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center px-6 text-center" role="alert">
          <AlertTriangle className="text-deny" size={28} aria-hidden="true" />
          <h1 className="mt-4 font-display text-xl font-semibold">Snapshot indisponível</h1>
          <p className="mt-2 text-sm leading-relaxed text-fg-mute">{error ?? 'A boundary não retornou dados.'}</p>
          <Button className="mt-5" onClick={() => void reload()}>Tentar novamente</Button>
        </div>
      </Shell>
    );
  }

  const liveSnapshot = snapshot.meta.dataSource === 'api' && 'live' in snapshot
    ? snapshot
    : null;
  const mockSnapshot = 'human' in snapshot ? snapshot : null;

  return (
    <Shell>
      {snapshot.meta.dataSource === 'mock' && (
        <div
          className="sticky top-[57px] z-10 border-b border-escalate/40 bg-escalate-dk px-5 py-2 text-center font-mono text-[11px] font-semibold tracking-wide text-escalate"
          role="status"
        >
          DADOS DE DEMONSTRAÇÃO / MOCK — estas projeções não representam estado vivo nem comprovam execução do runtime.
        </div>
      )}
      {error && <div className="mx-auto mt-4 max-w-[1180px] px-5 text-[12px] text-deny" role="alert">{error}</div>}
      {liveSnapshot ? (
        <>
          {view === 'human' && <LiveHumanView data={liveSnapshot.live} />}
          {view === 'merchant' && <LiveMerchantView capture={liveSnapshot.live.capture} receipts={liveSnapshot.live.receipts} />}
          {view === 'auditor' && <LiveAuditorView audit={liveSnapshot.live.audit} dispute={liveSnapshot.live.dispute} />}
          {view === 'trial' && (
            <TrialConsole
              mandateId={liveSnapshot.live.mandateId}
              dataSource="api"
              receipt={lastCommandReceipt}
              onSubmit={submitTrialCommand}
            />
          )}
        </>
      ) : mockSnapshot ? (
        <>
          {view === 'human' && <HumanView data={mockSnapshot.human} />}
          {view === 'merchant' && <MerchantView data={mockSnapshot.merchant} />}
          {view === 'auditor' && <AuditorView data={mockSnapshot.auditor} />}
          {view === 'trial' && (
            <TrialConsole
              mandateId={mockSnapshot.human.mandate.id}
              dataSource="mock"
              receipt={lastCommandReceipt}
              onSubmit={submitTrialCommand}
            />
          )}
        </>
      ) : null}
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
