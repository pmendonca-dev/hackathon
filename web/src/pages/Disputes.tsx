import { Check, FileSearch } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import { Page, TopBar } from '../components/Shell';
import { Badge, Panel, toneFor } from '../components/ui';

export function Disputes() {
  const { state, go } = useStore();

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Disputes']}
        title="Disputes"
        subtitle="Verdicts reconstructed from evidence, not from recollection"
      />
      <Page>
        <div className="space-y-3">
          {state.disputes.map((d) => (
            <Panel
              key={d.id}
              eyebrow={`${d.id} · ${d.paymentId}`}
              title={`${d.merchant} — ${money(d.amount)}`}
              action={
                <Badge tone={toneFor(d.verdict)} dot>
                  {d.verdict === 'UPHELD' ? 'MERCHANT CLAIM REJECTED' : 'CHARGE UPHELD'}
                </Badge>
              }
            >
              <blockquote className="border-l-2 border-line pl-4 text-[13px] leading-relaxed text-fg-dim italic">
                {d.claim}
              </blockquote>

              <h3 className="eyebrow mt-5 mb-2.5">Evidence chain</h3>
              <ul className="space-y-2">
                {d.evidence.map((e) => (
                  <li key={e} className="flex gap-2.5">
                    <Check size={12} className="mt-1 shrink-0 text-verify" strokeWidth={3} />
                    <span className="text-[12px] leading-relaxed text-fg-dim">{e}</span>
                  </li>
                ))}
              </ul>

              <button
                onClick={() => go('ledger')}
                className="mono mt-5 flex items-center gap-1.5 text-[10px] tracking-wider text-fg-mute uppercase transition-colors hover:text-fg"
              >
                <FileSearch size={12} />
                Replay in ledger
              </button>
            </Panel>
          ))}
        </div>
      </Page>
    </>
  );
}
