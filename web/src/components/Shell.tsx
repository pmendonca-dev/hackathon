import type { ReactNode } from 'react';
import { Gavel, RefreshCw, ScrollText, Store, UserRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { useAval, type View } from '../state/AvalProvider.tsx';
import { Badge, Button } from './ui.tsx';

const views: Array<{ id: View; label: string; context: string; icon: LucideIcon }> = [
  { id: 'human', label: 'Humano', context: 'Minha autoridade', icon: UserRound },
  { id: 'merchant', label: 'Merchant', context: 'O que verifiquei', icon: Store },
  { id: 'auditor', label: 'Auditor', context: 'Trilha completa', icon: ScrollText },
  { id: 'trial', label: 'Trial-by-fire', context: 'Intenções de mudança', icon: Gavel },
];

export function Shell({ children }: { children: ReactNode }) {
  const { view, setView, snapshot, loading, reload } = useAval();

  return (
    <div className="min-h-full bg-ink-950 text-fg lg:grid lg:grid-cols-[252px_minmax(0,1fr)]">
      <aside className="border-b border-line bg-ink-900 lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="flex items-center justify-between border-b border-line px-5 py-5">
          <div className="flex items-center gap-3">
            <span className="flex size-9 items-center justify-center rounded-lg bg-allow font-display text-sm font-black text-ink-950">A</span>
            <div>
              <p className="font-display text-base font-bold tracking-tight">AVAL</p>
              <p className="eyebrow mt-0.5">Authorization control</p>
            </div>
          </div>
        </div>

        <nav aria-label="Perspectivas" className="overflow-x-auto p-3 lg:overflow-visible">
          <ul className="flex min-w-max gap-1 lg:min-w-0 lg:flex-col">
            {views.map(({ id, label, context, icon: Icon }) => {
              const active = view === id;
              return (
                <li key={id}>
                  <button
                    type="button"
                    aria-current={active ? 'page' : undefined}
                    onClick={() => setView(id)}
                    className={`group flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors ${active ? 'bg-ink-800 text-fg' : 'text-fg-mute hover:bg-white/4 hover:text-fg'}`}
                  >
                    <Icon size={17} className={active ? 'text-allow' : ''} aria-hidden="true" />
                    <span>
                      <span className="block text-[13px] font-semibold">{label}</span>
                      <span className="eyebrow hidden lg:block">{context}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className="hidden border-t border-line p-5 lg:absolute lg:inset-x-0 lg:bottom-0 lg:block">
          <p className="eyebrow">Origem do snapshot</p>
          <div className="mt-2 flex items-center justify-between gap-2">
            <Badge tone={snapshot?.meta.dataSource === 'mock' ? 'escalate' : 'verify'}>{snapshot?.meta.dataSource ?? 'carregando'}</Badge>
            <span className="mono text-[9px] text-fg-mute">SEM REDE</span>
          </div>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 border-b border-line bg-ink-950/90 px-5 py-3 backdrop-blur-md sm:px-7">
          <div className="mx-auto flex max-w-[1180px] items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="eyebrow">Sala de prova · AP2 v0.2</p>
              <p className="truncate text-[12px] text-fg-mute">{snapshot?.meta.fixtureId ?? 'Carregando contrato de apresentação'}</p>
            </div>
            <div className="flex items-center gap-2">
              <Badge tone="escalate">MOCK</Badge>
              <Button variant="ghost" onClick={() => void reload()} disabled={loading} aria-label="Recarregar snapshot mock">
                <RefreshCw size={13} aria-hidden="true" />
                <span className="hidden sm:inline">Recarregar</span>
              </Button>
            </div>
          </div>
        </header>
        <main id="main-content">{children}</main>
      </div>
    </div>
  );
}
