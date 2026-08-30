import { useMemo } from 'react';
import { Bot, KeyRound, ScrollText, Store, UserRound } from 'lucide-react';

import type { AgentRun, MandateView } from '../gateways/authorizationGateway.ts';
import { formatMoney } from '../utils/format.ts';

type Chain = { intact: boolean; checked: number; broken_at: number | null } | null;

function toMoney(value: { minor_units: number; currency: string; scale: number }) {
  return { minorUnits: value.minor_units, currency: value.currency, scale: value.scale };
}

function reading(run: AgentRun | null, chain: Chain) {
  if (chain?.intact === false) {
    return { tone: 'deny', label: `Trilha interrompida no elo ${chain.broken_at}`, detail: 'A auditoria detectou uma alteração real.' };
  }
  if (!run) {
    return { tone: 'neutral', label: 'Aguardando uma decisão', detail: 'Escolha um cenário ou escreva uma instrução para o agente.' };
  }
  if (run.outcome === 'settled') {
    return { tone: 'allow', label: 'Compra liquidada dentro da autoridade', detail: run.human_summary };
  }
  if (run.escalation_id) {
    return { tone: 'escalate', label: 'Ponto de decisão humana aberto', detail: run.human_summary };
  }
  return { tone: 'deny', label: 'A rota foi bloqueada pelo núcleo', detail: run.human_summary };
}

export function AuthorityAtlas({
  mandate,
  lastRun,
  chain,
}: {
  mandate: MandateView | null;
  lastRun: AgentRun | null;
  chain: Chain;
}) {
  const state = useMemo(() => reading(lastRun, chain), [lastRun, chain]);
  const journeyKey = lastRun
    ? [lastRun.reservation_id, lastRun.escalation_id, lastRun.settlement_reference, lastRun.authorization_proof, lastRun.reason_code].join(':')
    : null;
  const remaining = mandate && mandate.limit.minor_units > 0
    ? Math.max(0, Math.min(100, (mandate.remaining.minor_units / mandate.limit.minor_units) * 100))
    : 0;

  return (
    <section className={`authority-atlas authority-atlas--${state.tone}`} aria-label="Mapa de autoridade da compra">
      <div className="atlas-heading">
        <div>
          <p className="eyebrow">Mapa da autoridade</p>
          <h2>O mandato orienta a compra.</h2>
        </div>
        <span className="atlas-status">{state.label}</span>
      </div>

      <div className="atlas-stage">
        <svg className="atlas-lines" viewBox="0 0 720 320" role="img" aria-label="Circuito entre titular, agente, mandato, merchant e trilha">
          <path className="atlas-line atlas-line--main" d="M108 92 C206 92 194 166 315 166 S421 104 548 104" />
          <path className="atlas-line atlas-line--audit" d="M392 178 C472 214 500 245 576 244" />
          <path className="atlas-line atlas-line--guard" d="M108 226 C206 226 238 194 315 178" />
          <circle className="atlas-anchor atlas-anchor--mandate" cx="353" cy="169" r="7" />
          <circle className="atlas-anchor atlas-anchor--merchant" cx="548" cy="104" r="6" />
          <circle className="atlas-anchor atlas-anchor--trail" cx="576" cy="244" r="6" />
          {lastRun && <circle key={journeyKey} className="atlas-traveler" r="7"><animateMotion dur="1.25s" path="M108 92 C206 92 194 166 315 166 S421 104 548 104" fill="freeze" /></circle>}
        </svg>

        <div className="atlas-node atlas-node--holder"><UserRound size={15} aria-hidden="true" /><b>{mandate?.principal.display_name ?? 'Titular'}</b><span>assina a autoridade</span></div>
        <div className="atlas-node atlas-node--agent"><Bot size={15} aria-hidden="true" /><b>Agente</b><span>propõe, não autoriza</span></div>
        <div className="atlas-node atlas-node--merchant"><Store size={15} aria-hidden="true" /><b>{mandate?.allowed_merchant_ids[0] ?? 'Merchant'}</b><span>verifica sem identificar</span></div>
        <div className="atlas-node atlas-node--trail"><ScrollText size={15} aria-hidden="true" /><b>Trilha</b><span>{chain?.intact === false ? 'quebra detectada' : 'evidência encadeada'}</span></div>

        <div className="atlas-mandate">
          <KeyRound size={15} aria-hidden="true" />
          <span>Mandato</span>
          <strong>{mandate ? formatMoney(toMoney(mandate.remaining)) : '—'}</strong>
          <small>{mandate ? 'ainda autorizado' : 'crie uma autorização para abrir a rota'}</small>
          <div className="atlas-meter" aria-label="Orçamento restante"><span style={{ width: `${remaining}%` }} /></div>
        </div>
      </div>

      <p className="atlas-detail" aria-live="polite">{state.detail}</p>
    </section>
  );
}
