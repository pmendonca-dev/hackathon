import { ChevronRight, Radio, ShieldOff } from 'lucide-react';
import { useStore } from '../domain/store';
import { money } from '../domain/policy';
import { Page, TopBar } from '../components/Shell';
import { Badge, Button, Drawer, Field, toneFor, StatusDot } from '../components/ui';
import { AuthorityRail } from '../components/AuthorityRail';
import { Timeline } from '../components/Verification';
import type { Mandate } from '../domain/types';

export function Mandates() {
  const { state, openMandate } = useStore();
  const open = state.mandates.find((m) => m.id === state.openMandateId);

  return (
    <>
      <TopBar
        crumb={['Yuno', 'Mandates']}
        title="Mandates"
        subtitle="Standing authority granted by a human to an agent"
      />
      <Page>
        <ul className="space-y-3">
          {state.mandates.map((m) => (
            <MandateRow key={m.id} mandate={m} onOpen={() => openMandate(m.id)} />
          ))}
        </ul>
      </Page>

      <Drawer
        open={!!open}
        onClose={() => openMandate(null)}
        eyebrow={open?.id}
        title={open?.principal ?? ''}
        width="max-w-2xl"
      >
        {open && <MandateDetail mandate={open} />}
      </Drawer>
    </>
  );
}

function MandateRow({ mandate, onOpen }: { mandate: Mandate; onOpen: () => void }) {
  const revoked = mandate.status !== 'ACTIVE';
  return (
    <li>
      <button
        onClick={onOpen}
        className={`group w-full rounded-xl border border-line bg-ink-850 p-5 text-left transition-colors hover:border-line-hi hover:bg-ink-800 ${
          revoked ? 'opacity-70' : ''
        }`}
      >
        <div className="flex flex-wrap items-start justify-between gap-4">
          <div className="min-w-0">
            <div className="flex items-center gap-2.5">
              <h3 className="font-display text-[17px] font-semibold tracking-tight">
                {mandate.principal}
              </h3>
              <Badge tone={toneFor(mandate.status)} dot>
                {mandate.status}
              </Badge>
            </div>
            <div className="mono mt-1.5 text-[11px] text-fg-mute">
              {mandate.id} · {mandate.agent} · {mandate.category}
            </div>
          </div>
          <div className="flex items-center gap-4">
            <span className="mono text-[10px] text-fg-faint">{mandate.lastActivity}</span>
            <ChevronRight
              size={15}
              className="text-fg-faint transition-transform group-hover:translate-x-0.5 group-hover:text-fg-dim"
            />
          </div>
        </div>

        <dl className="mt-5 grid grid-cols-2 gap-x-6 gap-y-3 sm:grid-cols-4">
          <Stat label="Per transaction" value={money(mandate.perTransaction)} />
          <Stat label="Monthly limit" value={money(mandate.monthlyLimit)} />
          <Stat label="Uses" value={`${mandate.uses} / ${mandate.maxUses}`} />
          <Stat label="Merchant scope" value={mandate.category} />
        </dl>

        <div className="mt-5">
          <AuthorityRail mandate={mandate} size="sm" showScale={false} />
        </div>
      </button>
    </li>
  );
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="eyebrow">{label}</dt>
      <dd className="mono mt-1 text-[13px] text-fg">{value}</dd>
    </div>
  );
}

function MandateDetail({ mandate }: { mandate: Mandate }) {
  const { revoke, toast } = useStore();
  const active = mandate.status === 'ACTIVE';

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <Badge tone={toneFor(mandate.status)} dot>
          MANDATE {mandate.status}
        </Badge>
        <span className="mono text-[10px] text-fg-faint">epoch {mandate.revocation.epoch}</span>
      </div>

      {/* Policy, as a shape rather than a table of numbers */}
      <section>
        <h3 className="eyebrow mb-3">Authorization policy</h3>
        <AuthorityRail mandate={mandate} size="lg" />
        <ul className="mono mt-4 space-y-1.5 text-[11px]">
          <li className="text-allow">
            ≤ {money(mandate.perTransaction)} → ALLOW
          </li>
          <li className="text-escalate">
            {money(mandate.perTransaction)} – {money(mandate.monthlyLimit)} → ESCALATE
          </li>
          <li className="text-deny">&gt; {money(mandate.monthlyLimit)} → DENY</li>
        </ul>
      </section>

      <section className="rounded-xl border border-line bg-ink-850 px-5 py-1">
        <Field label="Category">{mandate.category}</Field>
        <Field label="Destination">{mandate.destinations.join(' / ')}</Field>
        <Field label="Currency">{mandate.currency}</Field>
        <Field label="Agent">{mandate.agent}</Field>
        <Field label="Max live reservations">{mandate.maxLiveReservations}</Field>
        <Field label="Expires">{mandate.expiresAt}</Field>
      </section>

      {/* Revocation is the one thing no payment protocol covers, so it gets
          its own surface rather than a row in a table. */}
      <section
        className={`rounded-xl border px-5 py-4 ${
          active ? 'border-verify/25 bg-verify/[0.04]' : 'border-deny/30 bg-deny/[0.05]'
        }`}
      >
        <div className="flex items-center justify-between gap-4">
          <div className="flex items-center gap-2">
            {active ? (
              <Radio size={13} className="text-verify" />
            ) : (
              <ShieldOff size={13} className="text-deny" />
            )}
            <span className="eyebrow">Revocation status</span>
          </div>
          <span className={`mono text-[10px] font-semibold ${active ? 'text-verify' : 'text-deny'}`}>
            {active ? 'LIVE CHECK ENABLED' : 'AUTHORITY WITHDRAWN'}
          </span>
        </div>
        <div className="mono mt-3 flex flex-wrap items-center gap-x-5 gap-y-1.5 text-[11px] text-fg-mute">
          <span className="flex items-center gap-1.5">
            <StatusDot tone={active ? 'verify' : 'deny'} pulse={active} />
            Last checked: {mandate.revocation.lastCheckedSeconds}s ago
          </span>
          <span className="truncate">{mandate.revocation.revocationId}</span>
        </div>
        {!active && (
          <p className="mt-3 border-t border-deny/20 pt-3 text-[12px] leading-relaxed text-fg-dim">
            The mandate stays cryptographically valid. It simply carries no authority — every commit
            re-reads the registry inside the same transaction, so nothing in flight can outrun this.
          </p>
        )}
      </section>

      <section>
        <h3 className="eyebrow mb-3.5">Lifecycle</h3>
        <Timeline events={mandate.timeline} />
      </section>

      <div className="flex justify-end gap-2 border-t border-line pt-5">
        {active ? (
          <Button variant="danger" onClick={() => revoke(mandate.id)}>
            <ShieldOff size={13} />
            Revoke mandate
          </Button>
        ) : (
          <Button
            variant="ghost"
            onClick={() =>
              toast({
                tone: 'deny',
                title: 'Revocation is final',
                body: 'The state machine is monotonic. Issue a new mandate instead.',
              })
            }
          >
            Revocation is irreversible
          </Button>
        )}
      </div>
    </div>
  );
}
