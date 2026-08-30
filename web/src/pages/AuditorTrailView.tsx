import { useState } from 'react';
import { Link2, Link2Off, PenLine, Scale, ScrollText, ShieldAlert } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, Button, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, shortHash } from '../utils/format.ts';

/**
 * The trail, and the demonstration that it catches its own editor.
 *
 * The tamper control is the point of this screen. A log everybody promises not to edit
 * proves nothing; this one is re-hashed on every read, so an edit is caught by the
 * chain rather than by anybody's word. The button is only offered when the runtime was
 * started with the demo flag — its absence is the normal state.
 */
export function AuditorTrailView() {
  const { auditorEntries, chain, disputes, selectedMandateId, tamperLedger, operatorAvailable } =
    useAval();
  const [sequence, setSequence] = useState('1');
  const [busy, setBusy] = useState(false);

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do auditor</p>
          <h1>A trilha se verifica sozinha, sem confiar em quem a guarda.</h1>
          <p>
            Cada evento canonicaliza a si mesmo e encadeia o digest do anterior. Editar
            qualquer linha quebra o próprio digest e todos os elos seguintes.
          </p>
        </div>
        <Badge tone={chain?.intact === false ? 'deny' : 'verify'}>
          {chain === null ? 'SEM CADEIA' : chain.intact ? 'CADEIA ÍNTEGRA' : 'CADEIA QUEBRADA'}
        </Badge>
      </header>

      {chain?.intact === false && (
        <div role="alert" className="flex gap-3 rounded-2xl border border-deny/45 bg-deny/8 p-4 text-deny">
          <ShieldAlert className="mt-0.5 shrink-0" size={18} aria-hidden="true" />
          <p className="text-[13px] leading-relaxed">
            <strong>Adulteração detectada na posição {chain.broken_at}.</strong> O registro
            gravado não corresponde mais ao digest tirado sobre ele no momento da escrita.
            Nenhuma pessoa precisou notar isso — a verificação é aritmética.
          </p>
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1.4fr_0.6fr]">
        <Panel eyebrow="Cadeia de hash" title={`${auditorEntries.length} evento(s)`} action={<ScrollText size={18} className="text-verify" aria-hidden="true" />}>
          {auditorEntries.length === 0 ? (
            <EmptyNotice title="Nada registrado" body="Selecione um mandato com atividade para ler a trilha." />
          ) : (
            <ol className="space-y-2">
              {auditorEntries.map((entry) => {
                const broken = chain?.broken_at !== null && chain?.broken_at === entry.sequence;
                return (
                  <li
                    key={String(entry.sequence)}
                    className={`rounded-lg border p-3 ${broken ? 'border-deny/50 bg-deny/8' : 'border-line bg-ink-800/40'}`}
                  >
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="flex items-center gap-2">
                        {broken ? (
                          <Link2Off size={13} className="text-deny" aria-hidden="true" />
                        ) : (
                          <Link2 size={13} className="text-verify" aria-hidden="true" />
                        )}
                        <span className="mono text-[11px] text-fg-mute">#{String(entry.sequence)}</span>
                        <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                      </span>
                      <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                    {typeof entry.sha256 === 'string' && (
                      <p className="mono mt-1 text-[10px] text-fg-faint">{shortHash(entry.sha256)}</p>
                    )}
                  </li>
                );
              })}
            </ol>
          )}
        </Panel>

        <div className="space-y-4">
          <Panel
            eyebrow="Arbitragem"
            title="Quem responde, derivado da trilha"
            action={<Scale size={18} className="text-hold" aria-hidden="true" />}
          >
            {disputes.length === 0 ? (
              <EmptyNotice
                title="Nenhuma disputa"
                body="Quando uma compra é negada, o veredito aparece aqui com as linhas que o sustentam."
              />
            ) : (
              <ul className="space-y-3">
                {disputes.map((dispute) => (
                  <li key={dispute.id} className="rounded-xl border border-line bg-ink-850/70 p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="mono text-[11px] text-hold">{dispute.reservation_id}</span>
                      <Badge tone={dispute.liability.liable_party === 'holder' ? 'deny' : 'allow'}>
                        {dispute.liability.verdict}
                      </Badge>
                    </div>
                    <p className="mt-1 text-[12px] text-fg-mute">
                      responde: {dispute.liability.liable_party}
                    </p>
                    {/* The verdict is not stored. It is recomputed from append-only
                        evidence on every read, and these are the exact lines it read —
                        a conclusion nobody has to take on faith. */}
                    <ul className="mt-2 space-y-1">
                      {dispute.liability.basis.map((line, index) => (
                        <li key={index} className="text-[12px] leading-relaxed text-fg-mute">
                          · {line}
                        </li>
                      ))}
                    </ul>
                    <p className="mt-2 flex flex-wrap items-center gap-2">
                      <Badge
                        tone={dispute.liability.mandate_repudiation === 'refuted' ? 'verify' : 'hold'}
                      >
                        repudiação: {dispute.liability.mandate_repudiation}
                      </Badge>
                      {dispute.liability.holder_signatures.map((signature) => (
                        <span key={signature.kid + signature.kind} className="mono text-[10px] text-fg-faint">
                          <PenLine size={11} aria-hidden="true" /> {signature.kind} · {signature.kid}
                        </span>
                      ))}
                    </p>
                  </li>
                ))}
              </ul>
            )}
            <p className="safe-note mt-4">
              <Scale size={15} aria-hidden="true" />
              O mandato nasce assinado pela chave do titular, e essa assinatura é a
              posição 0 desta cadeia. É ela que responde a um “eu nunca criei esse
              mandato” sem depender de nada que a pessoa tenha feito depois.
            </p>
          </Panel>

          <Panel eyebrow="Verificação" title="Estado da cadeia">
            <dl>
              <Field label="Mandato">{selectedMandateId ?? '—'}</Field>
              <Field label="Elos conferidos">{chain?.checked ?? 0}</Field>
              <Field label="Quebra em">{chain?.broken_at ?? 'nenhuma'}</Field>
            </dl>
          </Panel>

          <Panel eyebrow="Prova ao vivo" title="Quebre um elo você mesmo">
            {!operatorAvailable ? (
              <p className="text-[13px] leading-relaxed text-fg-mute">
                Exige token de operador. Sem ele o comando não é enviado — e nada é
                simulado localmente.
              </p>
            ) : (
              <>
                <p className="mb-3 text-[13px] leading-relaxed text-fg-mute">
                  Reescreve o autor de um evento e recanonicaliza. A linha continua bem
                  formada; é o digest que denuncia.
                </p>
                <label className="block">
                  <span className="eyebrow">Sequência</span>
                  <input className="form-control" value={sequence} onChange={(event) => setSequence(event.target.value)} />
                </label>
                <Button
                  variant="danger"
                  className="mt-3 w-full"
                  disabled={busy || !selectedMandateId}
                  onClick={() => {
                    setBusy(true);
                    void tamperLedger(Number(sequence)).finally(() => setBusy(false));
                  }}
                >
                  <ShieldAlert size={13} aria-hidden="true" />Adulterar evento
                </Button>
                <p className="safe-note mt-4">
                  <ShieldAlert size={15} aria-hidden="true" />
                  Esta rota só existe quando o runtime sobe com AVAL_DEMO_TAMPER. Não há
                  contrapartida que conserte a cadeia.
                </p>
              </>
            )}
          </Panel>
        </div>
      </section>
    </div>
  );
}
