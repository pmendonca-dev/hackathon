import { useEffect, useState } from 'react';
import { Bot, Ban, PenLine, Timer, ArrowRight } from 'lucide-react';
import { useStore } from '../domain/store';
import { buildChecks, evaluate, money } from '../domain/policy';
import { REASON_TEXT } from '../domain/types';
import type { Attempt, Mandate } from '../domain/types';
import { Page, TopBar } from '../components/Shell';
import { Badge, Button, Drawer, Field, Panel, StatusDot, toneFor, toneText } from '../components/ui';
import { AuthorityRail } from '../components/AuthorityRail';
import { CheckList, ProofSeal } from '../components/Verification';

export function AgentActivity() {
  const { state, openAttempt } = useStore();
  const open = state.attempts.find((a) => a.id === state.openAttemptId);

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Agent Activity']}
        title="Agent Activity"
        subtitle="Every purchase the agent attempted, and what the gate decided"
      />
      <Page>
        <Panel
          eyebrow="Agent"
          title="Travel Assistant"
          action={
            <span className="mono flex items-center gap-1.5 text-[10px] font-semibold text-allow">
              <StatusDot tone="allow" pulse />
              ONLINE
            </span>
          }
        >
          <div className="flex flex-wrap items-center gap-4">
            <span className="flex size-11 shrink-0 items-center justify-center rounded-xl border border-allow/25 bg-allow/8">
              <Bot size={18} className="text-allow" strokeWidth={1.75} />
            </span>
            <p className="min-w-[240px] flex-1 text-[13px] leading-relaxed text-fg-mute">
              Authorized to purchase travel within mandate limits. It holds a signing key, not a
              payment credential — it can ask for authority, never grant it to itself.
            </p>
          </div>
        </Panel>

        <h2 className="eyebrow mt-7 mb-3">Purchase attempts</h2>
        <ul className="space-y-2">
          {state.attempts.map((a) => (
            <AttemptRow key={a.id} attempt={a} onOpen={() => openAttempt(a.id)} />
          ))}
        </ul>
      </Page>

      <Drawer
        open={!!open}
        onClose={() => openAttempt(null)}
        eyebrow="Payment authorization"
        title={open ? `${open.item} — ${money(open.amount, open.currency)}` : ''}
        width="max-w-2xl"
      >
        {open && <DecisionPanel attempt={open} />}
      </Drawer>
    </>
  );
}

function AttemptRow({ attempt, onOpen }: { attempt: Attempt; onOpen: () => void }) {
  const tone = toneFor(attempt.decision);
  return (
    <li>
      <button
        onClick={onOpen}
        className="group flex w-full flex-wrap items-center gap-4 rounded-xl border border-line bg-ink-850 px-5 py-4 text-left transition-colors hover:border-line-hi hover:bg-ink-800"
      >
        <span className={`h-9 w-0.5 shrink-0 rounded-full ${
          tone === 'allow' ? 'bg-allow' : tone === 'escalate' ? 'bg-escalate' : 'bg-deny'
        }`} />
        <div className="min-w-[180px] flex-1">
          <div className="text-[14px] font-medium">
            {attempt.item}
            {attempt.route && <span className="text-fg-mute"> — {attempt.route}</span>}
          </div>
          <div className="mono mt-1 text-[10px] text-fg-faint">
            {attempt.merchant} · {attempt.agent}
          </div>
        </div>
        <div className="mono shrink-0 text-[15px] tracking-tight">
          {money(attempt.amount, attempt.currency)}
        </div>
        <Badge tone={tone} dot>
          {attempt.decision}
        </Badge>
        <span className="mono flex shrink-0 items-center gap-1 text-[10px] tracking-wider text-fg-faint uppercase transition-colors group-hover:text-fg-dim">
          View decision
          <ArrowRight size={11} className="transition-transform group-hover:translate-x-0.5" />
        </span>
      </button>
    </li>
  );
}

// ── The decision surface ────────────────────────────────────────────────────
function DecisionPanel({ attempt }: { attempt: Attempt }) {
  const { mandateOf, approve, capture, go, toast } = useStore();
  const mandate = mandateOf(attempt.mandateId);
  if (!mandate) return null;

  const result = evaluate(mandate, attempt.amount);
  const checks = buildChecks(mandate, result);
  const tone = toneFor(result.decision);

  return (
    <div className="space-y-6">
      {/* What was being bought */}
      <section className="rounded-xl border border-line bg-ink-850 px-5 py-1">
        <Field label="Merchant">{attempt.merchant}</Field>
        <Field label="Item">{attempt.route ?? attempt.item}</Field>
        <Field label="Amount">{money(attempt.amount, attempt.currency)}</Field>
        <Field label="Agent">{attempt.agent}</Field>
        <Field label="Mandate">{mandate.principal}</Field>
      </section>

      {/* The verdict */}
      <section
        className={`overflow-hidden rounded-xl border ${
          tone === 'allow'
            ? 'border-allow/30 bg-allow/[0.045]'
            : tone === 'escalate'
              ? 'border-escalate/30 bg-escalate/[0.05]'
              : 'border-deny/35 bg-deny/[0.05]'
        }`}
      >
        <div className="px-5 py-5">
          <div className="eyebrow">Authorization result</div>
          <div className="mt-2.5 flex flex-wrap items-end justify-between gap-4">
            <div className={`font-display text-[34px] leading-none font-bold tracking-tight ${toneText[tone]}`}>
              {result.decision}
            </div>
            <div className="mono text-[22px] leading-none tracking-tight text-fg">
              {money(attempt.amount, attempt.currency)}
            </div>
          </div>
        </div>
        <dl className="border-t border-current/12 px-5 py-1">
          <Field label="Reason" tone={tone}>
            {result.reason}
          </Field>
          <Field label="Policy">
            {mandate.category} / {mandate.destinations[1] ?? mandate.destinations[0]}
          </Field>
          <Field label="Decision handle">{attempt.decisionHandle}</Field>
          {result.decision !== 'DENY' && (
            <Field label="Expires in">
              <Countdown seconds={attempt.expiresIn} />
            </Field>
          )}
        </dl>
        <p className="border-t border-current/12 px-5 py-3.5 text-[12px] leading-relaxed text-fg-dim">
          {REASON_TEXT[result.reason]}
        </p>
      </section>

      {/* Where the amount actually sits */}
      <section>
        <h3 className="eyebrow mb-3">Position against mandate</h3>
        <AuthorityRail mandate={mandate} amount={attempt.amount} size="md" />
      </section>

      {/* Checks always run, in the same order, whatever the verdict */}
      <section>
        <h3 className="eyebrow mb-1">Verification</h3>
        <CheckList checks={checks} />
        <div className="mt-4">
          <ProofSeal decision={result.decision} />
        </div>
      </section>

      {/* What a human may do next — the whole point of the three bands */}
      {result.decision === 'ESCALATE' && (
        <EscalationActions attempt={attempt} mandate={mandate} onApprove={approve} onCapture={capture} />
      )}

      {result.decision === 'DENY' && (
        <DenyBlock
          reason={result.reason}
          onViewPolicy={() => {
            go('mandates');
            toast({ tone: 'verify', title: 'Policy opened', body: 'Bands are set on the mandate.' });
          }}
        />
      )}

      {result.decision === 'ALLOW' && attempt.captured && (
        <div className="flex items-center gap-2.5 rounded-lg border border-line bg-ink-850 px-4 py-3">
          <StatusDot tone="allow" />
          <span className="text-[12px] text-fg-dim">
            Captured and settled. Reservation committed under the mandate lock.
          </span>
        </div>
      )}
    </div>
  );
}

function EscalationActions({
  attempt,
  mandate,
  onApprove,
  onCapture,
}: {
  attempt: Attempt;
  mandate: Mandate;
  onApprove: (id: string) => void;
  onCapture: (id: string) => void;
}) {
  const approved = !!attempt.approvedBy;

  return (
    <section className="rounded-xl border border-escalate/30 bg-escalate/[0.045] px-5 py-5">
      <h3 className="font-display text-[15px] font-semibold text-escalate">Escalation required</h3>
      <p className="mt-1.5 text-[13px] leading-relaxed text-fg-dim">
        This transaction exceeds the automatic authorization limit of{' '}
        <span className="mono">{money(mandate.perTransaction)}</span>. The agent cannot proceed on
        its own.
      </p>

      {!approved ? (
        <Button variant="primary" className="mt-5 w-full" onClick={() => onApprove(attempt.id)}>
          <PenLine size={13} />
          Approve purchase
        </Button>
      ) : (
        <div className="mt-5 space-y-3">
          <div className="flex items-center justify-between gap-3 rounded-lg border border-allow/25 bg-allow/8 px-4 py-3">
            <span className="text-[13px] font-medium text-allow">
              Approved by {attempt.approvedBy?.split(' ')[0]}
            </span>
            <span className="mono text-[10px] text-verify">Ed25519 signature verified</span>
          </div>
          <Button
            variant="primary"
            className="w-full"
            disabled={attempt.captured}
            onClick={() => onCapture(attempt.id)}
          >
            {attempt.captured ? 'Payment captured' : 'Capture payment'}
          </Button>
        </div>
      )}
    </section>
  );
}

function DenyBlock({ reason, onViewPolicy }: { reason: string; onViewPolicy: () => void }) {
  return (
    <section className="overflow-hidden rounded-xl border border-deny/35 bg-deny/[0.05]">
      <div className="flex flex-col items-center gap-3 px-6 py-8 text-center">
        <span className="flex size-11 items-center justify-center rounded-full border border-deny/30 bg-deny/10">
          <Ban size={19} className="text-deny" strokeWidth={1.75} />
        </span>
        <h3 className="font-display text-[19px] font-bold tracking-tight text-deny">
          Payment denied
        </h3>
        <div className="mono text-[10px] tracking-widest text-deny/80 uppercase">{reason}</div>
        <p className="max-w-sm text-[13px] leading-relaxed text-fg-dim">
          This transaction cannot be approved by the human. The mandate does not permit this amount.
        </p>
        <button
          onClick={onViewPolicy}
          className="mono mt-1 text-[10px] tracking-wider text-fg-mute uppercase underline underline-offset-4 transition-colors hover:text-fg"
        >
          View policy
        </button>
      </div>
    </section>
  );
}

function Countdown({ seconds }: { seconds: number }) {
  const [left, setLeft] = useState(seconds);
  useEffect(() => {
    setLeft(seconds);
    if (seconds <= 0) return;
    const id = window.setInterval(() => setLeft((v) => (v > 0 ? v - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [seconds]);

  const mm = String(Math.floor(left / 60)).padStart(2, '0');
  const ss = String(left % 60).padStart(2, '0');
  return (
    <span className={`inline-flex items-center gap-1.5 ${left < 30 ? 'text-escalate' : ''}`}>
      <Timer size={11} />
      {mm}:{ss}
    </span>
  );
}
