import { CheckCircle2, Clock3, ShieldCheck, WalletCards } from 'lucide-react';

import type { HumanViewProjection, Tone } from '../contracts/avalGateway.ts';
import { AuthorityRail } from '../components/AuthorityRail.tsx';
import { Badge, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, formatMoney, shortHash } from '../utils/format.ts';

const decisionTone: Record<HumanViewProjection['latestDecision']['status'], Tone> = {
  authorized: 'allow',
  awaiting_human: 'escalate',
  rejected: 'deny',
};

export function HumanView({ data }: { data: HumanViewProjection }) {
  const { mandate, latestDecision } = data;
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do titular</p>
          <h1>{data.principalName}, esta é a autoridade que está viva agora.</h1>
          <p>Veja o que seu agente pode fazer e como cada compra foi explicada pelo AVAL.</p>
        </div>
        <Badge tone={mandate.status === 'active' ? 'allow' : 'deny'}>{mandate.status}</Badge>
      </header>

      <section className="grid gap-4 xl:grid-cols-[1.35fr_0.65fr]">
        <Panel eyebrow="Mandato ativo" title={mandate.purpose} action={<span className="mono text-[10px] text-fg-mute">{mandate.id}</span>}>
          <AuthorityRail projection={mandate.authorityRail} moneyTemplate={mandate.ceiling} />
          <dl className="mt-5 grid gap-x-6 sm:grid-cols-2">
            <Field label="Agente" mono={false}>{mandate.agentName}</Field>
            <Field label="Allowance viva">{formatMoney(mandate.liveAllowance)}</Field>
            <Field label="Limite por compra">{formatMoney(mandate.perTransactionLimit)}</Field>
            <Field label="Teto do mandato">{formatMoney(mandate.ceiling)}</Field>
            <Field label="Token do cofre">{mandate.vaultToken}</Field>
            <Field label="Revogação">epoch {mandate.revocation.epoch} · {mandate.revocation.state}</Field>
          </dl>
          <div className="mt-4 flex flex-wrap gap-2" aria-label="Escopos permitidos">
            {mandate.scopes.map((scope) => <Badge key={scope}>{scope}</Badge>)}
          </div>
        </Panel>

        <Panel eyebrow="Última decisão" title="O que o core decidiu" action={<Badge tone={decisionTone[latestDecision.status]}>{latestDecision.status}</Badge>}>
          <div className="rounded-xl border border-allow/25 bg-allow/6 p-4">
            <CheckCircle2 className="text-allow" size={20} aria-hidden="true" />
            <p className="mt-3 text-sm leading-relaxed">{latestDecision.humanSummary}</p>
          </div>
          <dl className="mt-3">
            <Field label="Motivo">{latestDecision.reasonCode}</Field>
            <Field label="Reserva">{latestDecision.reservationState}</Field>
            <Field label="Política">{latestDecision.policyVersion}</Field>
            <Field label="Evidência">{shortHash(latestDecision.evidenceRef)}</Field>
          </dl>
        </Panel>
      </section>

      <Panel eyebrow="Recibos" title="Compras e decisões recentes" action={<WalletCards size={17} className="text-verify" aria-hidden="true" />}>
        <ul className="divide-y divide-line" aria-label="Recibos recentes">
          {data.receipts.map((receipt) => (
            <li key={receipt.id} className="grid gap-3 py-4 first:pt-0 last:pb-0 sm:grid-cols-[1fr_auto] sm:items-center">
              <div>
                <div className="flex flex-wrap items-center gap-2">
                  <h3 className="font-display text-sm font-semibold">{receipt.merchant}</h3>
                  <Badge tone={receipt.status === 'settled' ? 'allow' : receipt.status === 'awaiting_human' ? 'escalate' : 'deny'}>{receipt.status}</Badge>
                </div>
                <p className="mt-1 text-[13px] text-fg-dim">{receipt.item}</p>
                <p className="mt-2 text-[12px] leading-relaxed text-fg-mute">{receipt.humanSummary}</p>
                <span className="mono mt-2 flex items-center gap-1.5 text-[10px] text-fg-mute"><Clock3 size={11} aria-hidden="true" />{formatDateTime(receipt.occurredAt)} · {shortHash(receipt.receiptHash)}</span>
              </div>
              <strong className="mono text-base text-fg">{formatMoney(receipt.amount)}</strong>
            </li>
          ))}
        </ul>
      </Panel>

      <p className="safe-note"><ShieldCheck size={15} aria-hidden="true" />Allowance e estados são projeções recebidas. Esta tela não recalcula saldo, regra, revogação ou captura.</p>
    </div>
  );
}

