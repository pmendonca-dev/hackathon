import { useState, type FormEvent } from 'react';
import { AlertTriangle, ArrowRight, LockKeyhole, RadioTower } from 'lucide-react';

import type { TrialCommandKind, TrialCommandReceipt } from '../contracts/avalGateway.ts';
import { Badge, Button, Field, Panel } from '../components/ui.tsx';

const commands: Array<{ kind: TrialCommandKind; label: string; hint: string; placeholder: string }> = [
  { kind: 'lower-limit', label: 'Reduzir limite', hint: 'Pedir ao core um limite menor para decisões futuras.', placeholder: '15000 minor units' },
  { kind: 'change-scope', label: 'Alterar escopo', hint: 'Remover merchant ou categoria da autoridade viva.', placeholder: 'remove:merchant:nauta-suprimentos' },
  { kind: 'budget-zero', label: 'Zerar orçamento', hint: 'Pedir budget:zero sem recalcular saldo no browser.', placeholder: 'budget:zero' },
  { kind: 'revoke-mandate', label: 'Revogar mandato', hint: 'Enviar uma revogação pela autoridade registrada.', placeholder: 'revoked' },
];

export function TrialConsole({
  mandateId,
  receipt,
  onSubmit,
}: {
  mandateId: string;
  receipt: TrialCommandReceipt | null;
  onSubmit(command: { kind: TrialCommandKind; targetId: string; requestedValue: string }): Promise<void>;
}) {
  const [kind, setKind] = useState<TrialCommandKind>('lower-limit');
  const [targetId, setTargetId] = useState(mandateId);
  const [requestedValue, setRequestedValue] = useState('15000');
  const [submitting, setSubmitting] = useState(false);
  const selected = commands.find((command) => command.kind === kind) ?? commands[0];

  async function submit(event: FormEvent) {
    event.preventDefault();
    setSubmitting(true);
    try {
      await onSubmit({ kind, targetId, requestedValue });
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Console trial-by-fire</p>
          <h1>Formule a intervenção. O core decide o efeito.</h1>
          <p>Esta boundary continua em fixture porque o contrato integrado cobre checkout, não administração; ela não altera política, revogação, saldo ou captura.</p>
        </div>
        <Badge tone="escalate">fixture-only</Badge>
      </header>

      <div role="note" className="flex gap-3 rounded-2xl border border-escalate/40 bg-escalate/8 p-4 text-escalate">
        <AlertTriangle className="mt-0.5 shrink-0" size={18} aria-hidden="true" />
        <p className="text-[13px] leading-relaxed"><strong>Mock explícito.</strong> Nenhum endpoint, PSP ou rede é chamado. Um futuro handoff de administração substituirá somente a implementação de <span className="mono">AvalGateway</span>.</p>
      </div>

      <section className="grid gap-4 lg:grid-cols-[0.75fr_1.25fr]">
        <Panel eyebrow="Intervenções preparadas" title="Escolha um comando">
          <div className="space-y-2" role="list">
            {commands.map((command) => (
              <button
                key={command.kind}
                type="button"
                onClick={() => {
                  setKind(command.kind);
                  setRequestedValue(command.kind === 'budget-zero' ? 'budget:zero' : command.kind === 'revoke-mandate' ? 'revoked' : '');
                }}
                className={`w-full rounded-xl border p-3.5 text-left transition-colors ${kind === command.kind ? 'border-allow/50 bg-allow/8' : 'border-line bg-ink-800/50 hover:border-line-hi'}`}
              >
                <span className="flex items-center justify-between gap-2 text-[13px] font-semibold">{command.label}<ArrowRight size={14} className={kind === command.kind ? 'text-allow' : 'text-fg-mute'} aria-hidden="true" /></span>
                <span className="mt-1 block text-[12px] leading-relaxed text-fg-mute">{command.hint}</span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel eyebrow="Boundary de comando" title={selected.label} action={<LockKeyhole size={18} className="text-verify" aria-hidden="true" />}>
          <form onSubmit={(event) => void submit(event)} className="space-y-4">
            <label className="block">
              <span className="eyebrow">Alvo canônico</span>
              <input className="form-control" value={targetId} onChange={(event) => setTargetId(event.target.value)} required />
            </label>
            <label className="block">
              <span className="eyebrow">Valor solicitado</span>
              <input className="form-control" value={requestedValue} onChange={(event) => setRequestedValue(event.target.value)} placeholder={selected.placeholder} required />
            </label>
            <div className="rounded-xl border border-line bg-ink-800/60 p-3.5">
              <p className="eyebrow">Contrato futuro</p>
              <code className="mono mt-2 block break-all text-[11px] leading-relaxed text-fg-dim">{JSON.stringify({ kind, targetId, requestedValue })}</code>
            </div>
            <Button type="submit" disabled={submitting || !requestedValue.trim()} className="w-full sm:w-auto">
              <RadioTower size={14} aria-hidden="true" />{submitting ? 'Enviando intenção' : 'Enviar à boundary'}
            </Button>
          </form>
        </Panel>
      </section>

      <Panel eyebrow="Resultado da boundary" title="Resposta sem inferência local">
        {receipt ? (
          <dl>
            <Field label="Request ID">{receipt.requestId}</Field>
            <Field label="Origem">{receipt.dataSource}</Field>
            <Field label="Resultado">{receipt.outcome}</Field>
            <Field label="Estado alterado">{receipt.canonicalStateChanged ? 'sim' : 'não'}</Field>
            <Field label="Effective at">{receipt.effectiveAt ?? 'não aplicável na fixture'}</Field>
            <Field label="Mensagem" mono={false}>{receipt.message}</Field>
          </dl>
        ) : (
          <p className="py-5 text-center text-[13px] text-fg-mute">Envie uma intenção para inspecionar o envelope de resposta mock.</p>
        )}
      </Panel>
    </div>
  );
}

