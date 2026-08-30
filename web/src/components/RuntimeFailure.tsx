import { AlertTriangle, FileSearch, RefreshCw, ShieldAlert } from 'lucide-react';

import type { AvalErrorPresentation } from '../errors/avalError.ts';
import { safeDisplayText } from '../utils/safePresentation.ts';
import { Button } from './ui.tsx';

const toneClass = {
  deny: 'border-deny/40 bg-deny-dk text-deny',
  hold: 'border-hold/40 bg-hold-dk text-hold',
  verify: 'border-verify/40 bg-verify-dk text-verify',
  escalate: 'border-escalate/40 bg-escalate-dk text-escalate',
  neutral: 'border-line-hi bg-ink-850 text-fg-dim',
} as const;

function actionLabel(error: AvalErrorPresentation): string | null {
  if (error.action === 'check-status') return 'Consultar status e recibo';
  if (error.action === 'check-availability') return 'Verificar disponibilidade';
  if (error.action === 'retry-read') return 'Tentar leitura novamente';
  return null;
}

export function RuntimeFailure({
  error,
  onAction,
  compact = false,
}: {
  error: AvalErrorPresentation;
  onAction?(): void;
  compact?: boolean;
}) {
  const label = actionLabel(error);
  const isOperationPreserved = error.status === 409;
  const isSafeBlock = error.status === 503;
  const Icon = isSafeBlock ? ShieldAlert : isOperationPreserved ? FileSearch : AlertTriangle;

  return (
    <section
      className={`rounded-2xl border ${toneClass[error.tone]} ${compact ? 'p-4' : 'p-5'}`}
      role="alert"
      aria-live="polite"
    >
      <div className="flex items-start gap-3">
        <Icon className="mt-0.5 shrink-0" size={20} aria-hidden="true" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <h2 className="font-display text-base font-semibold text-fg">{error.title}</h2>
            <span className="mono text-[10px] uppercase tracking-wider opacity-75">
              {safeDisplayText(error.status ? `HTTP ${error.status} · ${error.code}` : error.code)}
            </span>
          </div>
          <p className="mt-1 text-[13px] leading-relaxed text-fg-dim">{safeDisplayText(error.message)}</p>
          <p className="mt-2 text-[12px] leading-relaxed opacity-90">{safeDisplayText(error.recovery)}</p>
          {label && onAction && (
            <Button className="mt-4" variant="ghost" onClick={onAction}>
              <RefreshCw size={14} aria-hidden="true" />{label}
            </Button>
          )}
        </div>
      </div>
    </section>
  );
}
