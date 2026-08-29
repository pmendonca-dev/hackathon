import { ArrowUpRight, Ban } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import { Page, TopBar } from '../components/Shell';
import { Panel, Badge, Button, toneFor } from '../components/ui';
import { FlowSpine } from '../components/FlowSpine';
import { AuthorityRail } from '../components/AuthorityRail';

export function Overview() {
  const { state, metrics, go, openAttempt } = useStore();
  const mandate = state.mandates[0];
  const attempt = state.attempts.find((a) => a.id === state.flow.attemptId);

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Authorization Overview']}
        title="Authorization Overview"
        subtitle="Real-time authorization and payment control"
        action={
          <Button variant="ghost" onClick={() => go('judge')}>
            Judge console
            <ArrowUpRight size={13} />
          </Button>
        }
      />
      <Page>
        {/* ── Metrics ─────────────────────────────────────────────────── */}
        <div className="grid grid-cols-2 gap-3 xl:grid-cols-4">
          <Metric label="Authorized today" value={money(metrics.authorizedToday)} />
          <Metric label="Active mandates" value={String(metrics.activeMandates)} />
          <Metric
            label="Pending confirmations"
            value={String(metrics.pendingConfirmations)}
            tone={metrics.pendingConfirmations > 0 ? 'escalate' : undefined}
          />
          <UnauthorizedSpend value={metrics.unauthorizedSpend} />
        </div>

        {/* ── The pipeline ────────────────────────────────────────────── */}
        <Panel
          className="mt-3"
          bodyClass=""
          eyebrow="Pipeline"
          title="Payment Authorization Flow"
          action={
            attempt && (
              <button
                onClick={() => {
                  go('agent');
                  setTimeout(() => openAttempt(attempt.id), 60);
                }}
                className="mono flex items-center gap-1.5 text-[10px] tracking-wider text-fg-mute uppercase transition-colors hover:text-fg"
              >
                {attempt.merchant} · {money(attempt.amount)}
                <ArrowUpRight size={12} />
              </button>
            )
          }
        >
          <FlowSpine flow={state.flow} />
        </Panel>

        {/* ── Authority, drawn to scale ───────────────────────────────── */}
        <div className="mt-3 grid gap-3 lg:grid-cols-[1.6fr_1fr]">
          <Panel
            eyebrow={`Mandate · ${mandate.id}`}
            title={`${mandate.principal} — authority granted`}
            action={<Badge tone={toneFor(mandate.status)} dot>{mandate.status}</Badge>}
          >
            <p className="mb-5 max-w-lg text-[13px] leading-relaxed text-fg-mute">
              The agent acts alone below{' '}
              <span className="mono text-allow">{money(mandate.perTransaction)}</span>, returns for a
              signature up to{' '}
              <span className="mono text-escalate">{money(mandate.monthlyLimit)}</span>, and can
              never cross that ceiling — not even with the principal's approval.
            </p>
            <AuthorityRail mandate={mandate} amount={attempt?.amount} size="lg" />
            <button
              onClick={() => go('mandates')}
              className="mono mt-5 flex items-center gap-1.5 text-[10px] tracking-wider text-fg-mute uppercase transition-colors hover:text-fg"
            >
              Open mandate
              <ArrowUpRight size={12} />
            </button>
          </Panel>

          <Panel eyebrow="Budget" title="This period">
            <div className="space-y-4">
              <BudgetBar mandate={mandate} />
              <dl className="space-y-2.5 pt-1">
                <Line label="Committed" value={money(mandate.committed)} tone="text-fg" />
                <Line
                  label="Reserved"
                  value={money(mandate.reserved)}
                  tone={mandate.reserved > 0 ? 'text-hold' : 'text-fg-mute'}
                />
                <Line
                  label="Remaining"
                  value={money(mandate.monthlyLimit - mandate.committed - mandate.reserved)}
                  tone="text-allow"
                />
                <Line
                  label="Uses"
                  value={`${mandate.uses} / ${mandate.maxUses}`}
                  tone="text-fg-dim"
                />
              </dl>
            </div>
          </Panel>
        </div>
      </Page>
    </>
  );
}

function Line({ label, value, tone }: { label: string; value: string; tone: string }) {
  return (
    <div className="flex items-baseline justify-between gap-3">
      <dt className="eyebrow">{label}</dt>
      <dd className={`mono text-[13px] ${tone}`}>{value}</dd>
    </div>
  );
}

function BudgetBar({ mandate }: { mandate: { committed: number; reserved: number; monthlyLimit: number } }) {
  const c = (mandate.committed / mandate.monthlyLimit) * 100;
  const r = (mandate.reserved / mandate.monthlyLimit) * 100;
  return (
    <div className="flex h-2 overflow-hidden rounded-full bg-ink-750">
      <span className="bg-allow transition-all duration-500" style={{ width: `${c}%` }} />
      <span className="bg-hold transition-all duration-500" style={{ width: `${r}%` }} />
    </div>
  );
}

export function Metric({
  label,
  value,
  tone,
  hint,
}: {
  label: string;
  value: string;
  tone?: 'allow' | 'escalate' | 'deny' | 'hold';
  hint?: string;
}) {
  const ink = tone ? { allow: 'text-allow', escalate: 'text-escalate', deny: 'text-deny', hold: 'text-hold' }[tone] : 'text-fg';
  return (
    <div className="rounded-xl border border-line bg-ink-850 px-5 py-4">
      <div className="eyebrow">{label}</div>
      <div className={`mono mt-2.5 text-[26px] leading-none font-medium tracking-tight ${ink}`}>
        {value}
      </div>
      {hint && <div className="mt-2 text-[11px] text-fg-mute">{hint}</div>}
    </div>
  );
}

/**
 * The one metric that carries the thesis, so it gets the one piece of extra
 * weight in the layout: a lime hairline, the invariant spelled out, and the
 * only ambient glow on the page.
 */
function UnauthorizedSpend({ value }: { value: number }) {
  const clean = value === 0;
  return (
    <div
      className={`relative overflow-hidden rounded-xl border px-5 py-4 ${
        clean ? 'border-allow/30 bg-allow/[0.045]' : 'border-deny/40 bg-deny/8'
      }`}
    >
      <div className="flex items-center gap-1.5">
        <Ban size={11} className={clean ? 'text-allow' : 'text-deny'} strokeWidth={2.25} />
        <span className="eyebrow">Unauthorized spend</span>
      </div>
      <div
        className={`mono mt-2.5 text-[26px] leading-none font-semibold tracking-tight ${
          clean ? 'text-allow' : 'text-deny'
        }`}
      >
        {money(value)}
      </div>
      <div className="mt-2 text-[11px] text-fg-mute">
        {clean ? 'No spend outside a mandate. Ever.' : 'Invariant broken — investigate.'}
      </div>
      {clean && (
        <span className="pointer-events-none absolute -right-8 -bottom-10 size-28 rounded-full bg-allow/8 blur-2xl" />
      )}
    </div>
  );
}
