import { AlertTriangle, LoaderCircle } from 'lucide-react';

import { Shell } from './components/Shell.tsx';
import { Button } from './components/ui.tsx';
import { HumanView } from './pages/HumanView.tsx';
import { MerchantView } from './pages/MerchantView.tsx';
import { AuditorView } from './pages/AuditorView.tsx';
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
          <span className="ml-3 text-sm text-fg-mute">Carregando snapshot mock…</span>
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

  return (
    <Shell>
      {error && <div className="mx-auto mt-4 max-w-[1180px] px-5 text-[12px] text-deny" role="alert">{error}</div>}
      {view === 'human' && <HumanView data={snapshot.human} />}
      {view === 'merchant' && <MerchantView data={snapshot.merchant} />}
      {view === 'auditor' && <AuditorView data={snapshot.auditor} />}
      {view === 'trial' && (
        <TrialConsole
          mandateId={snapshot.human.mandate.id}
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
