import { useAval } from '../state/AvalContext.ts';
import { formatMoney } from '../utils/format.ts';

/**
 * The four numbers the pitch asserts, read live while a judge attacks the system.
 *
 * They are aggregates of the same hash-chained trail the auditor tab reads, fetched
 * from the runtime rather than counted here. A page that added them up from whatever
 * it happened to have loaded could disagree with the auditor tab standing next to it,
 * and then neither would be evidence.
 *
 * `gasto autorizado fora do mandato` is the product metric: money held or settled with
 * no authorization proof bound to it. It is the same condition a dispute resolves as
 * AGENT_OVERREACH, so the footer and the arbitration cannot tell two different stories.
 */
export function LiveFooter() {
  const { metrics } = useAval();
  if (!metrics) return null;

  // The route a judge presses, falling back to the machine lane when only that ran.
  const decided = metrics.latency_ms?.agent_purchase?.count
    ? metrics.latency_ms.agent_purchase
    : metrics.latency_ms?.authorize;
  const refusedAtEdge = Object.values(metrics.edge_refusals ?? {}).reduce(
    (total, count) => total + count,
    0,
  );

  return (
    <footer className="live-footer" aria-label="Métricas ao vivo da instância">
      <Reading
        label="decisões"
        value={`${metrics.decisions.authorized} allow · ${metrics.decisions.awaiting_human} escalate · ${metrics.decisions.rejected} deny`}
      />
      <Reading
        label="p99 da decisão"
        value={decided?.count ? `${decided.p99.toFixed(1)} ms` : '—'}
      />
      <Reading label="recusados na borda" value={String(refusedAtEdge)} />
      <Reading
        label="gasto autorizado fora do mandato"
        value={formatMoney({
          minorUnits: metrics.spend_outside_mandate.minor_units,
          currency: metrics.spend_outside_mandate.currency,
          scale: metrics.spend_outside_mandate.scale,
        })}
        tone={metrics.spend_outside_mandate.minor_units === 0 ? 'allow' : 'deny'}
      />
    </footer>
  );
}

function Reading({
  label,
  value,
  tone = 'neutral',
}: {
  label: string;
  value: string;
  tone?: 'neutral' | 'allow' | 'deny';
}) {
  return (
    <div className="live-footer-reading">
      <span className="live-footer-label">{label}</span>
      <span className={`live-footer-value live-footer-${tone}`}>{value}</span>
    </div>
  );
}
