import { PlugZap, Unplug, Lock, Loader } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import type { Payment } from '../domain/types';
import { Page, TopBar } from '../components/Shell';
import { Badge, Button, Panel, StatusDot, toneFor } from '../components/ui';

export function Payments() {
  const { state, togglePsp } = useStore();
  const held = state.payments.filter(
    (p) => p.status === 'IN_DOUBT' || p.status === 'IN_CONFIRMATION',
  );

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Payments']}
        title="Payments"
        subtitle="Money in motion, and the state it is truly in"
      />
      <Page>
        {/* PSP control. A processor failure is a first-class state here, not an
            error banner, which is the entire point of the surface. */}
        <Panel
          eyebrow="Processor"
          title="PSP connection"
          action={
            <span
              className={`mono flex items-center gap-1.5 text-[10px] font-semibold ${
                state.pspOnline ? 'text-allow' : 'text-hold'
              }`}
            >
              <StatusDot tone={state.pspOnline ? 'allow' : 'hold'} pulse={!state.pspOnline} />
              {state.pspOnline ? 'ONLINE' : 'UNREACHABLE'}
            </span>
          }
        >
          <div className="flex flex-wrap items-center justify-between gap-4">
            <p className="max-w-md text-[13px] leading-relaxed text-fg-mute">
              A timeout is not a decline. When the processor goes quiet the budget stays reserved and
              delivery stays blocked until the ledger reconciles — never released, never refused.
            </p>
            {state.pspOnline ? (
              <Button variant="ghost" onClick={() => togglePsp(false)}>
                <Unplug size={13} />
                Simulate PSP offline
              </Button>
            ) : (
              <Button variant="primary" onClick={() => togglePsp(true)}>
                <PlugZap size={13} />
                Restore PSP
              </Button>
            )}
          </div>
        </Panel>

        {held.length > 0 && (
          <div className="mt-3 grid gap-3 md:grid-cols-2">
            {held.map((p) => (
              <InConfirmation
                key={p.id}
                payment={p}
                // Only a payment held by *this* outage reconciles when the
                // processor returns. A standing IN_DOUBT waits for its own cycle.
                reconciling={state.pspOnline && p.status === 'IN_CONFIRMATION'}
              />
            ))}
          </div>
        )}

        <Panel className="mt-3" bodyClass="" eyebrow="Ledger of record" title="All payments">
          <div className="overflow-x-auto">
            <table className="w-full min-w-[640px] text-left">
              <thead>
                <tr className="border-b border-line">
                  {['Payment', 'Agent', 'Merchant', 'Amount', 'Status'].map((h, i) => (
                    <th
                      key={h}
                      className={`eyebrow px-5 py-2.5 font-medium ${i === 3 ? 'text-right' : ''}`}
                    >
                      {h}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody className="divide-y divide-line/60">
                {state.payments.map((p) => {
                  const shown =
                    p.status === 'IN_CONFIRMATION' && state.pspOnline ? 'RECONCILING' : p.status;
                  return (
                    <tr key={p.id} className="transition-colors hover:bg-white/[0.015]">
                      <td className="mono px-5 py-3.5 text-[12px] text-fg">{p.id}</td>
                      <td className="px-5 py-3.5 text-[13px] text-fg-dim">{p.agent}</td>
                      <td className="px-5 py-3.5 text-[13px] text-fg-dim">{p.merchant}</td>
                      <td className="mono px-5 py-3.5 text-right text-[13px] text-fg">
                        {money(p.amount, p.currency)}
                      </td>
                      <td className="px-5 py-3.5">
                        <Badge tone={toneFor(shown)} dot>
                          {shown.replace(/_/g, ' ')}
                        </Badge>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        </Panel>
      </Page>
    </>
  );
}

function InConfirmation({ payment, reconciling }: { payment: Payment; reconciling: boolean }) {
  return (
    <section className="relative overflow-hidden rounded-xl border border-hold/30 bg-hold/[0.05] px-5 py-5">
      {reconciling && <span className="anim-sweep absolute inset-x-0 top-0 h-px overflow-hidden" />}
      <div className="flex items-center gap-2">
        {reconciling ? (
          <Loader size={13} className="animate-spin text-hold" />
        ) : (
          <Lock size={13} className="text-hold" />
        )}
        <h3 className="font-display text-[15px] font-semibold text-hold">
          {reconciling ? 'Reconciling…' : 'Payment in confirmation'}
        </h3>
      </div>
      <p className="mt-1.5 text-[13px] leading-relaxed text-fg-dim">
        {payment.note ?? 'The payment processor did not provide a definitive response.'}
      </p>
      <dl className="mono mt-4 space-y-2 border-t border-hold/20 pt-4 text-[11px]">
        <Row label="Reserved budget" value={money(payment.amount, payment.currency)} tone="text-hold" />
        <Row label="Merchant delivery" value="BLOCKED" tone="text-deny" />
        <Row
          label="Reconciliation"
          value={reconciling ? 'IN PROGRESS' : 'PENDING'}
          tone={reconciling ? 'text-verify' : 'text-fg-mute'}
        />
      </dl>
    </section>
  );
}

function Row({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="eyebrow">{label}</dt>
      <dd className={tone}>{value}</dd>
    </div>
  );
}
