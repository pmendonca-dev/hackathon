import { Fingerprint, Link2, Scale } from 'lucide-react';

import type { AuditorViewProjection } from '../contracts/avalGateway.ts';
import { Badge, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, formatMoney, shortHash } from '../utils/format.ts';
import { safeDisplayText } from '../utils/safePresentation.ts';

export function AuditorView({ data }: { data: AuditorViewProjection }) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do auditor</p>
          <h1>A decisão inteira, em ordem e em português.</h1>
          <p>Cada linha é append-only: ator, motivo, estado da reserva, evidência e hash de integridade permanecem juntos.</p>
        </div>
        <Badge tone={data.chainStatus === 'verified' ? 'verify' : 'deny'}>cadeia {data.chainStatus}</Badge>
      </header>

      <Panel eyebrow="Audit ledger" title="Timeline canônica" action={<span className="mono text-[10px] text-fg-mute">HEAD {shortHash(data.chainHead)}</span>}>
        <ol className="audit-timeline" aria-label="Eventos append-only">
          {data.events.map((event) => (
            <li key={event.id} className="audit-event">
              <div className="audit-sequence" aria-hidden="true">{event.sequence}</div>
              <article className="min-w-0 rounded-xl border border-line bg-ink-800/50 p-4">
                <div className="flex flex-wrap items-start justify-between gap-3">
                  <div>
                    <p className="eyebrow">{safeDisplayText(event.eventType)}</p>
                    <h3 className="mt-1 text-sm font-semibold">{safeDisplayText(event.humanSummary)}</h3>
                  </div>
                  <Badge tone={event.reservationState === 'settled' ? 'allow' : event.reservationState === 'committed' ? 'verify' : 'neutral'}>{event.reservationState}</Badge>
                </div>
                <dl className="mt-3 grid gap-x-5 sm:grid-cols-2">
                  <Field label="Ator">{safeDisplayText(event.actor)} · {safeDisplayText(event.actorRole)}</Field>
                  <Field label="Motivo">{safeDisplayText(event.reasonCode)}</Field>
                  <Field label="Quando">{formatDateTime(event.occurredAt)}</Field>
                  <Field label="Evento">{safeDisplayText(event.id)}</Field>
                  <Field label="Evidência">referência protegida</Field>
                  <Field label="Integridade">{shortHash(event.integrityHash)}</Field>
                </dl>
              </article>
            </li>
          ))}
        </ol>
      </Panel>

      <Panel eyebrow="Disputa reconstruída" title={safeDisplayText(data.dispute.id)} action={<Scale size={18} className="text-escalate" aria-hidden="true" />}>
        <div className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
          <dl>
            <Field label="Merchant" mono={false}>{safeDisplayText(data.dispute.merchant)}</Field>
            <Field label="Valor">{formatMoney(data.dispute.amount)}</Field>
            <Field label="Status">{data.dispute.status}</Field>
            <Field label="Alegação" mono={false}>{safeDisplayText(data.dispute.claim)}</Field>
          </dl>
          <div className="rounded-xl border border-escalate/30 bg-escalate/7 p-4">
            <p className="eyebrow text-escalate">Leitura da trilha</p>
            <p className="mt-2 text-sm leading-relaxed">{safeDisplayText(data.dispute.verdictSummary)}</p>
            <p className="mono mt-4 flex items-center gap-2 text-[10px] text-fg-mute"><Link2 size={12} aria-hidden="true" />{data.dispute.evidenceRefs.length} referências protegidas</p>
          </div>
        </div>
      </Panel>

      <p className="safe-note"><Fingerprint size={15} aria-hidden="true" />A interface não corrige, reordena nem reescreve eventos; a sequência exibida veio da boundary.</p>
    </div>
  );
}
