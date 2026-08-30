import { EyeOff, Store } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, EmptyNotice, Panel } from '../components/ui.tsx';
import { formatDateTime } from '../utils/format.ts';

/**
 * What the merchant is allowed to see — and, beside it, what it is not.
 *
 * The redaction list is served by the runtime rather than assembled here. A browser
 * that decided for itself which fields were hidden would be describing a privacy
 * property instead of showing one, and the two would drift the first time the
 * projection changed.
 */
export function MerchantDeskView() {
  const { merchantEntries, merchantRedactions, auditorEntries, mandates, selectedMandateId } = useAval();
  const merchantId =
    mandates.find((item) => item.mandate_id === selectedMandateId)?.allowed_merchant_ids[0] ?? '—';

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Merchant view · {merchantId}</p>
          <h1>I verified the purchase is legitimate without learning who bought.</h1>
          <p>
            The authorization proof binds checkout, merchant, amount, currency and terms —
            and omits the mandate and the buyer. Accepting does not require knowing either.
          </p>
        </div>
        <Badge tone="verify">NO BUYER IDENTITY</Badge>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="What I receive" title="The merchant projection" action={<Store size={18} className="text-verify" aria-hidden="true" />}>
          {merchantEntries.length === 0 ? (
            <EmptyNotice title="No sales yet" body="Purchases settled at this merchant appear here." />
          ) : (
            <ul className="space-y-2">
              {merchantEntries.slice().reverse().map((entry, index) => (
                <li key={index} className="rounded-lg border border-line bg-ink-800/40 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                    <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                  <PairwiseHandle entry={entry} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          eyebrow="What I am denied"
          title="Fields the projection withholds"
          action={<EyeOff size={18} className="text-escalate" aria-hidden="true" />}
        >
          {merchantRedactions.length === 0 ? (
            <EmptyNotice title="List unavailable" body="Load a mandate to see what the projection withholds." />
          ) : (
            <>
              <ul className="space-y-2">
                {merchantRedactions.map((field) => (
                  <li key={field} className="flex items-center gap-3 rounded-lg border border-dashed border-escalate/40 bg-escalate/5 px-3 py-2.5">
                    <EyeOff size={14} className="shrink-0 text-escalate" aria-hidden="true" />
                    <span className="mono text-[12px] text-escalate">{field}</span>
                  </li>
                ))}
              </ul>
              <p className="safe-note mt-4">
                <EyeOff size={15} aria-hidden="true" />
                This list is built by allowlist on the server: the projection names what the
                merchant receives, instead of trying to remember what to hide.
              </p>
            </>
          )}
        </Panel>
      </section>

      <Panel eyebrow="Privacy, demonstrated" title="The same event, for two audiences">
        <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
          On the left, what the auditor reads; on the right, what the merchant receives of
          the same event. The difference is not styling — it is what the projection refuses
          to hand over.
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-line bg-ink-800/40 p-4">
            <p className="eyebrow mb-2">Auditor · {auditorEntries.length} events</p>
            <pre className="mono max-h-72 overflow-auto text-[10.5px] leading-relaxed text-fg-dim">
              {JSON.stringify(auditorEntries.slice(-2), null, 2)}
            </pre>
          </div>
          <div className="rounded-xl border border-verify/30 bg-verify/5 p-4">
            <p className="eyebrow mb-2">Merchant · {merchantEntries.length} events</p>
            <pre className="mono max-h-72 overflow-auto text-[10.5px] leading-relaxed text-fg-dim">
              {JSON.stringify(merchantEntries.slice(-2), null, 2)}
            </pre>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/**
 * The only name this seller has for this buyer, and the only one it is allowed to have.
 *
 * `HMAC(secret, mandate | merchant)`: stable at this shop, so a returning customer is
 * recognisable, and different at every other shop, so two sellers comparing notes find
 * nothing in common. Before this the merchant had no buyer handle at all — correct, and
 * useless for the one thing a merchant legitimately wants.
 */
function PairwiseHandle({ entry }: { entry: { [key: string]: unknown } }) {
  const detail = (entry.detail ?? {}) as Record<string, unknown>;
  const handle = typeof detail.pairwise_id === 'string' ? detail.pairwise_id : null;
  if (!handle) return null;

  return (
    <p className="mono mt-2 text-[10px] text-fg-faint">
      buyer at this shop · {handle}
    </p>
  );
}
