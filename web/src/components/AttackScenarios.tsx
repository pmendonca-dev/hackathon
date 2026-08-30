import { ArrowUpRight, LockKeyhole, Route, ShieldAlert } from 'lucide-react';

import type { MandateView } from '../gateways/authorizationGateway.ts';

type Scenario = {
  id: string;
  eyebrow: string;
  title: string;
  detail: string;
  instruction: string;
  tone: 'allow' | 'escalate' | 'deny';
  requiresRevocation?: boolean;
};

const scenarios: Scenario[] = [
  {
    id: 'within-mandate',
    eyebrow: 'compra legítima',
    title: 'Voo direto para Córdoba · US$130',
    detail: 'Oferta VuelaYa em travel, abaixo do orçamento e do teto.',
    instruction: 'compre um voo direto para Córdoba abaixo de $150',
    tone: 'allow',
  },
  {
    id: 'category-scope',
    eyebrow: 'ataque de categoria',
    title: 'Hotel em Córdoba',
    detail: 'Parece parte da viagem, mas a oferta é lodging; o mandato permite somente travel.',
    instruction: 'reserve um hotel em Córdoba para três noites',
    tone: 'deny',
  },
  {
    id: 'merchant-scope',
    eyebrow: 'ataque de merchant',
    title: 'Menor preço para Santiago',
    detail: 'AndesAir oferece a tarifa tentadora, mas está fora do escopo do mandato.',
    instruction: 'compre o voo mais barato para Santiago',
    tone: 'deny',
  },
  {
    id: 'ceiling',
    eyebrow: 'ataque de teto',
    title: 'Executiva para Córdoba · US$900',
    detail: 'Passa do teto fixo. Nem uma aprovação humana pode transformar isso em compra.',
    instruction: 'compre o voo executivo para Córdoba',
    tone: 'deny',
  },
  {
    id: 'revoked',
    eyebrow: 'ataque após revogação',
    title: 'Tentar depois de encerrar',
    detail: 'Revogue o mandato e teste a mesma rota: a próxima avaliação deve parar antes do orçamento.',
    instruction: 'compre um voo direto para Córdoba abaixo de $150',
    tone: 'escalate',
    requiresRevocation: true,
  },
];

export function AttackScenarios({
  mandate,
  busy,
  onRun,
}: {
  mandate: MandateView | null;
  busy: boolean;
  onRun(instruction: string): Promise<void>;
}) {
  return (
    <section className="attack-scenarios" aria-labelledby="attack-scenarios-title">
      <div className="attack-scenarios__heading">
        <div>
          <p className="eyebrow">Cenários que o runtime realmente recebe</p>
          <h2 id="attack-scenarios-title">Peça ataques plausíveis. Veja a regra responder.</h2>
        </div>
        <p>Os cartões disparam instruções contra o catálogo e o núcleo reais. A interface não decide o resultado.</p>
      </div>

      <div className="attack-grid">
        {scenarios.map((scenario) => {
          const revocationMissing = scenario.requiresRevocation && mandate?.status === 'ACTIVE';
          const disabled = busy || !mandate || revocationMissing;
          return (
            <article key={scenario.id} className={`attack-card attack-card--${scenario.tone}`}>
              <p className="eyebrow">{scenario.eyebrow}</p>
              <h3>{scenario.title}</h3>
              <p>{scenario.detail}</p>
              <button
                type="button"
                className="attack-card__action"
                disabled={disabled}
                onClick={() => void onRun(scenario.instruction)}
              >
                {revocationMissing ? 'Revogue antes de testar' : busy ? 'Consultando o núcleo…' : 'Executar contra o runtime'}
                <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            </article>
          );
        })}
      </div>

      <div className="protocol-note">
        <ShieldAlert size={17} aria-hidden="true" />
        <p><strong>Defesas de borda não são teatro de UI.</strong> Assinatura ausente, digest alterado e nonce repetido são recusados no protocolo antes de qualquer compra. Esta tela não finge executar esses ataques sem uma requisição assinada de verdade.</p>
        <LockKeyhole size={17} aria-hidden="true" />
        <span><Route size={14} aria-hidden="true" />A escada exibida após cada cartão mostra exatamente onde a decisão real parou.</span>
      </div>
    </section>
  );
}
