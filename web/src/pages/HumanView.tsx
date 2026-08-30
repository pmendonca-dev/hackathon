import { FileCheck2, ShieldCheck, WalletCards } from 'lucide-react';

import type {
  UiAuditProjection,
  UiDisputeProjection,
  UiWorkspaceProjection,
} from '../contracts/avalGateway.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime } from '../utils/format.ts';
import { safeDisplayText } from '../utils/safePresentation.ts';

export function HumanView({
  workspace,
  audit,
  dispute,
}: {
  workspace: UiWorkspaceProjection;
  audit: UiAuditProjection | null;
  dispute: UiDisputeProjection | null;
}) {
  const mandate = workspace.mandates[0];
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do titular · BFF</p>
          <h1>Mandato, timeline e disputa na projeção autorizada.</h1>
          <p>Os valores são fatos devolvidos pelo Core através do BFF; o browser não recalcula autoridade.</p>
        </div>
        <Badge tone={mandate?.status === 'active' ? 'allow' : 'deny'}>
          {mandate ? safeDisplayText(mandate.status) : 'sem mandato'}
        </Badge>
      </header>

      {!mandate ? (
        <EmptyNotice title="Nenhum mandato disponível" body="A sessão do titular não recebeu mandatos autorizados." />
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          <Panel eyebrow="Mandato" title={safeDisplayText(mandate.mandate_id)} action={<ShieldCheck size={18} className="text-verify" aria-hidden="true" />}>
            <dl>
              <Field label="Status">{safeDisplayText(mandate.status)}</Field>
              <Field label="Disponível">{mandate.available_amount ?? 'não publicado'} {mandate.currency ? safeDisplayText(mandate.currency) : ''}</Field>
              <Field label="Unidade">minor units</Field>
            </dl>
          </Panel>
          <Panel eyebrow="Disputa" title={dispute ? safeDisplayText(dispute.reason_code) : 'Sem projeção'} action={<FileCheck2 size={18} className="text-escalate" aria-hidden="true" />}>
            <p className="text-sm leading-relaxed text-fg-dim">
              {dispute ? safeDisplayText(dispute.human_summary) : 'Nenhuma disputa foi devolvida para este mandato.'}
            </p>
            {dispute?.post_commit_note && (
              <p className="mt-4 rounded-xl border border-escalate/30 bg-escalate/7 p-4 text-[13px] leading-relaxed text-escalate">
                {safeDisplayText(dispute.post_commit_note)}
              </p>
            )}
          </Panel>
        </section>
      )}

      <Panel eyebrow="Audit" title="Timeline autorizada" action={<WalletCards size={18} className="text-verify" aria-hidden="true" />}>
        {!audit || audit.timeline.length === 0 ? (
          <EmptyNotice title="Sem eventos" body="O BFF não devolveu eventos para o mandato selecionado." />
        ) : (
          <ol className="audit-timeline" aria-label="Timeline do titular">
            {audit.timeline.map((event, index) => (
              <li key={`${event.sequence ?? index}-${event.occurred_at}`} className="audit-event">
                <div className="audit-sequence" aria-hidden="true">{event.sequence ?? index + 1}</div>
                <article className="min-w-0 rounded-xl border border-line bg-ink-800/50 p-4">
                  <p className="eyebrow">{safeDisplayText(event.event_type)}</p>
                  <h3 className="mt-1 text-sm font-semibold">{safeDisplayText(event.human_summary)}</h3>
                  <p className="mono mt-2 text-[10px] text-fg-mute">{formatDateTime(event.occurred_at)}</p>
                </article>
              </li>
            ))}
          </ol>
        )}
      </Panel>

      <p className="safe-note"><ShieldCheck size={15} aria-hidden="true" />Esta visão não recebe evidência bruta, credenciais de pagamento ou material de assinatura.</p>
    </div>
  );
}
