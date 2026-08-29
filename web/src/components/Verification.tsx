import { Check, X, ShieldCheck } from 'lucide-react';
import type { Check as PolicyCheck } from '../domain/policy';
import type { MandateEvent } from '../domain/types';
import { toneBg, toneText } from './ui';

/**
 * The seven edge checks. Cyan is reserved for this surface and the receipt seal
 * — it is the colour of "a signature verified", never of "a payment succeeded".
 */
export function CheckList({ checks }: { checks: PolicyCheck[] }) {
  return (
    <ul className="divide-y divide-line/60">
      {checks.map((c) => (
        <li key={c.label} className="flex items-center gap-3 py-2.5">
          <span
            className={`flex size-4 shrink-0 items-center justify-center rounded-full ${
              c.passed ? 'bg-verify/15 text-verify' : 'bg-deny/15 text-deny'
            }`}
          >
            {c.passed ? <Check size={10} strokeWidth={3.5} /> : <X size={10} strokeWidth={3.5} />}
          </span>
          <span className={`flex-1 text-[13px] ${c.passed ? 'text-fg-dim' : 'text-deny'}`}>
            {c.label}
          </span>
          {c.note && <span className="mono truncate text-[10px] text-fg-faint">{c.note}</span>}
        </li>
      ))}
    </ul>
  );
}

/**
 * Three outcomes, not two. A signature can verify perfectly on a purchase the
 * mandate still will not fund — conflating the two is exactly the mistake this
 * product exists to prevent.
 */
export function ProofSeal({
  decision = 'ALLOW',
}: {
  decision?: 'ALLOW' | 'ESCALATE' | 'DENY';
}) {
  const variants = {
    ALLOW: {
      cls: 'border-verify/30 bg-verify/6 text-verify',
      label: 'Authorization proof verified',
    },
    ESCALATE: {
      cls: 'border-escalate/30 bg-escalate/6 text-escalate',
      label: 'Proof valid — authority insufficient',
    },
    DENY: {
      cls: 'border-deny/30 bg-deny/6 text-deny',
      label: 'Authorization refused',
    },
  }[decision];

  return (
    <div className={`flex items-center justify-center gap-2.5 rounded-lg border py-3 ${variants.cls}`}>
      <ShieldCheck size={15} strokeWidth={2} />
      <span className="mono text-[11px] font-semibold tracking-widest uppercase">
        {variants.label}
      </span>
    </div>
  );
}

// ── Timeline ────────────────────────────────────────────────────────────────
export function Timeline({ events }: { events: MandateEvent[] }) {
  return (
    <ol className="relative">
      {events.map((e, i) => {
        const tone = !e.done ? 'neutral' : e.tone === 'deny' ? 'deny' : e.tone === 'allow' ? 'allow' : 'verify';
        const last = i === events.length - 1;
        return (
          <li key={e.label} className="relative flex gap-3.5 pb-5 last:pb-0">
            {!last && (
              <span
                className={`absolute top-3.5 left-[5px] h-full w-px ${
                  e.done ? 'bg-line-hi' : 'bg-line'
                }`}
              />
            )}
            <span
              className={`relative z-10 mt-1 size-2.5 shrink-0 rounded-full ring-4 ring-ink-850 ${
                e.done ? toneBg[tone] : 'bg-ink-750 outline outline-line'
              }`}
            />
            <div className="-mt-0.5 flex min-w-0 flex-1 items-baseline justify-between gap-3">
              <span
                className={`text-[13px] ${
                  e.done ? (e.tone === 'deny' ? toneText['deny'] : 'text-fg') : 'text-fg-faint'
                }`}
              >
                {e.label}
              </span>
              <span className="mono shrink-0 text-[10px] text-fg-mute">{e.at}</span>
            </div>
          </li>
        );
      })}
    </ol>
  );
}
