import { Check, Minus, X } from 'lucide-react';

import type { EvaluationStep } from '../gateways/authorizationGateway.ts';

/**
 * The ladder the core walked, drawn in the order it walked it.
 *
 * This is the argument the whole system makes, made visible: authority is checked
 * before money, so a refusal that stops at `mandate_not_revoked` never reached the
 * budget at all. The rungs the core never ran are drawn greyed rather than omitted —
 * seeing where the ladder *stopped* is the point, and a list that silently ended
 * would read as a shorter rulebook instead of an earlier answer.
 */

const LABELS: Record<string, string> = {
  mandate_exists: 'Mandato existe',
  revocation_readable: 'Revogação legível',
  mandate_not_revoked: 'Não revogado',
  merchant_not_revoked: 'Merchant não revogado',
  instrument_not_revoked: 'Instrumento não revogado',
  budget_not_zeroed: 'Orçamento não zerado',
  mandate_not_expired: 'Dentro da validade',
  merchant_in_scope: 'Merchant no escopo',
  category_in_scope: 'Categoria no escopo',
  money_unit_matches: 'Moeda e escala conferem',
  amount_positive: 'Valor positivo',
  below_ceiling: 'Abaixo do teto',
  within_usage_window: 'Dentro da frequência',
  within_budget: 'Dentro do orçamento',
};

/** The full order, so a stopped ladder still shows what it never reached. */
const FULL_ORDER = [
  'mandate_exists',
  'revocation_readable',
  'mandate_not_revoked',
  'merchant_not_revoked',
  'budget_not_zeroed',
  'mandate_not_expired',
  'merchant_in_scope',
  'category_in_scope',
  'money_unit_matches',
  'amount_positive',
  'below_ceiling',
  'within_usage_window',
  'within_budget',
];

const AUTHORITY_RUNGS = 6;

export function EvaluationLadder({ trace }: { trace: EvaluationStep[] }) {
  if (trace.length === 0) {
    return (
      <p className="text-[13px] leading-relaxed text-fg-mute">
        Nenhuma avaliação nesta sessão. Peça uma compra ao agente para ver a escada.
      </p>
    );
  }

  const walked = new Map(trace.map((step) => [step.check, step]));
  // Conditional rungs (frequency, instrument) only exist on mandates that carry them,
  // so an unwalked one is only drawn when the ladder actually reached that far.
  const stoppedAt = trace.length;
  const rows = FULL_ORDER.filter(
    (check) => walked.has(check) || (check !== 'within_usage_window' && stoppedAt > 0),
  );

  return (
    <>
      <ol className="space-y-px" aria-label="Ordem de avaliação do núcleo">
        {rows.map((check, index) => {
          const step = walked.get(check);
          const state = step === undefined ? 'skipped' : step.passed ? 'passed' : 'failed';
          const boundary = index === AUTHORITY_RUNGS;
          return (
            <li key={check}>
              {boundary && (
                <p className="eyebrow px-3 pt-4 pb-2 text-fg-faint">
                  ── acima: autoridade · abaixo: dinheiro ──
                </p>
              )}
              <div
                className={`flex items-start gap-3 rounded-lg px-3 py-2 ${
                  state === 'failed'
                    ? 'bg-deny/10'
                    : state === 'skipped'
                      ? 'opacity-40'
                      : 'bg-allow/5'
                }`}
              >
                <span className="mt-0.5 shrink-0" aria-hidden="true">
                  {state === 'passed' && <Check size={14} className="text-allow" />}
                  {state === 'failed' && <X size={14} className="text-deny" />}
                  {state === 'skipped' && <Minus size={14} className="text-fg-faint" />}
                </span>
                <span className="min-w-0 flex-1">
                  <span
                    className={`block text-[13px] font-medium ${
                      state === 'failed' ? 'text-deny' : state === 'skipped' ? 'text-fg-faint' : 'text-fg'
                    }`}
                  >
                    {LABELS[check] ?? check}
                    <span className="sr-only">
                      {state === 'passed'
                        ? ' — aprovado'
                        : state === 'failed'
                          ? ' — reprovado, a avaliação parou aqui'
                          : ' — não avaliado'}
                    </span>
                  </span>
                  {step?.detail && (
                    <span className="mono mt-0.5 block text-[11px] leading-relaxed text-fg-mute">
                      {step.detail}
                    </span>
                  )}
                  {state === 'skipped' && (
                    <span className="mono mt-0.5 block text-[11px] text-fg-faint">
                      nunca consultado
                    </span>
                  )}
                </span>
              </div>
            </li>
          );
        })}
      </ol>
      <p className="safe-note mt-4">
        <Check size={15} aria-hidden="true" />
        Um degrau cinza não é uma regra ausente: é uma regra que o núcleo não precisou
        consultar, porque já tinha uma resposta acima dela.
      </p>
    </>
  );
}
