import { useState } from 'react';
import { Link2, Link2Off, PenLine, Scale, ScrollText, Send, ShieldAlert } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, Button, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, shortHash } from '../utils/format.ts';

/**
 * The trail, and the demonstration that it catches its own editor.
 *
 * The tamper control is the point of this screen. A log everybody promises not to edit
 * proves nothing; this one is re-hashed on every read, so an edit is caught by the
 * chain rather than by anybody's word. The button is only offered when the runtime was
 * started with the demo flag — its absence is the normal state.
 */
export function AuditorTrailView() {
  const { auditorEntries, chain, disputes, selectedMandateId, tamperLedger, operatorAvailable, telegramActivity } =
    useAval();
  const [sequence, setSequence] = useState('1');
  const [busy, setBusy] = useState(false);

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Auditor view</p>
          <h1>The trail verifies itself, without trusting whoever keeps it.</h1>
          <p>
            Every event canonicalises itself and chains the digest of the one before it.
            Editing any line breaks its own digest and every link that follows.
          </p>
        </div>
        <Badge tone={chain?.intact === false ? 'deny' : 'verify'}>
          {chain === null ? 'NO CHAIN' : chain.intact ? 'CHAIN INTACT' : 'CHAIN BROKEN'}
        </Badge>
      </header>

      {chain?.intact === false && (
        <div role="alert" className="flex gap-3 rounded-2xl border border-deny/45 bg-deny/8 p-4 text-deny">
          <ShieldAlert className="mt-0.5 shrink-0" size={18} aria-hidden="true" />
          <p className="text-[13px] leading-relaxed">
            <strong>Tampering detected at position {chain.broken_at}.</strong> The stored
            record no longer matches the digest taken over it at the moment it was written.
            Nobody had to notice this — the verification is arithmetic.
          </p>
        </div>
      )}

      <Panel
        eyebrow="Telegram lane"
        title={
          telegramActivity === null
            ? 'The bot'
            : `${telegramActivity.events.length} decision(s) from ${telegramActivity.chats} chat(s)`
        }
        action={<Send size={18} className="text-verify" aria-hidden="true" />}
      >
        {telegramActivity === null ? (
          <EmptyNotice
            title="The bot is not reachable from here"
            body="This panel reads the core's own record of what the Telegram lane did. Nothing is being hidden — the runtime did not answer."
          />
        ) : telegramActivity.events.length === 0 ? (
          <EmptyNotice
            title="Nobody has typed yet"
            body="Whatever a judge does in the chat lands here, as the core recorded it."
          />
        ) : (
          <>
            <ol className="space-y-2">
              {telegramActivity.events.map((event, index) => (
                <li
                  key={`${event.digest ?? 'no-digest'}-${index}`}
                  className="rounded-lg border border-line bg-ink-800/40 p-3"
                >
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="flex items-center gap-2">
                      <span className="text-[13px] font-semibold">{event.who}</span>
                      <span className="mono text-[11px] text-verify">{event.event_type}</span>
                    </span>
                    <span className="mono text-[10px] text-fg-mute">{formatDateTime(event.at)}</span>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{event.summary}</p>
                  {event.digest !== null && (
                    <p className="mono mt-1 text-[10px] text-fg-faint">{shortHash(event.digest)}</p>
                  )}
                </li>
              ))}
            </ol>
            <p className="mt-3 text-[12px] leading-relaxed text-fg-mute">
              A first name and a decision, and deliberately nothing else: this feed carries
              no mandate, principal or chat id, so reading it can never become a way to look
              a buyer up. The digests are the same chain the panel below verifies.
            </p>
          </>
        )}
      </Panel>

      <section className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        <Panel eyebrow="Hash chain" title={`${auditorEntries.length} event(s)`} action={<ScrollText size={18} className="text-verify" aria-hidden="true" />}>
          {auditorEntries.length === 0 ? (
            <EmptyNotice title="Nothing recorded" body="Select a mandate with activity to read its trail." />
          ) : (
            <ol className="space-y-2">
              {auditorEntries.map((entry) => {
                const broken = chain?.broken_at !== null && chain?.broken_at === entry.sequence;
                return (
                  <li
                    key={String(entry.sequence)}
                    className={`rounded-lg border p-3 ${broken ? 'border-deny/50 bg-deny/8' : 'border-line bg-ink-800/40'}`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="flex items-center gap-2">
                        {broken ? (
                          <Link2Off size={13} className="text-deny" aria-hidden="true" />
                        ) : (
                          <Link2 size={13} className="text-verify" aria-hidden="true" />
                        )}
                        <span className="mono text-[11px] text-fg-mute">#{String(entry.sequence)}</span>
                        <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                      </span>
                      <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                    {typeof entry.sha256 === 'string' && (
                      <p className="mono mt-1 text-[10px] text-fg-faint">{shortHash(entry.sha256)}</p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel
            eyebrow="Arbitration"
            title="Who answers for it, derived from the trail"
            action={<Scale size={18} className="text-hold" aria-hidden="true" />}
          >
            {disputes.length === 0 ? (
              <EmptyNotice
                title="No disputes"
                body="When a purchase is denied, the verdict appears here with the lines that support it."
              />
            ) : (
              <ul className="space-y-3">
                {disputes.map((dispute) => (
                  <li key={dispute.id} className="rounded-xl border border-line bg-ink-850/70 p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="mono text-[11px] text-hold">{dispute.reservation_id}</span>
                      <Badge tone={dispute.liability.liable_party === 'holder' ? 'deny' : 'allow'}>
                        {dispute.liability.verdict}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[12px] text-fg-mute">
                      answers for it: {dispute.liability.liable_party}
                    </p>
                    {/* The verdict is not stored. It is recomputed from append-only
                        evidence on every read, and these are the exact lines it read —
                        a conclusion nobody has to take on faith. */}
                    <ul className="mt-2 space-y-1">
                      {dispute.liability.basis.map((line, index) => (
                        <li key={index} className="text-[12px] leading-relaxed text-fg-mute">
                          · {line}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge
                        tone={dispute.liability.mandate_repudiation === 'refuted' ? 'verify' : 'hold'}
                      >
                        repudiation: {dispute.liability.mandate_repudiation}
                      </Badge>
                      {dispute.liability.holder_signatures.map((signature) => (
                        <span key={signature.kid + signature.kind} className="mono text-[10px] text-fg-faint">
                          <PenLine size={11} aria-hidden="true" /> {signature.kind} · {signature.kid}
                        </span>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="safe-note mt-4">
              <Scale size={15} aria-hidden="true" />
              The mandate is born signed by the holder's key, and that signature is
              position 0 of this chain. It is what answers “I never created that mandate”
              without depending on anything the person did afterwards.
            </p>
          </Panel>

          <Panel eyebrow="Verification" title="Chain status">
            <dl>
              <Field label="Mandate">{selectedMandateId ?? '—'}</Field>
              <Field label="Links checked">{chain?.checked ?? 0}</Field>
              <Field label="Break at">{chain?.broken_at ?? 'none'}</Field>
            </dl>
          </Panel>

          <Panel eyebrow="Live proof" title="Break a link yourself">
            {!operatorAvailable ? (
              <p className="text-[13px] leading-relaxed text-fg-mute">
                Requires an operator token. Without one the command is never sent — and
                nothing is simulated locally.
              </p>
            ) : (
              <>
                <p className="mb-3 text-[13px] leading-relaxed text-fg-mute">
                  Rewrites an event's author and re-canonicalises it. The line stays
                  well formed; it is the digest that gives it away.
                </p>
                <label className="block">
                  <span className="eyebrow">Sequence</span>
                  <input className="form-control" value={sequence} onChange={(event) => setSequence(event.target.value)} />
                </label>
                <Button
                  variant="danger"
                  className="mt-3 w-full"
                  disabled={busy || !selectedMandateId}
                  onClick={() => {
                    setBusy(true);
                    void tamperLedger(Number(sequence)).finally(() => setBusy(false));
                  }}
                >
                  <ShieldAlert size={13} aria-hidden="true" />Tamper with the event
                </Button>
                <p className="safe-note mt-4">
                  <ShieldAlert size={15} aria-hidden="true" />
                  This route only exists when the runtime starts with AVAL_DEMO_TAMPER.
                  There is no counterpart that repairs the chain.
                </p>
              </>
            )}
          </Panel>
        </div>
      </section>
    </div>
  );
}
