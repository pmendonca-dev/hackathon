import { Bot, KeyRound, ScrollText, Store, UserRound } from 'lucide-react';

import type {
  UiAuditProjection,
  UiDisputeProjection,
  UiMandateProjection,
} from '../contracts/avalGateway.ts';
import { safeDisplayText } from '../utils/safePresentation.ts';

function authorityReading(
  mandate: UiMandateProjection | null,
  dispute: UiDisputeProjection | null,
) {
  if (!mandate) {
    return {
      tone: 'neutral',
      label: 'Aguardando projeção autorizada',
      detail: 'O mapa só aparece quando o BFF devolve um mandato para a sessão do titular.',
    };
  }
  if (mandate.status === 'revoked') {
    return {
      tone: 'deny',
      label: 'Mandato revogado',
      detail: dispute?.post_commit_note ?? 'Novas compras ficam bloqueadas sem reescrever liquidações anteriores.',
    };
  }
  if (mandate.status === 'expired') {
    return {
      tone: 'deny',
      label: 'Mandato expirado',
      detail: 'O runtime não pode autorizar uma nova compra com esta autoridade.',
    };
  }
  return {
    tone: 'allow',
    label: 'Mandato ativo no Core',
    detail: dispute?.human_summary ?? 'A projeção BFF confirma a autoridade vigente sem enviar credenciais ao browser.',
  };
}

function publishedAllowance(mandate: UiMandateProjection | null): string {
  if (!mandate || mandate.available_amount === undefined) return 'não publicado';
  const currency = mandate.currency ? ` ${safeDisplayText(mandate.currency)}` : '';
  return `${mandate.available_amount} minor units${currency}`;
}

export function AuthorityAtlas({
  mandate,
  audit,
  dispute,
}: {
  mandate: UiMandateProjection | null;
  audit: UiAuditProjection | null;
  dispute: UiDisputeProjection | null;
}) {
  const state = authorityReading(mandate, dispute);
  const active = mandate?.status === 'active';
  const timelineCount = audit?.timeline.length ?? 0;
  const merchantLabel = mandate?.merchant_id
    ? safeDisplayText(mandate.merchant_id)
    : 'Escopo autorizado';

  return (
    <section className={`authority-atlas authority-atlas--${state.tone}`} aria-label="Mapa de autoridade da compra">
      <div className="atlas-heading">
        <div>
          <p className="eyebrow">Mapa da autoridade · projeção BFF</p>
          <h2>O mandato orienta a compra.</h2>
        </div>
        <span className="atlas-status">{state.label}</span>
      </div>

      <div className="atlas-stage">
        <svg className="atlas-lines" viewBox="0 0 720 320" role="img" aria-label="Circuito entre titular, agente, mandato, merchant e trilha autorizada">
          <path className="atlas-line atlas-line--main" d="M108 92 C206 92 194 166 315 166 S421 104 548 104" />
          <path className="atlas-line atlas-line--audit" d="M392 178 C472 214 500 245 576 244" />
          <path className="atlas-line atlas-line--guard" d="M108 226 C206 226 238 194 315 178" />
          <circle className="atlas-anchor atlas-anchor--mandate" cx="353" cy="169" r="7" />
          <circle className="atlas-anchor atlas-anchor--merchant" cx="548" cy="104" r="6" />
          <circle className="atlas-anchor atlas-anchor--trail" cx="576" cy="244" r="6" />
        </svg>

        <div className="atlas-node atlas-node--holder"><UserRound size={15} aria-hidden="true" /><b>Titular autenticado</b><span>consulta sua projeção</span></div>
        <div className="atlas-node atlas-node--agent"><Bot size={15} aria-hidden="true" /><b>Agente</b><span>opera fora do browser</span></div>
        <div className="atlas-node atlas-node--merchant"><Store size={15} aria-hidden="true" /><b>{merchantLabel}</b><span>recebe projeção própria</span></div>
        <div className="atlas-node atlas-node--trail"><ScrollText size={15} aria-hidden="true" /><b>Trilha</b><span>{timelineCount} evento(s) autorizado(s)</span></div>

        <div className="atlas-mandate">
          <KeyRound size={15} aria-hidden="true" />
          <span>Mandato</span>
          <strong>{publishedAllowance(mandate)}</strong>
          <small>{mandate ? safeDisplayText(mandate.status) : 'sem projeção'}</small>
          <div className="atlas-meter" aria-label="Estado operacional do mandato"><span style={{ width: active ? '100%' : '0%' }} /></div>
        </div>
      </div>

      <p className="atlas-detail" aria-live="polite">{safeDisplayText(state.detail)}</p>
    </section>
  );
}
