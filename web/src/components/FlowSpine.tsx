import { Bot, FileSignature, ShieldCheck, UserCheck, CreditCard, Server, Store } from 'lucide-react';
import type { LucideIcon } from 'lucide-react';
import { FLOW_STAGES } from '../domain/store';
import type { Flow, FlowState } from '../domain/store';
import { toneFor, toneBg, toneText, Badge } from './ui';

const ICONS: LucideIcon[] = [Bot, FileSignature, ShieldCheck, UserCheck, CreditCard, Server, Store];

/**
 * The pipeline, drawn once. Numbering is used here because the stages really
 * are an ordered sequence: stage 3 cannot run before stage 2, and the whole
 * argument of the product is that no stage can be skipped.
 */
export function FlowSpine({ flow }: { flow: Flow }) {
  const tone = toneFor(flow.state === 'IDLE' ? '' : flow.state);

  return (
    <div className="authority-glow">
      <div className="grid-etch">
        <div className="flex flex-col gap-6 px-5 py-7 sm:px-8">
          {/* Stage rail */}
          <ol className="flex items-stretch gap-0 overflow-x-auto pb-1">
            {FLOW_STAGES.map((label, i) => {
              const Icon = ICONS[i];
              const reached = i <= flow.stage;
              const current = i === flow.stage;
              const halted = current && (flow.state === 'DENIED' || flow.state === 'ESCALATED');
              const held = current && (flow.state === 'IN_DOUBT' || flow.state === 'CONFIRMING');

              const ring = halted
                ? flow.state === 'DENIED'
                  ? 'border-deny/60 bg-deny/10'
                  : 'border-escalate/60 bg-escalate/10'
                : held
                  ? 'border-hold/60 bg-hold/10'
                  : reached
                    ? 'border-allow/45 bg-allow/8'
                    : 'border-line bg-ink-800';

              const ink = halted
                ? flow.state === 'DENIED'
                  ? 'text-deny'
                  : 'text-escalate'
                : held
                  ? 'text-hold'
                  : reached
                    ? 'text-allow'
                    : 'text-fg-faint';

              return (
                <li key={label} className="flex min-w-0 flex-1 items-start">
                  <div className="flex min-w-[86px] flex-1 flex-col items-center gap-2.5 text-center">
                    <div
                      className={`relative flex size-11 items-center justify-center rounded-xl border transition-all duration-500 ${ring} ${
                        current ? 'scale-110' : ''
                      }`}
                    >
                      <Icon size={17} className={`${ink} transition-colors`} strokeWidth={1.75} />
                      {current && (
                        <span
                          className={`anim-pulse absolute inset-0 rounded-xl ${ink}`}
                          style={{ backgroundColor: 'transparent' }}
                        />
                      )}
                    </div>
                    <div className="min-w-0">
                      <div className="mono text-[9px] text-fg-faint">
                        {String(i + 1).padStart(2, '0')}
                      </div>
                      <div
                        className={`text-[11px] leading-tight font-medium ${
                          reached ? 'text-fg-dim' : 'text-fg-faint'
                        }`}
                      >
                        {label}
                      </div>
                    </div>
                  </div>

                  {i < FLOW_STAGES.length - 1 && (
                    <div className="relative mt-[21px] h-px w-full min-w-3 shrink overflow-hidden bg-line">
                      <span
                        className={`absolute inset-y-0 left-0 transition-all duration-700 ${
                          i < flow.stage ? 'w-full' : 'w-0'
                        } ${halted ? toneBg[tone] : 'bg-allow/55'}`}
                      />
                    </div>
                  )}
                </li>
              );
            })}
          </ol>

          {/* State chain: AUTHORIZED -> CONFIRMING -> SETTLED */}
          <StateChain state={flow.state} />
        </div>
      </div>
    </div>
  );
}

const CHAIN: FlowState[] = ['AUTHORIZED', 'CONFIRMING', 'SETTLED'];

function StateChain({ state }: { state: FlowState }) {
  // Off-chain terminal states replace the chain rather than sitting inside it:
  // a denied payment never entered it, and one in doubt has left it.
  if (state === 'DENIED' || state === 'ESCALATED' || state === 'IN_DOUBT' || state === 'IDLE') {
    const copy: Record<string, string> = {
      DENIED: 'Refused at the gate. No reservation was ever committed.',
      ESCALATED: 'Held for a human signature. Nothing moves until it is given.',
      IN_DOUBT: 'No definitive processor response. Budget reserved, delivery blocked.',
      IDLE: 'No transaction in flight.',
    };
    return (
      <div className="flex flex-wrap items-center justify-center gap-3 border-t border-line pt-5">
        <Badge tone={toneFor(state)} dot>
          {state === 'IDLE' ? 'NO ACTIVITY' : state}
        </Badge>
        <p className="text-[12px] text-fg-mute">{copy[state]}</p>
      </div>
    );
  }

  const idx = CHAIN.indexOf(state);
  return (
    <div className="flex flex-wrap items-center justify-center gap-2 border-t border-line pt-5">
      {CHAIN.map((s, i) => {
        const done = i < idx;
        const current = i === idx;
        return (
          <div key={s} className="flex items-center gap-2">
            <span
              className={`mono rounded-full border px-3 py-1 text-[10px] font-semibold tracking-widest transition-all ${
                current
                  ? s === 'CONFIRMING'
                    ? 'border-hold/50 bg-hold/12 text-hold'
                    : 'border-allow/50 bg-allow/12 text-allow'
                  : done
                    ? 'border-line bg-transparent text-fg-mute'
                    : 'border-line/60 bg-transparent text-fg-faint'
              }`}
            >
              {s}
            </span>
            {i < CHAIN.length - 1 && (
              <span className={`text-xs ${i < idx ? toneText['allow'] : 'text-fg-faint'}`}>→</span>
            )}
          </div>
        );
      })}
    </div>
  );
}
