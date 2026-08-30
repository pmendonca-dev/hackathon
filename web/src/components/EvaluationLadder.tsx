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
  mandate_exists: 'Mandate exists',
  revocation_readable: 'Revocation readable',
  mandate_not_revoked: 'Not revoked',
  merchant_not_revoked: 'Merchant not revoked',
  instrument_not_revoked: 'Instrument not revoked',
  instrument_in_mandate: 'Instrument named by the mandate',
  reservation_slot_free: 'A reservation slot is free',
  budget_not_zeroed: 'Budget not zeroed',
  mandate_not_expired: 'Still within validity',
  merchant_in_scope: 'Merchant in scope',
  category_in_scope: 'Category in scope',
  money_unit_matches: 'Currency and scale agree',
  amount_positive: 'Amount positive',
  below_ceiling: 'Below the ceiling',
  within_usage_window: 'Within the frequency limit',
  within_budget: 'Within the budget',
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
  'instrument_in_mandate',
  'money_unit_matches',
  'amount_positive',
  'below_ceiling',
  'reservation_slot_free',
  'within_usage_window',
  'within_budget',
];

const AUTHORITY_RUNGS = 6;

export function EvaluationLadder({ trace }: { trace: EvaluationStep[] }) {
  if (trace.length === 0) {
    return (
      <p className="text-[13px] leading-relaxed text-fg-mute">
        No evaluation in this session yet. Ask the agent for a purchase to see the ladder.
      </p>
    );
  }

  const walked = new Map(trace.map((step) => [step.check, step]));
  // Conditional rungs (frequency, instrument) only exist on mandates that carry them,
  // so an unwalked one is only drawn when the ladder actually reached that far.
  const stoppedAt = trace.length;
  const rows = FULL_ORDER.filter(
    (check) =>
      walked.has(check)
      || (check !== 'within_usage_window' && check !== 'instrument_in_mandate' && stoppedAt > 0),
  );

  return (
    <>
      <ol className="space-y-px" aria-label="The order the core evaluates in">
        {rows.map((check, index) => {
          const step = walked.get(check);
          const state = step === undefined ? 'skipped' : step.passed ? 'passed' : 'failed';
          const boundary = index === AUTHORITY_RUNGS;
          return (
            <li key={check}>
              {boundary && (
                <p className="eyebrow px-3 pt-4 pb-2 text-fg-faint">
                  ── above: authority · below: money ──
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
                        ? ' — passed'
                        : state === 'failed'
                          ? ' — failed, the evaluation stopped here'
                          : ' — never evaluated'}
                    </span>
                  </span>
                  {step?.detail && (
                    <span className="mono mt-0.5 block text-[11px] leading-relaxed text-fg-mute">
                      {step.detail}
                    </span>
                  )}
                  {state === 'skipped' && (
                    <span className="mono mt-0.5 block text-[11px] text-fg-faint">
                      never consulted
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
        A greyed rung is not a missing rule: it is a rule the core never needed to
        consult, because it already had an answer further up.
      </p>
    </>
  );
}
