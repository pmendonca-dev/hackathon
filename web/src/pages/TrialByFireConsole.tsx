import { useState } from 'react';
import { Clock, KeyRound, PlugZap, RefreshCcw, ShieldOff, Wallet } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, Button, EmptyNotice, Panel } from '../components/ui.tsx';
import { LiveFooter } from '../components/LiveFooter.tsx';
import { formatDateTime } from '../utils/format.ts';

/**
 * Everything a judge can do without the team touching anything.
 *
 * The commands are split by *what proves them*, because that separation is the system's
 * central claim. Holder-signed commands move money and are signed in this browser;
 * operator commands run the instance and deliberately cannot move money. A console that
 * mixed them into one list of buttons would hide the one thing worth showing.
 */
export function TrialByFireConsole() {
  const {
    mandates,
    selectedMandateId,
    walletReady,
    operatorAvailable,
    receipts,
    changeLimit,
    revokeSelected,
    revokeEverything,
    setPspMode,
    reconcile,
    advanceClock,
  } = useAval();

  const [newLimit, setNewLimit] = useState('100');
  const [hours, setHours] = useState('24');
  const [busy, setBusy] = useState(false);
  const selected = mandates.find((item) => item.mandate_id === selectedMandateId) ?? null;

  function fire(action: () => Promise<void>) {
    setBusy(true);
    void action().finally(() => setBusy(false));
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Console trial-by-fire</p>
          <h1>Mude o que quiser. O núcleo relê tudo na decisão seguinte.</h1>
          <p>
            Nenhum cache na frente de limite e revogação, e nenhum reinício necessário.
            O efeito aparece na próxima compra que o agente tentar.
          </p>
        </div>
        <Badge tone={selected ? 'allow' : 'neutral'}>{selected?.mandate_id ?? 'SEM MANDATO'}</Badge>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel
          eyebrow="Provado pela chave do titular"
          title="Autoridade de gasto"
          action={<KeyRound size={18} className="text-allow" aria-hidden="true" />}
        >
          <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
            Assinado nesta carteira, no navegador. Nenhum token de operador consegue
            produzir estas assinaturas — é isso que impede quem opera a instância de
            gastar o dinheiro dos outros.
          </p>
          <label className="block">
            <span className="eyebrow">Novo orçamento (USD)</span>
            <input className="form-control" value={newLimit} onChange={(event) => setNewLimit(event.target.value)} />
          </label>
          <div className="mt-3 space-y-2">
            <Button
              className="w-full"
              disabled={busy || !selected || !walletReady}
              onClick={() => fire(() => changeLimit(Math.round(Number(newLimit) * 100)))}
            >
              <Wallet size={13} aria-hidden="true" />Mudar limite (assinado)
            </Button>
            <Button
              variant="danger"
              className="w-full"
              disabled={busy || !selected || !walletReady}
              onClick={() => fire(revokeSelected)}
            >
              <ShieldOff size={13} aria-hidden="true" />Revogar mandato (assinado)
            </Button>
            <Button
              variant="danger"
              className="w-full"
              disabled={busy || !walletReady || mandates.length === 0}
              onClick={() => fire(revokeEverything)}
            >
              <ShieldOff size={13} aria-hidden="true" />Revogar tudo (assinado)
            </Button>
          </div>
        </Panel>

        <Panel
          eyebrow="Provado pelo token de operador"
          title="Operação da instância"
          action={<PlugZap size={18} className="text-hold" aria-hidden="true" />}
        >
          {!operatorAvailable ? (
            <p className="text-[13px] leading-relaxed text-fg-mute">
              Nenhum token de operador configurado nesta sessão. Estes comandos não são
              enviados, e nada é simulado no navegador.
            </p>
          ) : (
            <>
              <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
                Estas superfícies operam a instância e, de propósito, não mexem em
                dinheiro nenhum.
              </p>
              <div className="grid gap-2 sm:grid-cols-3">
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('offline'))}>Processador offline</Button>
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('decline'))}>Processador recusa</Button>
                <Button variant="ghost" disabled={busy} onClick={() => fire(() => setPspMode('online'))}>Processador online</Button>
              </div>
              <Button variant="ghost" className="mt-2 w-full" disabled={busy} onClick={() => fire(reconcile)}>
                <RefreshCcw size={13} aria-hidden="true" />Reconciliar pendências
              </Button>
              <label className="mt-4 block">
                <span className="eyebrow">Avançar relógio (horas)</span>
                <input className="form-control" value={hours} onChange={(event) => setHours(event.target.value)} />
              </label>
              <Button
                variant="ghost"
                className="mt-2 w-full"
                disabled={busy}
                onClick={() => fire(() => advanceClock(Math.round(Number(hours) * 3600)))}
              >
                <Clock size={13} aria-hidden="true" />Avançar e ver expirar
              </Button>
              <p className="safe-note mt-4">
                <Clock size={15} aria-hidden="true" />
                O relógio só avança. Rebobinar reviveria um mandato expirado, e isso
                seria um operador devolvendo autoridade de gasto.
              </p>
            </>
          )}
        </Panel>
      </section>

      <Panel eyebrow="O que o runtime respondeu" title="Recibos desta sessão">
        {receipts.length === 0 ? (
          <EmptyNotice
            title="Nenhum comando ainda"
            body="Cada comando registra aqui o que o runtime respondeu — inclusive quando não respondeu nada."
          />
        ) : (
          <ul className="space-y-2">
            {receipts.map((receipt, index) => (
              <li
                key={index}
                className={`rounded-lg border p-3 ${
                  receipt.outcome === 'accepted'
                    ? 'border-allow/35 bg-allow/6'
                    : receipt.outcome === 'unreachable'
                      ? 'border-hold/40 bg-hold/6'
                      : 'border-deny/35 bg-deny/6'
                }`}
              >
                <div className="flex flex-wrap items-baseline justify-between gap-2">
                  <span className="text-[13px] font-semibold">{receipt.label}</span>
                  <Badge tone={receipt.outcome === 'accepted' ? 'allow' : receipt.outcome === 'unreachable' ? 'hold' : 'deny'}>
                    {receipt.reasonCode ?? receipt.outcome}
                  </Badge>
                </div>
                <p className="mt-1 text-[13px] leading-relaxed text-fg-dim">{receipt.message}</p>
                <p className="mono mt-1 text-[10px] text-fg-faint">{formatDateTime(receipt.at)}</p>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <LiveFooter />
    </div>
  );
}
