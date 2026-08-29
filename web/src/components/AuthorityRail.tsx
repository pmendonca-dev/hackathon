import { money } from '../domain/policy';
import type { Mandate } from '../domain/types';

/**
 * The signature element of the product.
 *
 * A mandate is not a switch, it is a shape: a band the agent may act inside on
 * its own, a band where it must come back for a human, and a ceiling it can
 * never cross no matter who asks. The rail draws that shape to scale and drops
 * a marker where the current amount actually falls.
 *
 * It reappears on the overview, on the mandate, and on every decision, so the
 * same picture answers "was this allowed?" everywhere in the product.
 */
export function AuthorityRail({
  mandate,
  amount,
  size = 'md',
  showScale = true,
}: {
  mandate: Mandate;
  amount?: number;
  size?: 'sm' | 'md' | 'lg';
  showScale?: boolean;
}) {
  const { perTransaction: allow, monthlyLimit: ceiling, currency } = mandate;
  // Headroom past the ceiling so the deny band is a visible place, not an edge.
  const scale = ceiling * 1.35;
  const pct = (v: number) => `${Math.min(100, (v / scale) * 100)}%`;

  const height = size === 'lg' ? 'h-14' : size === 'md' ? 'h-10' : 'h-7';
  const markerPct = amount === undefined ? null : Math.min(95, (amount / scale) * 100);

  const zone =
    amount === undefined ? null : amount <= allow ? 'allow' : amount <= ceiling ? 'escalate' : 'deny';

  const bands = [
    { key: 'allow', label: 'ALLOW', from: 0, to: allow, idle: 'bg-allow/12 text-allow/70', live: 'bg-allow/18 text-allow', bar: 'bg-allow' },
    { key: 'escalate', label: 'ESCALATE', from: allow, to: ceiling, idle: 'bg-escalate/12 text-escalate/70', live: 'bg-escalate/18 text-escalate', bar: 'bg-escalate' },
    { key: 'deny', label: 'DENY', from: ceiling, to: scale, idle: 'bg-deny/12 text-deny/70', live: 'bg-deny/18 text-deny', bar: 'bg-deny' },
  ] as const;

  return (
    <div className="w-full">
      {markerPct !== null && (
        <div className="relative mb-1.5 h-5">
          <div
            className="anim-marker absolute top-0 -translate-x-1/2 whitespace-nowrap"
            style={{ left: `${markerPct}%` }}
          >
            <span
              className={`mono rounded px-1.5 py-0.5 text-[10px] font-bold ${
                zone === 'allow'
                  ? 'bg-allow text-ink-950'
                  : zone === 'escalate'
                    ? 'bg-escalate text-ink-950'
                    : 'bg-deny text-ink-950'
              }`}
            >
              {money(amount!, currency)}
            </span>
          </div>
        </div>
      )}

      <div className={`relative flex ${height} overflow-hidden rounded-lg border border-line`}>
        {bands.map((b) => {
          const width = `${((b.to - b.from) / scale) * 100}%`;
          const active = zone === b.key;
          return (
            <div
              key={b.key}
              className={`relative flex items-center justify-center border-r border-line/70 transition-all last:border-r-0 ${
                active ? b.live : b.idle
              } ${zone && !active ? 'opacity-45' : ''}`}
              style={{ width }}
            >
              {size !== 'sm' && (
                <span className="mono text-[10px] font-bold tracking-widest">{b.label}</span>
              )}
              {active && <span className={`absolute inset-x-0 bottom-0 h-[3px] ${b.bar}`} />}
            </div>
          );
        })}

        {markerPct !== null && (
          <div
            className="pointer-events-none absolute inset-y-0 w-px bg-fg"
            style={{ left: `${markerPct}%` }}
          />
        )}
      </div>

      {showScale && (
        <div className="mono relative mt-1.5 h-4 text-[10px] text-fg-mute">
          <span className="absolute left-0">0</span>
          <span className="absolute -translate-x-1/2" style={{ left: pct(allow) }}>
            {money(allow, currency)}
          </span>
          <span className="absolute -translate-x-1/2" style={{ left: pct(ceiling) }}>
            {money(ceiling, currency)}
          </span>
        </div>
      )}
    </div>
  );
}
