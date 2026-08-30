import type { AuthorityRailProjection, Money, Tone } from '../contracts/avalGateway.ts';
import { formatMoney } from '../utils/format.ts';

const zoneStyle: Record<Tone, string> = {
  allow: 'bg-allow/15 text-allow',
  escalate: 'bg-escalate/15 text-escalate',
  deny: 'bg-deny/15 text-deny',
  verify: 'bg-verify/15 text-verify',
  hold: 'bg-hold/15 text-hold',
  neutral: 'bg-white/5 text-fg-mute',
};

const markerStyle: Record<Tone, string> = {
  allow: 'bg-allow text-ink-950',
  escalate: 'bg-escalate text-ink-950',
  deny: 'bg-deny text-ink-950',
  verify: 'bg-verify text-ink-950',
  hold: 'bg-hold text-ink-950',
  neutral: 'bg-fg-dim text-ink-950',
};

/** Draws a server-projected authority shape. It does not classify the amount. */
export function AuthorityRail({ projection, moneyTemplate }: { projection: AuthorityRailProjection; moneyTemplate: Money }) {
  const percent = (minorUnits: number) => `${(minorUnits / projection.maximumMinorUnits) * 100}%`;
  const markerMoney: Money = { ...moneyTemplate, minorUnits: projection.marker.atMinorUnits };

  return (
    <figure aria-labelledby="authority-rail-caption">
      <div className="relative pt-9">
        <div className="anim-marker absolute top-0 -translate-x-1/2" style={{ left: percent(projection.marker.atMinorUnits) }}>
          <span className={`mono whitespace-nowrap rounded px-2 py-1 text-[10px] font-bold ${markerStyle[projection.marker.tone]}`}>
            {projection.marker.label} · {formatMoney(markerMoney)}
          </span>
        </div>
        <div className="relative flex h-14 overflow-hidden rounded-xl border border-line-hi">
          {projection.zones.map((zone) => (
            <div
              key={zone.label}
              className={`flex min-w-0 items-center justify-center border-r border-line px-2 text-center last:border-r-0 ${zoneStyle[zone.tone]}`}
              style={{ width: percent(zone.toMinorUnits - zone.fromMinorUnits) }}
            >
              <span className="mono text-[9px] font-bold uppercase tracking-wider sm:text-[10px]">{zone.label}</span>
            </div>
          ))}
          <span className="pointer-events-none absolute inset-y-0 w-px bg-fg" style={{ left: percent(projection.marker.atMinorUnits) }} />
        </div>
      </div>
      <figcaption id="authority-rail-caption" className="mt-3 text-[12px] leading-relaxed text-fg-mute">
        Faixas e marcador vieram do snapshot do core. O browser apenas desenha esta projeção.
      </figcaption>
    </figure>
  );
}
