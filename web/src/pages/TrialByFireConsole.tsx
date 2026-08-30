import { useState } from 'react';
import {
  Clock,
  KeyRound,
  LogOut,
  PlugZap,
  RefreshCcw,
  ScrollText,
  ShieldOff,
  Siren,
  TrendingDown,
  Wallet,
} from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, Button, EmptyNotice, Panel } from '../components/ui.tsx';
import { LiveFooter } from '../components/LiveFooter.tsx';
import { formatDateTime } from '../utils/format.ts';

/**
 * Everything a judge can do without the team touching anything.
 *
 * The commands are split by *what proves them*, because that separation is the system's
 * central claim. Holder-signed commands move money and are signed in this browser;
 * operator commands run the instance and deliberately cannot move money. A console that
 * mixed them into one list of buttons would hide the one thing worth showing.
 */
export function TrialByFireConsole() {
  const {
    mandates,
    selectedMandateId,
    walletReady,
    operatorAvailable,
    operatorSessionExpiresAt,
    operatorJournal,
    receipts,
    changeLimit,
    revokeSelected,
    revokeEverything,
    setPspMode,
    reconcile,
    advanceClock,
    offers,
    repriceOffer,
    openOperatorSession,
    closeOperatorSession,
    loadOperatorJournal,
    rogueCharge,
  } = useAval();

  const [newLimit, setNewLimit] = useState('100');
  const [hours, setHours] = useState('24');
  const [sku, setSku] = useState('');
  const [newPrice, setNewPrice] = useState('90');
  // Held for exactly as long as it takes to press the button: never in state that
  // outlives the exchange, never in storage, and never sent anywhere but the exchange.
  const [operatorToken, setOperatorToken] = useState('');
  const [rogueAmount, setRogueAmount] = useState('90');
  const [busy, setBusy] = useState(false);
  const selected = mandates.find((item) => item.mandate_id === selectedMandateId) ?? null;
  const chosenSku = sku || offers[0]?.item.sku || '';

  function fire(action: () => Promise<void>) {
    setBusy(true);
    void action().finally(() => setBusy(false));
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Trial-by-fire console</p>
          <h1>Change whatever you like. The core re-reads all of it on the next decision.</h1>
          <p>
            No cache sits in front of a limit or a revocation, and nothing needs
            restarting. The effect shows up on the next purchase the agent attempts.
          </p>
        </div>
        <Badge tone={selected ? 'allow' : 'neutral'}>{selected?.mandate_id ?? 'NO MANDATE'}</Badge>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel
          eyebrow="Proved by the holder key"
          title="Spending authority"
          action={<KeyRound size={18} className="text-allow" aria-hidden="true" />}
        >
          <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
            Signed by this wallet, in the browser. No operator token can produce these
            signatures — that is what stops whoever runs the instance from spending other
            people's money.
          </p>
          <label className="block">
            <span className="eyebrow">New budget (USD)</span>
            <input className="form-control" value={newLimit} onChange={(event) => setNewLimit(event.target.value)} />
          </label>
          <div className="mt-3 space-y-2">
            <Button
              className="w-full"
              disabled={busy || !selected || !walletReady}
              onClick={() => fire(() => changeLimit(Math.round(Number(newLimit) * 100)))}
            >
              <Wallet size={13} aria-hidden="true" />Change the limit (signed)
            </Button>
            <Button
              variant="danger"
              className="w-full"
              disabled={busy || !selected || !walletReady}
              onClick={() => fire(revokeSelected)}
            >
              <ShieldOff size={13} aria-hidden="true" />Revoke the mandate (signed)
            </Button>
            <Button
              variant="danger"
              className="w-full"
              disabled={busy || !walletReady || mandates.length === 0}
              onClick={() => fire(revokeEverything)}
            >
              <ShieldOff size={13} aria-hidden="true" />Revoke everything (signed)
            </Button>
          </div>
        </Panel>

        <Panel
          eyebrow="Proved by the operator token"
          title="Running the instance"
          action={<PlugZap size={18} className="text-hold" aria-hidden="true" />}
        >
          {!operatorAvailable ? (
            <>
              {/* The token is typed here and exchanged for a session. It used to be
                  built into the bundle, which published it: anyone who opened devtools
                  on this page kept the processor switch forever. */}
              <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
                No operator session is open in this tab. Present the token once — what
                stays on the page is a short-lived credential that expires on its own.
              </p>
              <label className="block">
                <span className="eyebrow">Operator token</span>
                <input
                  className="form-control"
                  type="password"
                  autoComplete="off"
                  value={operatorToken}
                  onChange={(event) => setOperatorToken(event.target.value)}
                />
              </label>
              <Button
                variant="ghost"
                className="mt-2 w-full"
                disabled={busy || operatorToken.length === 0}
                onClick={() =>
                  fire(async () => {
                    await openOperatorSession(operatorToken);
                    setOperatorToken('');
                  })
                }
              >
                <KeyRound size={13} aria-hidden="true" />Open an operator session
              </Button>
              <p className="safe-note mt-4">
                <ShieldOff size={15} aria-hidden="true" />
                Nothing here moves money. Raising a limit and approving an escalation
                still require the holder key, which this session does not have and cannot
                obtain.
              </p>
            </>
          ) : (
            <>
              <p className="mb-2 text-[13px] leading-relaxed text-fg-mute">
                These surfaces run the instance and, deliberately, touch no money at
                all.
              </p>
              <p className="mb-4 flex flex-wrap items-center gap-2">
                <Badge tone="hold">session until {operatorSessionExpiresAt ?? '—'}</Badge>
                <Button variant="ghost" disabled={busy} onClick={() => fire(closeOperatorSession)}>
                  <LogOut size={13} aria-hidden="true" />End the session
                </Button>
              </p>
              <div className="grid gap-2 sm:grid-cols-3">
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('offline'))}>Processor offline</Button>
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('decline'))}>Processor declines</Button>
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('online'))}>Processor online</Button>
              </div>
              <Button variant="ghost" className="mt-2 w-full" disabled={busy} onClick={() => fire(reconcile)}>
                <RefreshCcw size={13} aria-hidden="true" />Reconcile what is pending
              </Button>
              <label className="mt-4 block">
                <span className="eyebrow">Advance the clock (hours)</span>
                <input className="form-control" value={hours} onChange={(event) => setHours(event.target.value)} />
              </label>
              <Button
                variant="ghost"
                className="mt-2 w-full"
                disabled={busy}
                onClick={() => fire(() => advanceClock(Math.round(Number(hours) * 3600)))}
              >
                <Clock size={13} aria-hidden="true" />Advance it and watch things expire
              </Button>
              {/* The control that ends a standing order's waiting. It sits here, and
                  not with the holder commands, because moving a price authorizes
                  nothing: the watch it wakes faces the same mandate as ever. */}
              <label className="mt-4 block">
                <span className="eyebrow">Drop the price of</span>
                <select
                  className="form-control"
                  value={chosenSku}
                  onChange={(event) => setSku(event.target.value)}
                  disabled={offers.length === 0}
                >
                  {offers.map((offer) => (
                    <option key={offer.offer_id} value={offer.item.sku}>
                      {offer.item.title} · {offer.total.minor_units / 100} {offer.total.currency}
                    </option>
                  ))}
                </select>
              </label>
              <label className="mt-2 block">
                <span className="eyebrow">New price (USD)</span>
                <input
                  className="form-control"
                  value={newPrice}
                  onChange={(event) => setNewPrice(event.target.value)}
                />
              </label>
              <Button
                variant="ghost"
                className="mt-2 w-full"
                disabled={busy || !chosenSku}
                onClick={() => fire(() => repriceOffer(chosenSku, Math.round(Number(newPrice) * 100)))}
              >
                <TrendingDown size={13} aria-hidden="true" />The price dropped — now what?
              </Button>
              {/* The agent that goes around AVAL entirely: it charges the card and
                  never asks the mandate. It is the only way to produce money this layer
                  cannot justify holding — and therefore the only way to watch the
                  verdict give it back. Mounted only with AVAL_DEMO_ROGUE. */}
              <label className="mt-4 block">
                <span className="eyebrow">Charge that bypasses the core (USD)</span>
                <input
                  className="form-control"
                  value={rogueAmount}
                  onChange={(event) => setRogueAmount(event.target.value)}
                />
              </label>
              <Button
                variant="danger"
                className="mt-2 w-full"
                disabled={busy || !selected}
                onClick={() => fire(() => rogueCharge(Math.round(Number(rogueAmount) * 100)))}
              >
                <Siren size={13} aria-hidden="true" />Charge without consulting the mandate
              </Button>
              <Button
                variant="ghost"
                className="mt-2 w-full"
                disabled={busy}
                onClick={() => fire(loadOperatorJournal)}
              >
                <ScrollText size={13} aria-hidden="true" />Read the operator journal
              </Button>
              <p className="safe-note mt-4">
                <Clock size={15} aria-hidden="true" />
                The clock only moves forward. Rewinding it would revive an expired
                mandate, and that would be an operator handing spending authority back.
              </p>
            </>
          )}
        </Panel>
      </section>

      {operatorJournal && (
        <Panel
          eyebrow="The other half of the symmetry"
          title={`Operator journal — ${operatorJournal.entries.length} act(s)`}
          action={
            <Badge tone={operatorJournal.chain.intact ? 'verify' : 'deny'}>
              {operatorJournal.chain.intact
                ? 'CHAIN INTACT'
                : `BROKEN AT ${operatorJournal.chain.broken_at}`}
            </Badge>
          }
        >
          {operatorJournal.entries.length === 0 ? (
            <EmptyNotice
              title="Nothing has been operated yet"
              body="Writes land here; reads do not, because reading is not an act of operation."
            />
          ) : (
            <ul className="space-y-2">
              {operatorJournal.entries
                .slice()
                .reverse()
                .map((entry) => (
                  <li
                    key={entry.sequence}
                    className="rounded-lg border border-line bg-ink-800/40 p-3"
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="mono text-[11px] text-hold">{entry.action}</span>
                      <span className="mono text-[10px] text-fg-mute">
                        {formatDateTime(entry.occurred_at)}
                      </span>
                    </div>
                    <p className="mono mt-1 text-[11px] text-fg-mute">{entry.actor}</p>
                  </li>
                ))}
            </ul>
          )}
          <p className="safe-note mt-4">
            <ScrollText size={15} aria-hidden="true" />
            The holder signs to spend; nobody signs to operate. The chain takes the
            signature's place: it does not prove who typed, and it does prove nothing was
            removed afterwards.
          </p>
        </Panel>
      )}

      <Panel eyebrow="What the runtime answered" title="Receipts from this session">
        {receipts.length === 0 ? (
          <EmptyNotice
            title="No commands yet"
            body="Every command records here what the runtime answered — including when it answered nothing at all."
          />
        ) : (
          <ul className="space-y-2">
            {receipts.map((receipt, index) => (
              <li
                key={index}
                className={`rounded-lg border p-3 ${
                  receipt.outcome === 'accepted'
                    ? 'border-allow/35 bg-allow/6'
                    : receipt.outcome === 'unreachable'
                      ? 'border-hold/40 bg-hold/6'
                      : 'border-deny/35 bg-deny/6'
                }`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13px] font-semibold">{receipt.label}</span>
                  <Badge tone={receipt.outcome === 'accepted' ? 'allow' : receipt.outcome === 'unreachable' ? 'hold' : 'deny'}>
                    {receipt.reasonCode ?? receipt.outcome}
                  </Badge>
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-fg-dim">{receipt.message}</p>
                <p className="mono mt-1 text-[10px] text-fg-faint">{formatDateTime(receipt.at)}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <LiveFooter />
    </div>
  );
}
