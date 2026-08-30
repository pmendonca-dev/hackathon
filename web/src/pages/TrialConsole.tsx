import { useState, type FormEvent } from 'react';
import { AlertTriangle, ArrowRight, LockKeyhole, RadioTower } from 'lucide-react';

import type { DataSource, TrialCommandKind, TrialCommandReceipt } from '../contracts/avalGateway.ts';
import { Badge, Button, Field, Panel } from '../components/ui.tsx';
import { safeDisplayText } from '../utils/safePresentation.ts';

const commands: Array<{ kind: TrialCommandKind; label: string; hint: string; placeholder: string }> = [
  { kind: 'lower-limit', label: 'Reduzir limite', hint: 'API administrativa não publicada.', placeholder: 'indisponível' },
  { kind: 'change-scope', label: 'Alterar escopo', hint: 'API administrativa não publicada.', placeholder: 'indisponível' },
  { kind: 'budget-zero', label: 'Zerar orçamento', hint: 'API administrativa não publicada.', placeholder: 'indisponível' },
  { kind: 'revoke-mandate', label: 'Revogar mandato', hint: 'Enviar uma revogação assinada pela autoridade registrada.', placeholder: 'Cole a revogação assinada' },
];

export function TrialConsole({
  mandateId,
  dataSource,
  receipt,
  onSubmit,
}: {
  mandateId: string;
  dataSource: DataSource;
  receipt: TrialCommandReceipt | null;
  onSubmit(command: { kind: TrialCommandKind; targetId: string; requestedValue: string }): Promise<void>;
}) {
  const [kind, setKind] = useState<TrialCommandKind>('revoke-mandate');
  const [targetId, setTargetId] = useState(mandateId);
  const [requestedValue, setRequestedValue] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const selected = commands.find((command) => command.kind === kind) ?? commands[0];
  const commandAvailable = dataSource === 'api' && kind === 'revoke-mandate';

  async function submit(event: FormEvent) {
    event.preventDefault();
    if (!commandAvailable) return;
    setSubmitting(true);
    try {
      await onSubmit({ kind, targetId, requestedValue });
    } finally {
      setRequestedValue('');
      setSubmitting(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Console trial-by-fire</p>
          <h1>Formule a intervenção. O core decide o efeito.</h1>
          <p>Somente a revogação assinada possui API publicada. Os demais comandos permanecem indisponíveis e não geram mudança local.</p>
        </div>
        <Badge tone={dataSource === 'api' ? 'verify' : 'escalate'}>{dataSource === 'api' ? 'API REAL' : 'INDISPONÍVEL'}</Badge>
      </header>

      <div role="note" className={`flex gap-3 rounded-2xl border p-4 ${dataSource === 'api' ? 'border-verify/40 bg-verify/8 text-verify' : 'border-escalate/40 bg-escalate/8 text-escalate'}`}>
        <AlertTriangle className="mt-0.5 shrink-0" size={18} aria-hidden="true" />
        <p className="text-[13px] leading-relaxed">
          {dataSource === 'api'
            ? <><strong>Efeito real.</strong> O JWS é enviado com autenticação de sessão e idempotência; depois da resposta, a tela recarrega o estado canônico.</>
            : <><strong>Dados mock.</strong> Comandos administrativos estão indisponíveis e nenhum sucesso será simulado.</>}
        </p>
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
                  setRequestedValue('');
                }}
                className={`w-full rounded-xl border p-3.5 text-left transition-colors ${kind === command.kind ? 'border-allow/50 bg-allow/8' : 'border-line bg-ink-800/50 hover:border-line-hi'}`}
              >
                <span className="flex items-center justify-between gap-2 text-[13px] font-semibold">
                  {command.label}
                  {dataSource === 'api' && command.kind === 'revoke-mandate'
                    ? <ArrowRight size={14} className={kind === command.kind ? 'text-allow' : 'text-fg-mute'} aria-hidden="true" />
                    : <Badge tone="neutral">indisponível</Badge>}
                </span>
                <span className="mt-1 block text-[12px] leading-relaxed text-fg-mute">{command.hint}</span>
              </button>
            ))}
          </div>
        </Panel>

        <Panel eyebrow="Boundary de comando" title={selected.label} action={<LockKeyhole size={18} className={commandAvailable ? 'text-verify' : 'text-fg-mute'} aria-hidden="true" />}>
          <form onSubmit={(event) => void submit(event)} className="space-y-4">
            <label className="block">
              <span className="eyebrow">Alvo canônico</span>
              <input className="form-control" value={targetId} onChange={(event) => setTargetId(event.target.value)} required disabled={!commandAvailable} />
            </label>
            <label className="block">
              <span className="eyebrow">Revogação assinada (JWS)</span>
              <input
                className="form-control"
                type="password"
                autoComplete="off"
                spellCheck={false}
                value={requestedValue}
                onChange={(event) => setRequestedValue(event.target.value)}
                placeholder={selected.placeholder}
                required
                disabled={!commandAvailable}
              />
            </label>
            <div className="rounded-xl border border-line bg-ink-800/60 p-3.5">
              <p className="eyebrow">Endpoint publicado</p>
              <code className="mono mt-2 block break-all text-[11px] leading-relaxed text-fg-dim">{commandAvailable ? `POST /mandates/${targetId}/revocations` : 'API administrativa não publicada para este comando'}</code>
            </div>
            <Button type="submit" disabled={!commandAvailable || submitting || !requestedValue.trim()} className="w-full sm:w-auto">
              <RadioTower size={14} aria-hidden="true" />{submitting ? 'Enviando revogação' : commandAvailable ? 'Revogar no runtime' : 'Comando indisponível'}
            </Button>
          </form>
        </Panel>
      </section>

      <Panel eyebrow="Resultado da boundary" title="Resposta sem inferência local">
        {receipt ? (
          <dl>
            <Field label="Request ID">{safeDisplayText(receipt.requestId)}</Field>
            <Field label="Origem">{receipt.dataSource}</Field>
            <Field label="Resultado">{receipt.outcome}</Field>
            <Field label="Estado alterado">{receipt.canonicalStateChanged ? 'sim' : 'não'}</Field>
            <Field label="Effective at">{receipt.effectiveAt ?? 'não informado pela API'}</Field>
            <Field label="Mensagem" mono={false}>{safeDisplayText(receipt.message)}</Field>
          </dl>
        ) : (
          <p className="py-5 text-center text-[13px] text-fg-mute">Nenhum comando real foi executado nesta sessão.</p>
        )}
      </Panel>
    </div>
  );
}
