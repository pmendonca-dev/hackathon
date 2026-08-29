import { ShieldCheck } from 'lucide-react';
import { useStore } from '../domain/store';
import { Page, TopBar } from '../components/Shell';
import { Badge, Panel, toneFor, toneBg } from '../components/ui';

export function Ledger() {
  const { state } = useStore();
  const events = [...state.ledger].reverse();

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Ledger']}
        title="Authorization Ledger"
        subtitle="Append-only record of every authority decision and money movement"
        action={
          <div className="flex items-center gap-2.5 rounded-lg border border-verify/25 bg-verify/[0.05] px-3.5 py-2">
            <ShieldCheck size={14} className="text-verify" />
            <div className="leading-tight">
              <div className="eyebrow">Ledger integrity</div>
              <div className="mono text-[11px] font-semibold text-verify">VERIFIED</div>
            </div>
          </div>
        }
      />
      <Page>
        <Panel eyebrow={`${events.length} events`} title="Event stream" bodyClass="p-0">
          <ol className="relative">
            {events.map((e, i) => {
              const tone = toneFor(e.status);
              return (
                <li
                  key={e.id}
                  className="relative flex flex-wrap items-center gap-x-5 gap-y-2 border-b border-line/60 px-5 py-3.5 transition-colors last:border-0 hover:bg-white/[0.015]"
                >
                  {/* Spine connecting the events, drawn only between rows. */}
                  {i < events.length - 1 && (
                    <span className="absolute top-1/2 bottom-0 left-[26px] w-px bg-line" />
                  )}
                  <span className="absolute top-1/2 left-0 h-1/2 w-px bg-line first:hidden" />

                  <span
                    className={`relative z-10 size-2 shrink-0 rounded-full ring-4 ring-ink-850 ${toneBg[tone]}`}
                    style={{ marginLeft: '18px' }}
                  />

                  <span className="mono w-[64px] shrink-0 text-[11px] text-fg-mute">{e.time}</span>

                  <span className="mono min-w-[190px] flex-1 text-[12px] font-medium text-fg">
                    {e.type}
                  </span>

                  <span className="min-w-[92px] text-[12px] text-fg-dim">{e.actor}</span>

                  <span className="mono min-w-[120px] truncate text-[11px] text-fg-mute">
                    {e.txId}
                  </span>

                  <span className="mono min-w-[70px] text-[11px] text-fg-faint">{e.hash}</span>

                  <Badge tone={tone} size="sm">
                    {e.status}
                  </Badge>
                </li>
              );
            })}
          </ol>
        </Panel>

        <p className="mt-4 max-w-2xl text-[12px] leading-relaxed text-fg-mute">
          Every row is written inside the same transaction as the state change it describes, so the
          ledger cannot drift from reality. A dispute is settled by replaying this list, not by
          asking anyone what they remember.
        </p>
      </Page>
    </>
  );
}
