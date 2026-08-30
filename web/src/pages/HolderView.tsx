import { useMemo, useState, type FormEvent } from 'react';
import { Clock, Eye, Gavel, KeyRound, Scale, Send, ShieldOff, Sparkles } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { AttackScenarios } from '../components/AttackScenarios.tsx';
import { AuthorityAtlas } from '../components/AuthorityAtlas.tsx';
import { EvaluationLadder } from '../components/EvaluationLadder.tsx';
import { Badge, Button, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, formatMoney } from '../utils/format.ts';

const MONTH_SECONDS = 30 * 24 * 3600;

/**
 * A default validity dated from the runtime, never from this laptop.
 *
 * The demo clock only moves forward, and a judge is invited to move it. A form that
 * dated itself here would then propose an instant the server has already passed, and
 * every mandate created after that trial-by-fire step would be refused as expired —
 * a failure the judge caused without being able to see why.
 */
function defaultExpiry(serverNow: string | null): string {
  const base = serverNow ? new Date(serverNow) : new Date();
  const valid = new Date(base.getTime() + MONTH_SECONDS * 1000);
  return `${valid.toISOString().slice(0, 19)}Z`;
}

export function HolderView() {
  const {
    mandates,
    selectedMandateId,
    selectMandate,
    escalations,
    lastRun,
    chain,
    humanEntries,
    holderKid,
    walletReady,
    watches,
    disputes,
    serverNow,
    createMandate,
    disputePurchase,
    resolveDispute,
    runAgent,
    watchInstruction,
    tickWatches,
    decideEscalation,
    revokeSelected,
    revokeEverything,
  } = useAval();

  const [instruction, setInstruction] = useState('buy a nonstop flight to Córdoba under $150');
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const selected = mandates.find((item) => item.mandate_id === selectedMandateId) ?? null;
  const expiryDefault = useMemo(() => defaultExpiry(serverNow), [serverNow]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Holder view</p>
          <h1>A purchase only finds a route inside the authority I granted.</h1>
          <p>
            The key that moves a limit, a revocation or an approval is born in this
            browser. AVAL shows the route the decision took, but it is the deterministic
            core that lets each step through or stops it.
          </p>
        </div>
        <Badge tone={walletReady ? 'verify' : 'escalate'}>
          {walletReady ? 'WALLET READY' : 'NO WALLET'}
        </Badge>
      </header>

      {!walletReady && (
        <div role="alert" className="rounded-2xl border border-escalate/40 bg-escalate/8 p-4 text-[13px] leading-relaxed text-escalate">
          The holder wallet has not opened in this browser yet. Without it nothing that
          moves spending authority can be signed — and nothing will be faked.
        </div>
      )}

      <AuthorityAtlas mandate={selected} lastRun={lastRun} chain={chain} />

      <AttackScenarios
        mandate={selected}
        busy={busy}
        onRun={async (nextInstruction) => {
          setInstruction(nextInstruction);
          await guard(() => runAgent(nextInstruction));
        }}
      />

      <section className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <Panel
          eyebrow="My mandates"
          title={`${mandates.length} active`}
          action={
            <Button variant="ghost" onClick={() => setShowCreate((open) => !open)}>
              <Sparkles size={13} aria-hidden="true" />
              {showCreate ? 'Close' : 'Create mandate'}
            </Button>
          }
        >
          {showCreate && (
            <CreateMandateForm
              onSubmit={createMandate}
              onDone={() => setShowCreate(false)}
              defaultExpiresAt={expiryDefault}
            />
          )}
          {mandates.length === 0 ? (
            <EmptyNotice
              title="No mandates yet"
              body="Create the first mandate so the agent has some authority — and only that."
            />
          ) : (
            <ul className="space-y-2">
              {mandates.map((mandate) => {
                const active = mandate.mandate_id === selectedMandateId;
                const revoked = mandate.status !== 'ACTIVE';
                return (
                  <li key={mandate.mandate_id}>
                    <button
                      type="button"
                      onClick={() => selectMandate(mandate.mandate_id)}
                      aria-current={active ? 'true' : undefined}
                      className={`w-full rounded-xl border p-3.5 text-left transition-colors ${
                        active ? 'border-allow/50 bg-allow/8' : 'border-line bg-ink-800/50 hover:border-line-hi'
                      }`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="mono truncate text-[11px] text-fg-mute">{mandate.mandate_id}</span>
                        <Badge tone={revoked ? 'deny' : 'allow'}>{mandate.status}</Badge>
                      </span>
                      <span className="mt-2 block text-[13px]">
                        {formatMoney(toMoney(mandate.remaining))} of {formatMoney(toMoney(mandate.limit))} left
                      </span>
                      <span className="mono mt-1 block text-[11px] text-fg-mute">
                        {mandate.allowed_categories.join(', ')} · {mandate.allowed_merchant_ids.join(', ')}
                        {mandate.usage_limit
                          ? ` · ${mandate.uses_in_window}/${mandate.usage_limit.max_uses} uses`
                          : ''}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel eyebrow="The buying agent" title="Write whatever you like. The decision stays with the core." action={<Send size={18} className="text-allow" aria-hidden="true" />}>
          <form
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              void guard(() => runAgent(instruction));
            }}
            className="space-y-3"
          >
            <label className="block">
              <span className="eyebrow">Instruction</span>
              <input
                className="form-control"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                required
                disabled={!selected || busy}
              />
            </label>
            <Button type="submit" disabled={!selected || busy || !instruction.trim()}>
              {busy ? 'Running' : 'Ask the agent'}
            </Button>
          </form>

          {lastRun && (
            <div className="mt-5 border-t border-line pt-5">
              <div className="flex items-center justify-between gap-3">
                <p className="eyebrow">Outcome</p>
                <Badge tone={lastRun.outcome === 'settled' ? 'allow' : lastRun.escalation_id ? 'escalate' : 'deny'}>
                  {lastRun.reason_code}
                </Badge>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed">{lastRun.human_summary}</p>
              <div className="mt-4">
                <p className="eyebrow mb-2">How the core got there</p>
                <EvaluationLadder trace={lastRun.evaluation_trace} />
              </div>

              {/* Nothing matching is not a dead end — but turning it into a live
                  standing order is the buyer's call, never the agent's. Opening one
                  silently would be approving a future purchase nobody asked for. */}
              {lastRun.outcome === 'no_offer' && (
                <div className="mt-4 rounded-xl border border-hold/35 bg-hold/6 p-3.5">
                  <p className="text-[13px] leading-relaxed">
                    Nothing in the catalogue matches right now. The agent can keep trying
                    on its own — the watch runs against this very mandate.
                  </p>
                  <Button
                    variant="ghost"
                    className="mt-3"
                    disabled={busy || !selected}
                    onClick={() => void guard(() => watchInstruction(instruction))}
                  >
                    <Eye size={13} aria-hidden="true" />
                    Leave the agent watching
                  </Button>
                </div>
              )}
            </div>
          )}
        </Panel>
      </section>

      <Panel eyebrow="Waiting on me" title={`${escalations.length} approval(s) pending`}>
        {escalations.length === 0 ? (
          <EmptyNotice
            title="Nothing waiting on a decision"
            body="Purchases outside the mandate appear here with both buttons — they are never approved silently."
          />
        ) : (
          <ul className="space-y-3">
            {escalations.map((escalation) => (
              <li key={escalation.id} className="rounded-xl border border-escalate/35 bg-escalate/6 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="mono text-[11px] text-fg-mute">{escalation.id}</span>
                  <Badge tone="escalate">{escalation.reason_code}</Badge>
                </div>
                <p className="mt-2 text-[13px]">
                  {formatMoney(toMoney(escalation.amount))} at {escalation.merchant_id} · {escalation.category}
                </p>
                <div className="mt-3 flex gap-2">
                  <Button disabled={busy || !walletReady} onClick={() => void guard(() => decideEscalation(escalation.id, 'approve'))}>
                    Approve by signing
                  </Button>
                  <Button variant="danger" disabled={busy || !walletReady} onClick={() => void guard(() => decideEscalation(escalation.id, 'deny'))}>
                    Refuse
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        eyebrow="Standing orders"
        title={`${watches.length} watch(es)`}
        action={
          <Button
            variant="ghost"
            disabled={busy || watches.length === 0}
            onClick={() => void guard(tickWatches)}
          >
            <Clock size={13} aria-hidden="true" />
            Try them now
          </Button>
        }
      >
        {watches.length === 0 ? (
          <EmptyNotice
            title="No open watches"
            body="When the agent finds no offer, it offers to keep looking. This is the one part of the system where the buyer is not a person pressing pay."
          />
        ) : (
          <ul className="space-y-2">
            {watches.map((watch) => (
              <li key={watch.watch_id} className="rounded-xl border border-line bg-ink-800/40 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="mono text-[11px] text-fg-mute">{watch.watch_id}</span>
                  <Badge tone={watchTone(watch)}>{watch.outcome ?? watch.status}</Badge>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed">{watch.instruction}</p>
                <p className="mono mt-1 text-[11px] text-fg-mute">
                  until {formatDateTime(watch.expires_at)}
                  {watch.settlement_reference ? ` · ${watch.settlement_reference}` : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="safe-note mt-4">
          <Eye size={15} aria-hidden="true" />
          The autonomy is in <em>when</em> the agent acts, never in <em>what</em> it may
          do: firing calls the same mandate as always, so a watch against a revoked
          mandate is refused in exactly the same way.
        </p>
      </Panel>

      <section className="grid gap-4 lg:grid-cols-[1.3fr_0.7fr]">
        <Panel eyebrow="My record" title="What was bought, under which mandate">
          {humanEntries.length === 0 ? (
            <EmptyNotice title="Empty trail" body="Every decision the core makes appears here as it happens." />
          ) : (
            <ul className="space-y-2">
              {humanEntries.slice().reverse().map((entry, index) => (
                <li key={index} className="rounded-lg border border-line bg-ink-800/40 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                    <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                  <PaymentState entry={entry} />
                  <DenyPurchase
                    entry={entry}
                    disputes={disputes}
                    busy={busy}
                    onDeny={(reservationId) =>
                      void guard(() =>
                        disputePurchase(reservationId, 'The holder does not recognise this purchase.'),
                      )
                    }
                  />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          eyebrow="Disputes"
          title="Who answers for this purchase"
          action={<Scale size={18} className="text-hold" aria-hidden="true" />}
        >
          {disputes.length === 0 ? (
            <EmptyNotice
              title="No purchase disputed"
              body="Every settled purchase carries a button to deny it. The trail decides the rest."
            />
          ) : (
            <ul className="space-y-2">
              {disputes.map((dispute) => (
                <li key={dispute.id} className="rounded-lg border border-line bg-ink-800/40 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="mono text-[11px] text-hold">{dispute.reservation_id}</span>
                    <Badge tone={dispute.status === 'OPEN' ? 'hold' : 'verify'}>
                      {dispute.status}
                    </Badge>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{dispute.reason}</p>
                  {dispute.resolution && (
                    <p className="mt-1 text-[12px] text-fg-mute">{dispute.resolution}</p>
                  )}
                  {dispute.status === 'OPEN' ? (
                    <Button
                      className="mt-3"
                      disabled={busy}
                      onClick={() => void guard(() => resolveDispute(dispute.id))}
                    >
                      <Gavel size={13} aria-hidden="true" />Resolve from the trail
                    </Button>
                  ) : (
                    <p className="mt-2">
                      <Badge tone={dispute.liability.liable_party === 'holder' ? 'deny' : 'allow'}>
                        {dispute.liability.verdict} · answers for it: {dispute.liability.liable_party}
                      </Badge>
                    </p>
                  )}
                </li>
              ))}
            </ul>
          )}
          <p className="safe-note mt-4">
            <Scale size={15} aria-hidden="true" />
            Denying does not refund by itself: the verdict does. When the trail does not
            support the charge, the money comes back and the budget comes back with it;
            when it does, the receipt names exactly which proof holds it up.
          </p>
        </Panel>

        <Panel eyebrow="Shut it down" title="Withdraw authority" action={<ShieldOff size={18} className="text-deny" aria-hidden="true" />}>
          <dl>
            <Field label="Holder key">{holderKid ?? 'unavailable'}</Field>
            {selected && <Field label="Mandate">{selected.mandate_id}</Field>}
          </dl>
          <div className="mt-4 space-y-2">
            <Button variant="danger" className="w-full" disabled={!selected || busy || !walletReady} onClick={() => void guard(revokeSelected)}>
              <KeyRound size={13} aria-hidden="true" />Revoke this mandate
            </Button>
            <Button variant="danger" className="w-full" disabled={busy || !walletReady || mandates.length === 0} onClick={() => void guard(revokeEverything)}>
              <ShieldOff size={13} aria-hidden="true" />Revoke everything under this key
            </Button>
          </div>
          <p className="safe-note mt-4">
            <KeyRound size={15} aria-hidden="true" />
            Both require a signature from this wallet. No operator token can produce one.
          </p>
        </Panel>
      </section>
    </div>
  );
}

/**
 * "I do not recognise this purchase", on the purchase itself.
 *
 * It only appears where it can mean something: a settled purchase, whose reservation
 * the person's own record names. Offering it beside a refusal would invite a dispute
 * about money nobody took, and a purchase already disputed shows its dispute instead of
 * a second button.
 */
function DenyPurchase({
  entry,
  disputes,
  busy,
  onDeny,
}: {
  entry: { [key: string]: unknown };
  disputes: Array<{ reservation_id: string }>;
  busy: boolean;
  onDeny(reservationId: string): void;
}) {
  const detail = (entry.detail ?? {}) as Record<string, unknown>;
  const reservationId = typeof detail.reservation_id === 'string' ? detail.reservation_id : null;
  const settled = detail.payment_state === 'settled';
  if (!reservationId || !settled) return null;
  if (disputes.some((dispute) => dispute.reservation_id === reservationId)) {
    return <p className="mt-2 text-[11px] text-fg-mute">Already disputed.</p>;
  }

  return (
    <Button variant="danger" className="mt-3" disabled={busy} onClick={() => onDeny(reservationId)}>
      <Gavel size={13} aria-hidden="true" />I do not recognise this purchase
    </Button>
  );
}

/**
 * Authorized, in confirmation, settled — never two states where there are three.
 *
 * The middle one is the honest reading of a processor that did not answer: the budget
 * is held and the outcome is unknown. Rounding it to "approved" would promise the buyer
 * a purchase that may not exist; rounding it to "declined" would tell them their money
 * is free when it is not. So the screen says what is true and says it is unfinished.
 */
function PaymentState({ entry }: { entry: { [key: string]: unknown } }) {
  const detail = (entry.detail ?? {}) as Record<string, unknown>;
  const state = typeof detail.payment_state === 'string' ? detail.payment_state : null;
  if (!state) return null;

  const reading = {
    settled: { tone: 'allow' as const, label: 'settled' },
    declined: { tone: 'deny' as const, label: 'declined by the processor' },
    in_doubt: { tone: 'hold' as const, label: 'payment in confirmation' },
  }[state];
  if (!reading) return null;

  return (
    <p className="mt-2">
      <Badge tone={reading.tone}>{reading.label}</Badge>
    </p>
  );
}

/**
 * Open is `hold`, not `allow`: a standing order has decided nothing yet, and painting
 * it green would read as a purchase that already happened.
 */
function watchTone(watch: { status: string; outcome: string | null }) {
  if (watch.outcome === 'settled') return 'allow' as const;
  if (watch.status === 'OPEN') return 'hold' as const;
  return watch.outcome ? ('deny' as const) : ('neutral' as const);
}

function toMoney(value: { minor_units: number; currency: string; scale: number }) {
  return { minorUnits: value.minor_units, currency: value.currency, scale: value.scale };
}

function CreateMandateForm({
  onSubmit,
  onDone,
  defaultExpiresAt,
}: {
  onSubmit: ReturnType<typeof useAval>['createMandate'];
  onDone(): void;
  defaultExpiresAt: string;
}) {
  const [limit, setLimit] = useState('200');
  const [ceiling, setCeiling] = useState('500');
  const [merchants, setMerchants] = useState('vuelaya');
  const [categories, setCategories] = useState('travel');
  const [maxUses, setMaxUses] = useState('');
  const [expiresAt, setExpiresAt] = useState(defaultExpiresAt);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="mb-5 space-y-3 rounded-xl border border-line bg-ink-800/50 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit({
          displayName: 'Holder',
          merchants: merchants.split(',').map((value) => value.trim()).filter(Boolean),
          categories: categories.split(',').map((value) => value.trim()).filter(Boolean),
          limit: { minor_units: Math.round(Number(limit) * 100), currency: 'USD', scale: 2 },
          ceiling: ceiling ? { minor_units: Math.round(Number(ceiling) * 100), currency: 'USD', scale: 2 } : null,
          expiresAt,
          usageLimit: maxUses ? { max_uses: Number(maxUses), window_seconds: MONTH_SECONDS } : null,
        })
          .then(onDone)
          .finally(() => setBusy(false));
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Budget (USD)</span>
          <input className="form-control" value={limit} onChange={(event) => setLimit(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Per-purchase ceiling (USD)</span>
          <input className="form-control" value={ceiling} onChange={(event) => setCeiling(event.target.value)} />
        </label>
        <label className="block">
          <span className="eyebrow">Merchants</span>
          <input className="form-control" value={merchants} onChange={(event) => setMerchants(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Categories</span>
          <input className="form-control" value={categories} onChange={(event) => setCategories(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Max purchases / month</span>
          <input className="form-control" value={maxUses} onChange={(event) => setMaxUses(event.target.value)} placeholder="no limit" />
        </label>
        <label className="block">
          <span className="eyebrow">Valid until</span>
          <input className="form-control" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required />
        </label>
      </div>
      <Button type="submit" disabled={busy}>{busy ? 'Creating' : 'Create a mandate signed by this wallet'}</Button>
    </form>
  );
}
