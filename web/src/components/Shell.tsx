import { useState, type ReactNode } from 'react';
import { Gavel, KeyRound, PanelLeftClose, PanelLeftOpen, RefreshCw, ScrollText, Store, UserRound } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';

import { useAval, type View } from '../state/AvalContext.ts';
import { Badge, Button } from './ui.tsx';

const views: Array<{ id: View; label: string; context: string; icon: LucideIcon }> = [
  { id: 'human', label: 'Holder', context: 'My authority', icon: UserRound },
  { id: 'merchant', label: 'Merchant', context: 'What I verified', icon: Store },
  { id: 'auditor', label: 'Auditor', context: 'The full trail', icon: ScrollText },
  { id: 'trial', label: 'Trial by fire', context: 'Change it live', icon: Gavel },
];

/**
 * The persistent strip is operational provenance, not decoration: it says which key is
 * signing and whether the trail still verifies, and it cannot scroll away. Those are
 * the two facts that decide whether anything else on screen can be trusted.
 */
export function Shell({ children }: { children: ReactNode }) {
  const { view, setView, loading, reload, principalId, holderKid, walletReady, chain } = useAval();
  const [sidebarCollapsed, setSidebarCollapsed] = useState(false);

  return (
    <div className={`min-h-full bg-ink-950 text-fg transition-[grid-template-columns] duration-200 ease-out motion-reduce:transition-none lg:grid ${sidebarCollapsed ? 'lg:grid-cols-[76px_minmax(0,1fr)]' : 'lg:grid-cols-[252px_minmax(0,1fr)]'}`}>
      <aside className="border-b border-line bg-ink-900 lg:sticky lg:top-0 lg:h-screen lg:border-r lg:border-b-0">
        <div className="sidebar-topbar flex h-[84px] items-center border-b border-line px-4 lg:h-[88px]">
          <div className="flex w-full items-center">
            <div className={`flex min-w-0 items-center ${sidebarCollapsed ? 'gap-0' : 'gap-2'}`}>
              <button
                type="button"
                className="sidebar-monogram-button hidden size-9 shrink-0 items-center justify-center rounded-full bg-verify font-display text-lg font-bold text-white shadow-sm lg:inline-flex"
                aria-label={sidebarCollapsed ? 'Expand sidebar' : 'Collapse sidebar'}
                aria-expanded={!sidebarCollapsed}
                aria-controls="sidebar-navigation"
                onClick={() => setSidebarCollapsed((collapsed) => !collapsed)}
              >
                <span className="sidebar-monogram-letter">A</span>
                {sidebarCollapsed ? (
                  <PanelLeftOpen className="sidebar-monogram-icon" size={16} aria-hidden="true" />
                ) : (
                  <PanelLeftClose className="sidebar-monogram-icon" size={16} aria-hidden="true" />
                )}
              </button>
              <span className="flex size-9 shrink-0 items-center justify-center rounded-full bg-verify font-display text-lg font-bold text-white shadow-sm lg:hidden">A</span>
              <div className={`sidebar-brand-copy ${sidebarCollapsed ? 'sidebar-brand-copy--collapsed' : ''}`}>
                <p className="font-display text-base font-bold tracking-tight">AVAL</p>
                <p className="eyebrow mt-0.5">Authorization control</p>
              </div>
            </div>
          </div>
        </div>

        <nav id="sidebar-navigation" aria-label="Perspectives" className="overflow-x-auto p-3 lg:overflow-visible">
          <ul className="flex min-w-max gap-1 lg:min-w-0 lg:flex-col">
            {views.map(({ id, label, context, icon: Icon }) => {
              const active = view === id;
              return (
                <li key={id}>
                  <button
                    type="button"
                    aria-current={active ? 'page' : undefined}
                    onClick={() => setView(id)}
                    className={`sidebar-nav-item group flex min-h-12 w-full items-center gap-3 rounded-xl px-3 py-2 text-left transition-colors ${sidebarCollapsed ? 'sidebar-nav-item--collapsed' : ''} ${active ? 'bg-ink-850 text-fg shadow-sm' : 'text-fg-mute hover:bg-ink-800 hover:text-fg'}`}
                  >
                    <Icon size={17} className={`sidebar-nav-icon ${active ? 'text-allow' : ''}`} aria-hidden="true" />
                    <span className={`sidebar-nav-label ${sidebarCollapsed ? 'sidebar-nav-label--collapsed' : ''}`}>
                      <span className="block text-[13px] font-semibold">{label}</span>
                      <span className="eyebrow hidden lg:block">{context}</span>
                    </span>
                  </button>
                </li>
              );
            })}
          </ul>
        </nav>

        <div className={`sidebar-footer hidden border-t border-line p-5 lg:absolute lg:inset-x-0 lg:bottom-0 ${sidebarCollapsed ? 'sidebar-footer--collapsed' : ''}`}>
          <p className="eyebrow">Who signs here</p>
          <div className="mt-2 flex items-center justify-between gap-2">
            <Badge tone={walletReady ? 'verify' : 'escalate'}>
              {walletReady ? 'LOCAL KEY' : 'NO KEY'}
            </Badge>
            <span className="mono text-[9px] text-fg-mute">{principalId}</span>
          </div>
          <p className="mono mt-2 truncate text-[9px] text-fg-faint">{holderKid ?? '—'}</p>
        </div>
      </aside>

      <div className="min-w-0">
        <header className="sticky top-0 z-20 flex h-[84px] items-center border-b border-line bg-ink-950/90 px-5 backdrop-blur-md sm:px-7 lg:h-[88px]">
          <div className="flex w-full items-center justify-between gap-4">
            <div className="min-w-0">
              <p className="eyebrow">Authorization lane · deterministic core</p>
              <p className="mono truncate text-[11px] text-fg-mute">
                <KeyRound size={11} className="mr-1 inline" aria-hidden="true" />
                {holderKid ?? 'holder wallet not open yet'}
              </p>
            </div>
            <div className="flex items-center gap-2">
              {chain && (
                <Badge tone={chain.intact ? 'verify' : 'deny'}>
                  {chain.intact ? `CHAIN OK · ${chain.checked}` : `BREAK AT ${chain.broken_at}`}
                </Badge>
              )}
              <Button variant="ghost" onClick={() => void reload()} disabled={loading} aria-label="Reload canonical state">
                <RefreshCw size={13} aria-hidden="true" />
                <span className="hidden sm:inline">Reload</span>
              </Button>
            </div>
          </div>
        </header>
        <main id="main-content">{children}</main>
      </div>
    </div>
  );
}
