import { LockKeyhole, Route, ShieldAlert } from 'lucide-react';

import type { UiMandateProjection } from '../contracts/avalGateway.ts';
import { Badge } from './ui.tsx';

type Scenario = {
  id: string;
  eyebrow: string;
  title: string;
  detail: string;
  tone: 'allow' | 'escalate' | 'deny';
  requiresRevocation?: boolean;
};

const scenarios: Scenario[] = [
  {
    id: 'within-mandate',
    eyebrow: 'compra legítima',
    title: 'Voo direto para Córdoba · US$130',
    detail: 'Oferta em travel, abaixo do orçamento e do teto.',
    tone: 'allow',
  },
  {
    id: 'category-scope',
    eyebrow: 'ataque de categoria',
    title: 'Hotel em Córdoba',
    detail: 'Parece parte da viagem, mas lodging não pertence ao escopo travel.',
    tone: 'deny',
  },
  {
    id: 'merchant-scope',
    eyebrow: 'ataque de merchant',
    title: 'Menor preço fora do escopo',
    detail: 'Uma tarifa tentadora não substitui a autorização explícita do merchant.',
    tone: 'deny',
  },
  {
    id: 'ceiling',
    eyebrow: 'ataque de teto',
    title: 'Executiva para Córdoba · US$900',
    detail: 'O teto fixo continua sendo um limite, mesmo diante de aprovação humana.',
    tone: 'deny',
  },
  {
    id: 'revoked',
    eyebrow: 'ataque após revogação',
    title: 'Tentar depois de encerrar',
    detail: 'Uma revogação bloqueia decisões futuras sem cancelar settlement já concluído.',
    tone: 'escalate',
    requiresRevocation: true,
  },
];

export function AttackScenarios({ mandate }: { mandate: UiMandateProjection | null }) {
  return (
    <section className="attack-scenarios" aria-labelledby="attack-scenarios-title">
      <div className="attack-scenarios__heading">
        <div>
          <p className="eyebrow">Matriz de prova preservada</p>
          <h2 id="attack-scenarios-title">Ataques plausíveis continuam visíveis.</h2>
        </div>
        <p>O BFF atual não publica intenção de compra. Por isso os cartões documentam o comportamento esperado sem disparar APIs de agente pelo browser.</p>
      </div>

      <div className="attack-grid">
        {scenarios.map((scenario) => {
          const revocationObserved = scenario.requiresRevocation && mandate?.status === 'revoked';
          return (
            <article key={scenario.id} className={`attack-card attack-card--${scenario.tone}`}>
              <p className="eyebrow">{scenario.eyebrow}</p>
              <h3>{scenario.title}</h3>
              <p>{scenario.detail}</p>
              <div className="mt-auto pt-3">
                <Badge tone={revocationObserved ? 'verify' : 'neutral'}>
                  {revocationObserved ? 'Revogação observada' : 'Indisponível no BFF'}
                </Badge>
              </div>
            </article>
          );
        })}
      </div>

      <div className="protocol-note">
        <ShieldAlert size={17} aria-hidden="true" />
        <p><strong>Defesas de borda não são teatro de UI.</strong> Assinatura ausente, digest alterado e nonce repetido continuam recusados nas APIs de agente. Esta página não tenta contornar essa fronteira.</p>
        <LockKeyhole size={17} aria-hidden="true" />
        <span><Route size={14} aria-hidden="true" />Um controle só será habilitado quando existir uma intenção equivalente em <code>/ui-api/v1/</code>.</span>
      </div>
    </section>
  );
}
