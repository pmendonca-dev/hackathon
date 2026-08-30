import { useMemo, useState, type FormEvent } from 'react';
import { Clock, Eye, KeyRound, Send, ShieldOff, Sparkles } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { EvaluationLadder } from '../components/EvaluationLadder.tsx';
import { Badge, Button, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, formatMoney } from '../utils/format.ts';

const MONTH_SECONDS = 30 * 24 * 3600;

/**
 * A default validity dated from the runtime, never from this laptop.
 *
 * The demo clock only moves forward, and a judge is invited to move it. A form that
 * dated itself here would then propose an instant the server has already passed, and
 * every mandate created after that trial-by-fire step would be refused as expired —
 * a failure the judge caused without being able to see why.
 */
function defaultExpiry(serverNow: string | null): string {
  const base = serverNow ? new Date(serverNow) : new Date();
  const valid = new Date(base.getTime() + MONTH_SECONDS * 1000);
  return `${valid.toISOString().slice(0, 19)}Z`;
}

export function HolderView() {
  const {
    mandates,
    selectedMandateId,
    selectMandate,
    escalations,
    lastRun,
    humanEntries,
    holderKid,
    walletReady,
    watches,
    serverNow,
    createMandate,
    runAgent,
    watchInstruction,
    tickWatches,
    decideEscalation,
    revokeSelected,
    revokeEverything,
  } = useAval();

  const [instruction, setInstruction] = useState('compre um voo para Córdoba abaixo de $150');
  const [busy, setBusy] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const selected = mandates.find((item) => item.mandate_id === selectedMandateId) ?? null;
  const expiryDefault = useMemo(() => defaultExpiry(serverNow), [serverNow]);

  async function guard(action: () => Promise<void>) {
    setBusy(true);
    try {
      await action();
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do titular</p>
          <h1>A autoridade que eu dei, e tudo o que foi feito com ela.</h1>
          <p>
            A chave que assina revogação, limite e aprovação foi gerada neste navegador e
            nunca sai dele. O servidor conhece apenas a metade pública.
          </p>
        </div>
        <Badge tone={walletReady ? 'verify' : 'escalate'}>
          {walletReady ? 'CARTEIRA PRONTA' : 'SEM CARTEIRA'}
        </Badge>
      </header>

      {!walletReady && (
        <div role="alert" className="rounded-2xl border border-escalate/40 bg-escalate/8 p-4 text-[13px] leading-relaxed text-escalate">
          A carteira do titular ainda não abriu neste navegador. Sem ela nada que mova
          autoridade de gasto pode ser assinado — e nada será fingido.
        </div>
      )}

      <section className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
        <Panel
          eyebrow="Meus mandatos"
          title={`${mandates.length} ativo(s)`}
          action={
            <Button variant="ghost" onClick={() => setShowCreate((open) => !open)}>
              <Sparkles size={13} aria-hidden="true" />
              {showCreate ? 'Fechar' : 'Criar mandato'}
            </Button>
          }
        >
          {showCreate && (
            <CreateMandateForm
              onSubmit={createMandate}
              onDone={() => setShowCreate(false)}
              defaultExpiresAt={expiryDefault}
            />
          )}
          {mandates.length === 0 ? (
            <EmptyNotice
              title="Nenhum mandato ainda"
              body="Crie o primeiro mandato para que o agente tenha alguma autoridade — e apenas ela."
            />
          ) : (
            <ul className="space-y-2">
              {mandates.map((mandate) => {
                const active = mandate.mandate_id === selectedMandateId;
                const revoked = mandate.status !== 'ACTIVE';
                return (
                  <li key={mandate.mandate_id}>
                    <button
                      type="button"
                      onClick={() => selectMandate(mandate.mandate_id)}
                      aria-current={active ? 'true' : undefined}
                      className={`w-full rounded-xl border p-3.5 text-left transition-colors ${
                        active ? 'border-allow/50 bg-allow/8' : 'border-line bg-ink-800/50 hover:border-line-hi'
                      }`}
                    >
                      <span className="flex items-center justify-between gap-2">
                        <span className="mono truncate text-[11px] text-fg-mute">{mandate.mandate_id}</span>
                        <Badge tone={revoked ? 'deny' : 'allow'}>{mandate.status}</Badge>
                      </span>
                      <span className="mt-2 block text-[13px]">
                        {formatMoney(toMoney(mandate.remaining))} de {formatMoney(toMoney(mandate.limit))} restantes
                      </span>
                      <span className="mono mt-1 block text-[11px] text-fg-mute">
                        {mandate.allowed_categories.join(', ')} · {mandate.allowed_merchant_ids.join(', ')}
                        {mandate.usage_limit
                          ? ` · ${mandate.uses_in_window}/${mandate.usage_limit.max_uses} usos`
                          : ''}
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
          )}
        </Panel>

        <Panel eyebrow="Agente comprador" title="Diga em texto livre. O núcleo é que decide." action={<Send size={18} className="text-allow" aria-hidden="true" />}>
          <form
            onSubmit={(event: FormEvent) => {
              event.preventDefault();
              void guard(() => runAgent(instruction));
            }}
            className="space-y-3"
          >
            <label className="block">
              <span className="eyebrow">Instrução</span>
              <input
                className="form-control"
                value={instruction}
                onChange={(event) => setInstruction(event.target.value)}
                required
                disabled={!selected || busy}
              />
            </label>
            <Button type="submit" disabled={!selected || busy || !instruction.trim()}>
              {busy ? 'Executando' : 'Pedir ao agente'}
            </Button>
          </form>

          {lastRun && (
            <div className="mt-5 border-t border-line pt-5">
              <div className="flex items-center justify-between gap-3">
                <p className="eyebrow">Resultado</p>
                <Badge tone={lastRun.outcome === 'settled' ? 'allow' : lastRun.escalation_id ? 'escalate' : 'deny'}>
                  {lastRun.reason_code}
                </Badge>
              </div>
              <p className="mt-2 text-[13px] leading-relaxed">{lastRun.human_summary}</p>
              <div className="mt-4">
                <p className="eyebrow mb-2">Como o núcleo chegou nisso</p>
                <EvaluationLadder trace={lastRun.evaluation_trace} />
              </div>

              {/* Nothing matching is not a dead end — but turning it into a live
                  standing order is the buyer's call, never the agent's. Opening one
                  silently would be approving a future purchase nobody asked for. */}
              {lastRun.outcome === 'no_offer' && (
                <div className="mt-4 rounded-xl border border-hold/35 bg-hold/6 p-3.5">
                  <p className="text-[13px] leading-relaxed">
                    Nada no catálogo atende agora. O agente pode continuar tentando
                    sozinho — a vigília corre contra este mesmo mandato.
                  </p>
                  <Button
                    variant="ghost"
                    className="mt-3"
                    disabled={busy || !selected}
                    onClick={() => void guard(() => watchInstruction(instruction))}
                  >
                    <Eye size={13} aria-hidden="true" />
                    Deixar o agente vigiando
                  </Button>
                </div>
              )}
            </div>
          )}
        </Panel>
      </section>

      <Panel eyebrow="Esperando por mim" title={`${escalations.length} aprovação(ões) pendente(s)`}>
        {escalations.length === 0 ? (
          <EmptyNotice
            title="Nada esperando decisão"
            body="Compras fora do mandato aparecem aqui com os dois botões — nunca são aprovadas em silêncio."
          />
        ) : (
          <ul className="space-y-3">
            {escalations.map((escalation) => (
              <li key={escalation.id} className="rounded-xl border border-escalate/35 bg-escalate/6 p-4">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="mono text-[11px] text-fg-mute">{escalation.id}</span>
                  <Badge tone="escalate">{escalation.reason_code}</Badge>
                </div>
                <p className="mt-2 text-[13px]">
                  {formatMoney(toMoney(escalation.amount))} em {escalation.merchant_id} · {escalation.category}
                </p>
                <div className="mt-3 flex gap-2">
                  <Button disabled={busy || !walletReady} onClick={() => void guard(() => decideEscalation(escalation.id, 'approve'))}>
                    Aprovar assinando
                  </Button>
                  <Button variant="danger" disabled={busy || !walletReady} onClick={() => void guard(() => decideEscalation(escalation.id, 'deny'))}>
                    Recusar
                  </Button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Panel>

      <Panel
        eyebrow="Ordens permanentes"
        title={`${watches.length} vigília(s)`}
        action={
          <Button
            variant="ghost"
            disabled={busy || watches.length === 0}
            onClick={() => void guard(tickWatches)}
          >
            <Clock size={13} aria-hidden="true" />
            Tentar agora
          </Button>
        }
      >
        {watches.length === 0 ? (
          <EmptyNotice
            title="Nenhuma vigília aberta"
            body="Quando o agente não encontra oferta, ele oferece ficar olhando. É a única parte do sistema em que o comprador não é uma pessoa apertando pagar."
          />
        ) : (
          <ul className="space-y-2">
            {watches.map((watch) => (
              <li key={watch.watch_id} className="rounded-xl border border-line bg-ink-800/40 p-3.5">
                <div className="flex flex-wrap items-center justify-between gap-2">
                  <span className="mono text-[11px] text-fg-mute">{watch.watch_id}</span>
                  <Badge tone={watchTone(watch)}>{watch.outcome ?? watch.status}</Badge>
                </div>
                <p className="mt-2 text-[13px] leading-relaxed">{watch.instruction}</p>
                <p className="mono mt-1 text-[11px] text-fg-mute">
                  até {formatDateTime(watch.expires_at)}
                  {watch.settlement_reference ? ` · ${watch.settlement_reference}` : ''}
                </p>
              </li>
            ))}
          </ul>
        )}
        <p className="safe-note mt-4">
          <Eye size={15} aria-hidden="true" />
          A autonomia está em <em>quando</em> o agente age, nunca no <em>que</em> ele
          pode fazer: disparar é chamar o mesmo mandato de sempre, então uma vigília
          contra um mandato revogado é recusada igualzinho.
        </p>
      </Panel>

      <section className="grid gap-4 lg:grid-cols-[1.3fr_0.7fr]">
        <Panel eyebrow="Meu registro" title="O que foi comprado, sob qual mandato">
          {humanEntries.length === 0 ? (
            <EmptyNotice title="Trilha vazia" body="Cada decisão do núcleo aparece aqui assim que acontece." />
          ) : (
            <ul className="space-y-2">
              {humanEntries.slice().reverse().map((entry, index) => (
                <li key={index} className="rounded-lg border border-line bg-ink-800/40 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                    <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                  <PaymentState entry={entry} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel eyebrow="Encerrar" title="Retirar autoridade" action={<ShieldOff size={18} className="text-deny" aria-hidden="true" />}>
          <dl>
            <Field label="Chave do titular">{holderKid ?? 'indisponível'}</Field>
            {selected && <Field label="Mandato">{selected.mandate_id}</Field>}
          </dl>
          <div className="mt-4 space-y-2">
            <Button variant="danger" className="w-full" disabled={!selected || busy || !walletReady} onClick={() => void guard(revokeSelected)}>
              <KeyRound size={13} aria-hidden="true" />Revogar este mandato
            </Button>
            <Button variant="danger" className="w-full" disabled={busy || !walletReady || mandates.length === 0} onClick={() => void guard(revokeEverything)}>
              <ShieldOff size={13} aria-hidden="true" />Revogar tudo desta chave
            </Button>
          </div>
          <p className="safe-note mt-4">
            <KeyRound size={15} aria-hidden="true" />
            Ambos exigem uma assinatura desta carteira. Nenhum token de operador
            consegue produzi-la.
          </p>
        </Panel>
      </section>
    </div>
  );
}

/**
 * Authorized, in confirmation, settled — never two states where there are three.
 *
 * The middle one is the honest reading of a processor that did not answer: the budget
 * is held and the outcome is unknown. Rounding it to "aprovado" would promise the buyer
 * a purchase that may not exist; rounding it to "recusado" would tell them their money
 * is free when it is not. So the screen says what is true and says it is unfinished.
 */
function PaymentState({ entry }: { entry: { [key: string]: unknown } }) {
  const detail = (entry.detail ?? {}) as Record<string, unknown>;
  const state = typeof detail.payment_state === 'string' ? detail.payment_state : null;
  if (!state) return null;

  const reading = {
    settled: { tone: 'allow' as const, label: 'liquidado' },
    declined: { tone: 'deny' as const, label: 'recusado pelo processador' },
    in_doubt: { tone: 'hold' as const, label: 'pagamento em confirmação' },
  }[state];
  if (!reading) return null;

  return (
    <p className="mt-2">
      <Badge tone={reading.tone}>{reading.label}</Badge>
    </p>
  );
}

/**
 * Open is `hold`, not `allow`: a standing order has decided nothing yet, and painting
 * it green would read as a purchase that already happened.
 */
function watchTone(watch: { status: string; outcome: string | null }) {
  if (watch.outcome === 'settled') return 'allow' as const;
  if (watch.status === 'OPEN') return 'hold' as const;
  return watch.outcome ? ('deny' as const) : ('neutral' as const);
}

function toMoney(value: { minor_units: number; currency: string; scale: number }) {
  return { minorUnits: value.minor_units, currency: value.currency, scale: value.scale };
}

function CreateMandateForm({
  onSubmit,
  onDone,
  defaultExpiresAt,
}: {
  onSubmit: ReturnType<typeof useAval>['createMandate'];
  onDone(): void;
  defaultExpiresAt: string;
}) {
  const [limit, setLimit] = useState('200');
  const [ceiling, setCeiling] = useState('500');
  const [merchants, setMerchants] = useState('vuelaya');
  const [categories, setCategories] = useState('travel');
  const [maxUses, setMaxUses] = useState('');
  const [expiresAt, setExpiresAt] = useState(defaultExpiresAt);
  const [busy, setBusy] = useState(false);

  return (
    <form
      className="mb-5 space-y-3 rounded-xl border border-line bg-ink-800/50 p-4"
      onSubmit={(event) => {
        event.preventDefault();
        setBusy(true);
        void onSubmit({
          displayName: 'Titular',
          merchants: merchants.split(',').map((value) => value.trim()).filter(Boolean),
          categories: categories.split(',').map((value) => value.trim()).filter(Boolean),
          limit: { minor_units: Math.round(Number(limit) * 100), currency: 'USD', scale: 2 },
          ceiling: ceiling ? { minor_units: Math.round(Number(ceiling) * 100), currency: 'USD', scale: 2 } : null,
          expiresAt,
          usageLimit: maxUses ? { max_uses: Number(maxUses), window_seconds: MONTH_SECONDS } : null,
        })
          .then(onDone)
          .finally(() => setBusy(false));
      }}
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="block">
          <span className="eyebrow">Orçamento (USD)</span>
          <input className="form-control" value={limit} onChange={(event) => setLimit(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Teto por compra (USD)</span>
          <input className="form-control" value={ceiling} onChange={(event) => setCeiling(event.target.value)} />
        </label>
        <label className="block">
          <span className="eyebrow">Merchants</span>
          <input className="form-control" value={merchants} onChange={(event) => setMerchants(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Categorias</span>
          <input className="form-control" value={categories} onChange={(event) => setCategories(event.target.value)} required />
        </label>
        <label className="block">
          <span className="eyebrow">Máx. compras / mês</span>
          <input className="form-control" value={maxUses} onChange={(event) => setMaxUses(event.target.value)} placeholder="sem limite" />
        </label>
        <label className="block">
          <span className="eyebrow">Validade</span>
          <input className="form-control" value={expiresAt} onChange={(event) => setExpiresAt(event.target.value)} required />
        </label>
      </div>
      <Button type="submit" disabled={busy}>{busy ? 'Criando' : 'Criar mandato assinado por esta carteira'}</Button>
    </form>
  );
}
