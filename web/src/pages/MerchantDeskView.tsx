import { EyeOff, Store } from 'lucide-react';

import { useAval } from '../state/AvalContext.ts';
import { Badge, EmptyNotice, Panel } from '../components/ui.tsx';
import { formatDateTime } from '../utils/format.ts';

/**
 * What the merchant is allowed to see — and, beside it, what it is not.
 *
 * The redaction list is served by the runtime rather than assembled here. A browser
 * that decided for itself which fields were hidden would be describing a privacy
 * property instead of showing one, and the two would drift the first time the
 * projection changed.
 */
export function MerchantDeskView() {
  const { merchantEntries, merchantRedactions, auditorEntries, mandates, selectedMandateId } = useAval();
  const merchantId =
    mandates.find((item) => item.mandate_id === selectedMandateId)?.allowed_merchant_ids[0] ?? '—';

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do merchant · {merchantId}</p>
          <h1>Eu recebo uma prova da compra, não a pessoa por trás dela.</h1>
          <p>
            A prova de autorização vincula checkout, merchant, valor, moeda e termos — e
            omite o mandato e o comprador. Aceitar não exige conhecê-los.
          </p>
        </div>
        <Badge tone="verify">SEM IDENTIDADE DO COMPRADOR</Badge>
      </header>

      <section className="merchant-envelope" aria-label="Fluxo de verificação do merchant">
        <div><span>01</span><strong>Oferta assinada</strong><p>Termos, valor e merchant chegam vinculados.</p></div>
        <div><span>02</span><strong>Prova verificável</strong><p>AVAL confirma a autorização sem abrir o mandato.</p></div>
        <div><span>03</span><strong>Identidade protegida</strong><p>O merchant nunca recebe titular, orçamento ou chave.</p></div>
      </section>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="O que eu recebo" title="Projeção do merchant" action={<Store size={18} className="text-verify" aria-hidden="true" />}>
          {merchantEntries.length === 0 ? (
            <EmptyNotice title="Nenhuma venda ainda" body="Compras liquidadas por este merchant aparecem aqui." />
          ) : (
            <ul className="space-y-2">
              {merchantEntries.slice().reverse().map((entry, index) => (
                <li key={index} className="rounded-lg border border-line bg-ink-800/40 p-3">
                  <div className="flex flex-wrap items-baseline justify-between gap-2">
                    <span className="mono text-[11px] text-verify">{entry.event_type}</span>
                    <span className="mono text-[10px] text-fg-mute">{formatDateTime(entry.occurred_at)}</span>
                  </div>
                  <p className="mt-1 text-[13px] leading-relaxed">{entry.human_summary}</p>
                  <PairwiseHandle entry={entry} />
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          eyebrow="O que me é negado"
          title="Campos retidos pela projeção"
          action={<EyeOff size={18} className="text-escalate" aria-hidden="true" />}
        >
          {merchantRedactions.length === 0 ? (
            <EmptyNotice title="Lista indisponível" body="Carregue um mandato para ver o que a projeção retém." />
          ) : (
            <>
              <ul className="space-y-2">
                {merchantRedactions.map((field) => (
                  <li key={field} className="flex items-center gap-3 rounded-lg border border-dashed border-escalate/40 bg-escalate/5 px-3 py-2.5">
                    <EyeOff size={14} className="shrink-0 text-escalate" aria-hidden="true" />
                    <span className="mono text-[12px] text-escalate">{field}</span>
                  </li>
                ))}
              </ul>
              <p className="safe-note mt-4">
                <EyeOff size={15} aria-hidden="true" />
                Esta lista é construída por lista branca no servidor: a projeção nomeia o
                que o merchant recebe, em vez de tentar lembrar o que esconder.
              </p>
            </>
          )}
        </Panel>
      </section>

      <Panel eyebrow="Prova de privacidade" title="O mesmo evento, para dois públicos">
        <p className="mb-4 text-[13px] leading-relaxed text-fg-mute">
          À esquerda o que o auditor lê; à direita o que o merchant recebe do mesmo
          evento. A diferença não é estilo — é o que a projeção se recusa a entregar.
        </p>
        <div className="grid gap-3 lg:grid-cols-2">
          <div className="rounded-xl border border-line bg-ink-800/40 p-4">
            <p className="eyebrow mb-2">Auditor · {auditorEntries.length} eventos</p>
            <pre className="mono max-h-72 overflow-auto text-[10.5px] leading-relaxed text-fg-dim">
              {JSON.stringify(auditorEntries.slice(-2), null, 2)}
            </pre>
          </div>
          <div className="rounded-xl border border-verify/30 bg-verify/5 p-4">
            <p className="eyebrow mb-2">Merchant · {merchantEntries.length} eventos</p>
            <pre className="mono max-h-72 overflow-auto text-[10.5px] leading-relaxed text-fg-dim">
              {JSON.stringify(merchantEntries.slice(-2), null, 2)}
            </pre>
          </div>
        </div>
      </Panel>
    </div>
  );
}

/**
 * The only name this seller has for this buyer, and the only one it is allowed to have.
 *
 * `HMAC(secret, mandate | merchant)`: stable at this shop, so a returning customer is
 * recognisable, and different at every other shop, so two sellers comparing notes find
 * nothing in common. Before this the merchant had no buyer handle at all — correct, and
 * useless for the one thing a merchant legitimately wants.
 */
function PairwiseHandle({ entry }: { entry: { [key: string]: unknown } }) {
  const detail = (entry.detail ?? {}) as Record<string, unknown>;
  const handle = typeof detail.pairwise_id === 'string' ? detail.pairwise_id : null;
  if (!handle) return null;

  return (
    <p className="mono mt-2 text-[10px] text-fg-faint">
      comprador nesta loja · {handle}
    </p>
  );
}
