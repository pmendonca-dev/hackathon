import { AlertTriangle, LoaderCircle } from 'lucide-react';

import { Shell } from './components/Shell.tsx';
import { Button } from './components/ui.tsx';
import { AuditorTrailView } from './pages/AuditorTrailView.tsx';
import { HolderView } from './pages/HolderView.tsx';
import { MerchantDeskView } from './pages/MerchantDeskView.tsx';
import { TrialByFireConsole } from './pages/TrialByFireConsole.tsx';
import { useAval } from './state/AvalContext.ts';
import { AvalProvider } from './state/AvalProvider.tsx';

function Workspace() {
  const { view, loading, error, mandates, reload } = useAval();

  if (loading && mandates.length === 0 && !error) {
    return (
      <Shell>
        <div className="flex min-h-[70vh] items-center justify-center" role="status">
          <LoaderCircle className="animate-spin text-allow" size={24} aria-hidden="true" />
          <span className="ml-3 text-sm text-fg-mute">Lendo o estado canônico…</span>
        </div>
      </Shell>
    );
  }

  // An unreachable runtime is shown as unreachable. There is no fixture fallback: a
  // screen that filled itself with invented data would be indistinguishable from a
  // working system precisely when it matters most.
  if (error && mandates.length === 0) {
    return (
      <Shell>
        <div className="mx-auto flex min-h-[70vh] max-w-md flex-col items-center justify-center px-6 text-center" role="alert">
          <AlertTriangle className="text-deny" size={28} aria-hidden="true" />
          <h1 className="mt-4 font-display text-xl font-semibold">Runtime indisponível</h1>
          <p className="mt-2 text-sm leading-relaxed text-fg-mute">{error}</p>
          <Button className="mt-5" onClick={() => void reload()}>Tentar novamente</Button>
        </div>
      </Shell>
    );
  }

  return (
    <Shell>
      {error && (
        <div className="mx-auto mt-4 max-w-[1180px] px-5 text-[12px] text-deny" role="alert">
          {error}
        </div>
      )}
      {view === 'human' && <HolderView />}
      {view === 'merchant' && <MerchantDeskView />}
      {view === 'auditor' && <AuditorTrailView />}
      {view === 'trial' && <TrialByFireConsole />}
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
