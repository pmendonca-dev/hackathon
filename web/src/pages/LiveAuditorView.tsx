import { Fingerprint, Scale } from 'lucide-react';

import type { AuditVerdictProjection } from '../contracts/paymentRuntimeApi.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, shortHash } from '../utils/format.ts';

export function LiveAuditorView({
  audit,
  dispute,
}: {
  audit: AuditVerdictProjection;
  dispute: AuditVerdictProjection;
}) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do auditor · API real</p>
          <h1>A timeline append-only na ordem devolvida pelo runtime.</h1>
          <p>Ator, motivo, explicação e hash de evidência são apresentados sem correção ou reclassificação local.</p>
        </div>
        <Badge tone="verify">{audit.status}</Badge>
      </header>

      <Panel eyebrow="Audit ledger" title="Timeline canônica" action={<span className="mono text-[10px] text-fg-mute">{audit.timeline.length} eventos</span>}>
        {audit.timeline.length === 0 ? (
          <EmptyNotice title="Nenhum evento retornado" body="A API respondeu com uma timeline vazia para este mandato." />
        ) : (
          <ol className="audit-timeline" aria-label="Eventos append-only">
            {audit.timeline.map((event, index) => (
              <li key={event.id} className="audit-event">
                <div className="audit-sequence" aria-hidden="true">{index + 1}</div>
                <article className="min-w-0 rounded-xl border border-line bg-ink-800/50 p-4">
                  <p className="eyebrow">{event.event_type}</p>
                  <h3 className="mt-1 text-sm font-semibold">{event.human_summary}</h3>
                  <dl className="mt-3 grid gap-x-5 sm:grid-cols-2">
                    <Field label="Ator">{event.actor}</Field>
                    <Field label="Motivo">{event.reason_code}</Field>
                    <Field label="Quando">{formatDateTime(event.occurred_at)}</Field>
                    <Field label="Epoch">{event.revocation_epoch}</Field>
                    <Field label="Evento">{event.id}</Field>
                    <Field label="Evidência">{shortHash(event.evidence_hash)}</Field>
                  </dl>
                </article>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel eyebrow="Disputa reconstruída" title={dispute.reason_code} action={<Scale size={18} className="text-escalate" aria-hidden="true" />}>
        <p className="text-sm leading-relaxed">{dispute.human_summary}</p>
        {dispute.post_commit_note && (
          <p className="mt-4 rounded-xl border border-escalate/30 bg-escalate/7 p-4 text-[13px] leading-relaxed text-escalate">
            {dispute.post_commit_note}
          </p>
        )}
      </Panel>

      <p className="safe-note"><Fingerprint size={15} aria-hidden="true" />A ordem usada é a ordem de <span className="mono">timeline</span> recebida; o browser não reordena eventos.</p>
    </div>
  );
}
