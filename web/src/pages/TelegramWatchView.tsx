import { useCallback, useEffect, useRef, useState } from 'react';
import { CircleDot, MessageSquare, RadioTower, ShieldCheck, ShieldX } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { GatewayError, type LedgerEntry, type MandateView, type TelegramChat } from '../gateways/authorizationGateway.ts';
import { formatDateTime, formatMoney, toMoney } from '../utils/format.ts';

const FOLLOW_INTERVAL_MS = 4000;
const STORAGE_KEY = 'aval.telegram.chat';

/**
 * The chat, on the projector.
 *
 * Everything here is read-only, and that is a property rather than a shortcut. The
 * mandates a chat holds are signed by a key that lives in the bot's identity store, so
 * this browser could not act on one even if a button offered to — the core would refuse
 * the signature. What the screen shows instead is what any auditor may see: the
 * mandate's own numbers and the trail underneath them, both answered by routes that
 * take a mandate id and no credential at all.
 *
 * Approving, revoking and changing a limit stay in the chat, where the key is. Putting
 * them here would mean copying that key into a browser, which is the one thing the
 * isolation exists to prevent.
 */
export function TelegramWatchView() {
  const { gateway, operatorAvailable, live } = useAval();

  const [chats, setChats] = useState<TelegramChat[]>([]);
  const [selected, setSelected] = useState<number | null>(() => {
    const stored = Number(localStorage.getItem(STORAGE_KEY));
    return Number.isFinite(stored) && stored !== 0 ? stored : null;
  });
  const [mandate, setMandate] = useState<MandateView | null>(null);
  const [entries, setEntries] = useState<LedgerEntry[]>([]);
  const [chain, setChain] = useState<{ intact: boolean; checked: number } | null>(null);
  const [problem, setProblem] = useState<string | null>(null);
  // A mandate the runtime no longer has will 404 on every tick forever. Remembering
  // which one died keeps a stale chat from turning live mode into a 404 storm.
  const buried = useRef<string | null>(null);

  const chosen = chats.find((chat) => chat.chat_id === selected) ?? null;

  const refresh = useCallback(async () => {
    let reading: string | null = null;
    try {
      const directory = await gateway.listTelegramChats();
      setChats(directory.chats);
      setProblem(null);

      const target = directory.chats.find((chat) => chat.chat_id === selected);
      reading = target?.mandate_id ?? null;
      if (reading !== null && reading === buried.current) return;
      if (!target?.mandate_id) {
        setMandate(null);
        setEntries([]);
        setChain(null);
        return;
      }
      // Three unauthenticated reads: the mandate, what it bought, and whether the
      // trail under it still verifies. None of them needs this chat's key.
      const [snapshot, human, auditor] = await Promise.all([
        gateway.readMandate(target.mandate_id),
        gateway.humanLedger(target.mandate_id),
        gateway.auditorLedger(target.mandate_id),
      ]);
      setMandate(snapshot);
      setEntries(human.entries);
      setChain({ intact: auditor.chain.intact, checked: auditor.chain.checked });
    } catch (error) {
      // A mandate id that outlived its database is the failure this screen actually
      // meets — the dev database is recreated often and the bot's store is not. Saying
      // so beats an empty panel that looks like "nothing happened yet".
      if (error instanceof GatewayError && error.status === 404) {
        buried.current = reading;
        setMandate(null);
        setEntries([]);
        setChain(null);
        setProblem('O mandato deste chat não existe mais neste runtime. Peça /start no bot para emitir outro.');
        return;
      }
      setProblem(error instanceof GatewayError ? error.message : 'Falha ao ler o chat.');
    }
  }, [gateway, selected]);

  useEffect(() => {
    void refresh();
    if (!live) return;
    const timer = setInterval(() => {
      if (!document.hidden) void refresh();
    }, FOLLOW_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [refresh, live]);

  function choose(chatId: number) {
    buried.current = null;
    setSelected(chatId);
    localStorage.setItem(STORAGE_KEY, String(chatId));
  }

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Chat do Telegram · somente leitura</p>
          <h1>O que o juiz acabou de fazer no celular, aqui.</h1>
          <p>
            Esta tela segue um chat sem nunca segurar a chave dele. Aprovar, revogar e
            mudar limite continuam no chat — é lá que a chave está, e é isso que impede
            este navegador de gastar o dinheiro de outra pessoa.
          </p>
        </div>
        <Badge tone={live ? 'verify' : 'neutral'}>
          {live ? `SEGUINDO · ${FOLLOW_INTERVAL_MS / 1000}s` : 'AO VIVO DESLIGADO'}
        </Badge>
      </header>

      {!operatorAvailable ? (
        <EmptyNotice
          title="Sem token de operador"
          body="A lista de chats é uma superfície de operador: um diretório de compradores não é coisa que um estranho enumere. Suba o Vite com VITE_AVAL_OPERATOR_TOKEN."
        />
      ) : (
        <section className="grid gap-4 lg:grid-cols-[0.8fr_1.2fr]">
          <div className="space-y-4">
            <Panel
              eyebrow="Quem falou com o bot"
              title={`${chats.length} chat(s)`}
              action={<MessageSquare size={18} className="text-verify" aria-hidden="true" />}
            >
              {chats.length === 0 ? (
                <EmptyNotice
                  title="Ninguém iniciou ainda"
                  body="Mande /start para o bot. O chat aparece aqui sozinho, sem recarregar a página."
                />
              ) : (
                <ul className="space-y-2">
                  {chats.map((chat) => {
                    const active = chat.chat_id === selected;
                    return (
                      <li key={chat.chat_id}>
                        <button
                          type="button"
                          aria-current={active ? 'true' : undefined}
                          onClick={() => choose(chat.chat_id)}
                          className={`w-full rounded-lg border p-3 text-left transition-colors ${active ? 'border-allow/50 bg-allow/8' : 'border-line bg-ink-800/40 hover:bg-white/4'}`}
                        >
                          <span className="flex items-center justify-between gap-2">
                            <span className="text-[13px] font-semibold">{chat.display_name}</span>
                            <span className="mono text-[10px] text-fg-mute">{chat.chat_id}</span>
                          </span>
                          <span className="mono mt-1 block truncate text-[10px] text-fg-faint">
                            {chat.mandate_id ?? 'sem mandato'}
                          </span>
                        </button>
                      </li>
                    );
                  })}
                </ul>
              )}
            </Panel>

            {chosen && (
              <Panel eyebrow="Mandato do chat" title="Autoridade concedida">
                {problem ? (
                  <p className="text-[13px] leading-relaxed text-escalate">{problem}</p>
                ) : mandate === null ? (
                  <p className="text-[13px] leading-relaxed text-fg-mute">Lendo…</p>
                ) : (
                  <dl>
                    <Field label="Estado">
                      <Badge tone={mandate.status === 'ACTIVE' ? 'allow' : 'deny'}>{mandate.status}</Badge>
                    </Field>
                    <Field label="Orçamento livre">{formatMoney(toMoney(mandate.remaining))}</Field>
                    <Field label="Limite">{formatMoney(toMoney(mandate.limit))}</Field>
                    <Field label="Gasto">{formatMoney(toMoney(mandate.spent))}</Field>
                    {mandate.ceiling && <Field label="Teto por compra">{formatMoney(toMoney(mandate.ceiling))}</Field>}
                    <Field label="Merchants">{mandate.allowed_merchant_ids.join(', ')}</Field>
                    <Field label="Categorias">{mandate.allowed_categories.join(', ')}</Field>
                    <Field label="Expira">{formatDateTime(mandate.expires_at)}</Field>
                  </dl>
                )}
              </Panel>
            )}
          </div>

          <Panel
            eyebrow="O que aconteceu neste chat"
            title={`${entries.length} evento(s)`}
            action={
              chain === null ? (
                <RadioTower size={18} className="text-fg-mute" aria-hidden="true" />
              ) : chain.intact ? (
                <span className="flex items-center gap-1.5 text-verify">
                  <ShieldCheck size={16} aria-hidden="true" />
                  <span className="mono text-[10px] uppercase tracking-wider">cadeia ok · {chain.checked}</span>
                </span>
              ) : (
                <span className="flex items-center gap-1.5 text-deny">
                  <ShieldX size={16} aria-hidden="true" />
                  <span className="mono text-[10px] uppercase tracking-wider">cadeia quebrada</span>
                </span>
              )
            }
          >
            {entries.length === 0 ? (
              <EmptyNotice
                title="Nada ainda"
                body="Escolha um chat à esquerda. Cada compra, escalação, aprovação e revogação aparece aqui no instante em que o núcleo decide."
              />
            ) : (
              <ol className="space-y-2">
                {entries.map((entry) => (
                  <li key={String(entry.sequence)} className="rounded-lg border border-line bg-ink-800/40 p-3">
                    <div className="flex flex-wrap items-baseline justify-between gap-2">
                      <span className="flex items-center gap-2">
                        <CircleDot size={12} className="text-verify" aria-hidden="true" />
                        <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                      </span>
                      <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                    </div>
                    <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                  </li>
                ))}
              </ol>
            )}
          </Panel>
        </section>
      )}
    </div>
  );
}
