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
    eyebrow: 'legitimate purchase',
    title: 'Nonstop to Córdoba · under $150',
    detail: 'A VuelaYa travel offer, inside both the budget and the per-purchase ceiling.',
    instruction: 'buy a nonstop flight to Córdoba under $150',
    tone: 'allow',
  },
  {
    id: 'category-scope',
    eyebrow: 'category attack',
    title: 'A hotel in Córdoba',
    detail: 'It reads like part of the trip, but the offer is lodging; the mandate allows travel only.',
    instruction: 'book a hotel in Córdoba for three nights',
    tone: 'deny',
  },
  {
    id: 'merchant-scope',
    eyebrow: 'merchant attack',
    title: 'Lowest fare to Santiago',
    detail: 'AndesAir has the tempting price, and is a seller the mandate never named.',
    instruction: 'buy the cheapest flight to Santiago',
    tone: 'deny',
  },
  {
    id: 'ceiling',
    eyebrow: 'ceiling attack',
    title: 'Business class to Córdoba · $900',
    detail: 'Past the fixed ceiling. Not even a human approval can turn this into a purchase.',
    instruction: 'buy the business class flight to Córdoba',
    tone: 'deny',
  },
  {
    id: 'revoked',
    eyebrow: 'attack after revocation',
    title: 'Try again after shutting it down',
    detail: 'Revoke the mandate, then run the same route: the next evaluation must stop before the budget.',
    instruction: 'buy a nonstop flight to Córdoba under $150',
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
          <p className="eyebrow">Scenarios the runtime actually receives</p>
          <h2 id="attack-scenarios-title">Ask for plausible attacks. Watch the rule answer.</h2>
        </div>
        <p>These cards fire instructions at the real catalogue and the real core. The interface does not decide the outcome.</p>
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
                {revocationMissing ? 'Revoke it first' : busy ? 'Asking the core…' : 'Run it against the runtime'}
                <ArrowUpRight size={14} aria-hidden="true" />
              </button>
            </article>
          );
        })}
      </div>

      <div className="protocol-note">
        <ShieldAlert size={17} aria-hidden="true" />
        <p><strong>Edge defences are not UI theatre.</strong> A missing signature, an altered digest and a replayed nonce are refused at the protocol, before any purchase exists. This screen will not pretend to run those attacks without a genuinely signed request.</p>
        <LockKeyhole size={17} aria-hidden="true" />
        <span><Route size={14} aria-hidden="true" />The ladder below each card shows exactly where the real decision stopped.</span>
      </div>
    </section>
  );
}
