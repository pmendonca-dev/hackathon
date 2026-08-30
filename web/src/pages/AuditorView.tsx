import { Fingerprint, Scale } from 'lucide-react';

import type {
  UiAuditProjection,
  UiDisputeProjection,
  UiWorkspaceProjection,
} from '../contracts/avalGateway.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime } from '../utils/format.ts';
import { safeDisplayText } from '../utils/safePresentation.ts';

export function AuditorView({
  workspace,
  audit,
  dispute,
}: {
  workspace: UiWorkspaceProjection;
  audit: UiAuditProjection | null;
  dispute: UiDisputeProjection | null;
}) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do auditor · BFF</p>
          <h1>Timeline append-only na ordem autorizada.</h1>
          <p>O browser apresenta o vocabulário fechado do BFF sem refletir evidência ou texto bruto do ledger.</p>
        </div>
        <Badge tone="verify">{workspace.mandates.length} mandato(s)</Badge>
      </header>

      <Panel eyebrow="Audit ledger" title={audit ? safeDisplayText(audit.mandate_id) : 'Sem mandato selecionado'} action={<Fingerprint size={18} className="text-verify" aria-hidden="true" />}>
        {!audit || audit.timeline.length === 0 ? (
          <EmptyNotice title="Nenhum evento retornado" body="A projeção auditável está vazia para o mandato selecionado." />
        ) : (
          <ol className="audit-timeline" aria-label="Eventos append-only">
            {audit.timeline.map((event, index) => (
              <li key={`${event.sequence ?? index}-${event.occurred_at}`} className="audit-event">
                <div className="audit-sequence" aria-hidden="true">{event.sequence ?? index + 1}</div>
                <article className="min-w-0 rounded-xl border border-line bg-ink-800/50 p-4">
                  <p className="eyebrow">{safeDisplayText(event.event_type)}</p>
                  <h3 className="mt-1 text-sm font-semibold">{safeDisplayText(event.human_summary)}</h3>
                  <dl className="mt-3">
                    <Field label="Quando">{formatDateTime(event.occurred_at)}</Field>
                    <Field label="Sequência">{event.sequence ?? 'não publicada'}</Field>
                  </dl>
                </article>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <Panel eyebrow="Disputa reconstruída" title={dispute ? safeDisplayText(dispute.reason_code) : 'Sem projeção'} action={<Scale size={18} className="text-escalate" aria-hidden="true" />}>
        <p className="text-sm leading-relaxed">
          {dispute ? safeDisplayText(dispute.human_summary) : 'Nenhuma disputa foi devolvida.'}
        </p>
        {dispute?.post_commit_note && (
          <p className="mt-4 rounded-xl border border-escalate/30 bg-escalate/7 p-4 text-[13px] leading-relaxed text-escalate">
            {safeDisplayText(dispute.post_commit_note)}
          </p>
        )}
      </Panel>

      <p className="safe-note"><Fingerprint size={15} aria-hidden="true" />A ordem exibida é a ordem recebida do BFF; a interface não reclassifica fatos.</p>
    </div>
  );
}
