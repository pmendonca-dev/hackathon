import type { ReactNode } from 'react';
import {
  LayoutGrid,
  ScrollText,
  CreditCard,
  Bot,
  Store,
  ListTree,
  Gavel,
  Scale,
  RotateCcw,
  ChevronRight,
} from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { useStore } from '../domain/store';
import type { Route } from '../domain/store';
import { Badge, StatusDot, Button } from './ui';

const NAV: { route: Route; label: string; icon: LucideIcon }[] = [
  { route: 'overview', label: 'Overview', icon: LayoutGrid },
  { route: 'mandates', label: 'Mandates', icon: ScrollText },
  { route: 'payments', label: 'Payments', icon: CreditCard },
  { route: 'agent', label: 'Agent Activity', icon: Bot },
  { route: 'merchant', label: 'Merchant', icon: Store },
  { route: 'ledger', label: 'Ledger', icon: ListTree },
  { route: 'disputes', label: 'Disputes', icon: Scale },
  { route: 'judge', label: 'Judge Console', icon: Gavel },
];

export function Sidebar() {
  const { state, go } = useStore();
  return (
    <nav className="hidden w-[236px] shrink-0 flex-col border-r border-line bg-ink-900 lg:flex">
      <div className="border-b border-line px-5 py-5">
        <div className="flex items-center gap-2.5">
          <span className="flex size-7 items-center justify-center rounded-md bg-allow">
            <span className="font-display text-[13px] font-bold text-ink-950">Y</span>
          </span>
          <div className="leading-none">
            <div className="font-display text-[15px] font-bold tracking-tight">YUNO</div>
            <div className="eyebrow mt-1">Authorization Layer</div>
          </div>
        </div>
      </div>

      <ul className="flex-1 space-y-0.5 p-3">
        {NAV.map(({ route, label, icon: Icon }) => {
          const active = state.route === route;
          return (
            <li key={route} className="relative">
              {active && (
                <span className="absolute top-1/2 -left-3 h-4 w-0.5 -translate-y-1/2 rounded-r bg-allow" />
              )}
              <button
                onClick={() => go(route)}
                className={`flex w-full items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] transition-colors ${
                  active
                    ? 'bg-ink-800 font-medium text-fg'
                    : 'text-fg-mute hover:bg-white/3 hover:text-fg-dim'
                }`}
              >
                <Icon size={15} strokeWidth={1.75} className={active ? 'text-allow' : ''} />
                {label}
              </button>
            </li>
          );
        })}
      </ul>

      <div className="space-y-3 border-t border-line px-5 py-4">
        <Row label="System status">
          <span className="mono flex items-center gap-1.5 text-[10px] font-semibold text-allow">
            <StatusDot tone="allow" pulse />
            OPERATIONAL
          </span>
        </Row>
        <Row label="Environment">
          <span className="mono text-[10px] font-semibold text-fg-dim">DEMO</span>
        </Row>
        <div className="flex items-center gap-2.5 border-t border-line pt-3.5">
          <span className="flex size-7 shrink-0 items-center justify-center rounded-full border border-line bg-ink-800 font-display text-[11px] font-semibold text-fg-dim">
            MS
          </span>
          <div className="min-w-0 leading-tight">
            <div className="truncate text-[12px] font-medium">Marta Silva</div>
            <div className="eyebrow">Principal</div>
          </div>
        </div>
      </div>
    </nav>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-2">
      <span className="eyebrow">{label}</span>
      {children}
    </div>
  );
}

export function TopBar({
  title,
  subtitle,
  crumb,
  action,
}: {
  title: string;
  subtitle?: string;
  crumb: string[];
  action?: ReactNode;
}) {
  const { state, reset } = useStore();
  return (
    <header className="sticky top-0 z-30 border-b border-line bg-ink-950/85 backdrop-blur-md">
      <div className="flex items-center justify-between gap-4 border-b border-line/60 px-6 py-2 lg:px-8">
        <ol className="flex min-w-0 items-center gap-1.5 overflow-hidden">
          {crumb.map((c, i) => (
            <li key={c} className="flex shrink-0 items-center gap-1.5">
              {i > 0 && <ChevronRight size={11} className="text-fg-faint" />}
              <span
                className={`mono text-[10px] tracking-wider uppercase ${
                  i === crumb.length - 1 ? 'text-fg-dim' : 'text-fg-faint'
                }`}
              >
                {c}
              </span>
            </li>
          ))}
        </ol>
        <div className="flex shrink-0 items-center gap-2.5">
          <span className="mono hidden items-center gap-1.5 text-[10px] text-fg-mute sm:flex">
            <StatusDot tone={state.pspOnline ? 'allow' : 'hold'} pulse={!state.pspOnline} />
            PSP {state.pspOnline ? 'ONLINE' : 'UNREACHABLE'}
          </span>
          <Badge tone="verify" size="sm">
            DEMO
          </Badge>
          <button
            onClick={reset}
            title="Reset all mock state"
            className="rounded-lg p-1.5 text-fg-mute transition-colors hover:bg-white/5 hover:text-fg"
            aria-label="Reset demo"
          >
            <RotateCcw size={13} />
          </button>
          <span className="flex size-7 items-center justify-center rounded-full border border-line bg-ink-800 font-display text-[10px] font-semibold text-fg-dim">
            MS
          </span>
        </div>
      </div>

      <div className="flex flex-wrap items-end justify-between gap-4 px-6 py-5 lg:px-8">
        <div>
          <h1 className="font-display text-[26px] leading-none font-bold tracking-[-0.02em]">
            {title}
          </h1>
          {subtitle && <p className="mt-2 text-[13px] text-fg-mute">{subtitle}</p>}
        </div>
        {action}
      </div>
    </header>
  );
}

/** Compact nav for viewports below the sidebar breakpoint. */
export function MobileNav() {
  const { state, go } = useStore();
  return (
    <div className="flex gap-1 overflow-x-auto border-b border-line bg-ink-900 px-4 py-2 lg:hidden">
      {NAV.map(({ route, label, icon: Icon }) => (
        <button
          key={route}
          onClick={() => go(route)}
          className={`mono flex shrink-0 items-center gap-1.5 rounded-lg px-2.5 py-1.5 text-[10px] uppercase transition-colors ${
            state.route === route ? 'bg-ink-800 text-allow' : 'text-fg-mute'
          }`}
        >
          <Icon size={13} strokeWidth={1.75} />
          {label}
        </button>
      ))}
    </div>
  );
}

export function Page({ children }: { children: ReactNode }) {
  return (
    <div className="anim-rise mx-auto w-full max-w-[1180px] px-6 py-7 lg:px-8">{children}</div>
  );
}

export { Button };
