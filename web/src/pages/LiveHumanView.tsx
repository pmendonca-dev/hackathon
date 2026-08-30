import { FileCheck2, ShieldCheck, WalletCards } from 'lucide-react';

import type { LiveWorkspaceProjection } from '../contracts/avalGateway.ts';
import { Badge, Field, Panel } from '../components/ui.tsx';
import { safeDisplayText } from '../utils/safePresentation.ts';

export function LiveHumanView({ data }: { data: LiveWorkspaceProjection }) {
  const decisionTone = data.audit.reason_code.includes('expired')
    || data.audit.reason_code.includes('revoked')
    || data.audit.reason_code.includes('unavailable')
    ? 'deny'
    : data.capture?.status === 'settled'
      ? 'allow'
      : 'hold';

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do titular · API real</p>
          <h1>O runtime explica o que aconteceu sem o browser refazer a decisão.</h1>
          <p>Somente fatos devolvidos pelas APIs de captura, recibo, auditoria e disputa aparecem aqui.</p>
        </div>
        <Badge tone={decisionTone}>{safeDisplayText(data.audit.status)}</Badge>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="Mandato observado" title={safeDisplayText(data.mandateId)} action={<ShieldCheck size={18} className="text-verify" aria-hidden="true" />}>
          <dl>
            <Field label="Resultado">{safeDisplayText(data.audit.status)}</Field>
            <Field label="Motivo">{safeDisplayText(data.audit.reason_code)}</Field>
            <Field label="Explicação" mono={false}>{safeDisplayText(data.audit.human_summary)}</Field>
            <Field label="Eventos duráveis">{data.audit.timeline.length}</Field>
          </dl>
        </Panel>

        <Panel eyebrow="Captura canônica" title={data.capture ? safeDisplayText(data.capture.capture_id) : 'Nenhuma captura configurada'} action={<WalletCards size={18} className="text-allow" aria-hidden="true" />}>
          {data.capture ? (
            <dl>
              <Field label="Status">{safeDisplayText(data.capture.status)}</Field>
              <Field label="Reserva">{safeDisplayText(data.capture.reservation_id)}</Field>
              <Field label="Liquidação">{safeDisplayText(data.capture.settlement_reference)}</Field>
              <Field label="Recibos">{data.receipts ? 'disponíveis' : 'indisponíveis'}</Field>
            </dl>
          ) : (
            <p className="text-[13px] leading-relaxed text-fg-mute">Configure um capture ID emitido pelo runtime para acompanhar liquidação e recibos.</p>
          )}
        </Panel>
      </section>

      <Panel eyebrow="Disputa" title={safeDisplayText(data.dispute.reason_code)} action={<FileCheck2 size={18} className="text-escalate" aria-hidden="true" />}>
        <p className="text-sm leading-relaxed">{safeDisplayText(data.dispute.human_summary)}</p>
        {data.dispute.post_commit_note && (
          <p className="mt-4 rounded-xl border border-escalate/30 bg-escalate/7 p-4 text-[13px] leading-relaxed text-escalate">
            {safeDisplayText(data.dispute.post_commit_note)}
          </p>
        )}
      </Panel>

      <p className="safe-note"><ShieldCheck size={15} aria-hidden="true" />Limite, saldo, escopo e identidade não são inventados quando a API não os publica.</p>
    </div>
  );
}
