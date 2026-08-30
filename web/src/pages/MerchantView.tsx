import { EyeOff, FileCheck2, Store } from 'lucide-react';

import type { MerchantViewProjection } from '../contracts/avalGateway.ts';
import { Badge, Field, Panel } from '../components/ui.tsx';
import { formatDateTime, formatMoney, shortHash } from '../utils/format.ts';

export function MerchantView({ data }: { data: MerchantViewProjection }) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do merchant</p>
          <h1>{data.merchantName} recebeu o necessário — e nada além.</h1>
          <p>A prova confirma pagamento e autorização sem expor identidade privada, orçamento ou credencial de cartão.</p>
        </div>
        <Badge tone="verify">AP2 {data.signedEvidence.ap2Version}</Badge>
      </header>

      <section className="grid gap-4 lg:grid-cols-2">
        <Panel eyebrow="Payment receipt" title={data.receipt.itemSummary} action={<Badge tone="allow">{data.receipt.status}</Badge>}>
          <div className="mb-4 flex items-center justify-between rounded-xl border border-allow/25 bg-allow/6 p-4">
            <div>
              <p className="eyebrow">Valor confirmado</p>
              <strong className="mono mt-1 block text-2xl">{formatMoney(data.receipt.amount)}</strong>
            </div>
            <Store size={24} className="text-allow" aria-hidden="true" />
          </div>
          <dl>
            <Field label="Recibo">{data.receipt.receiptId}</Field>
            <Field label="Transação">{data.receipt.transactionRef}</Field>
            <Field label="Token opaco">{data.receipt.paymentToken}</Field>
            <Field label="Confirmado em">{formatDateTime(data.receipt.occurredAt)}</Field>
          </dl>
        </Panel>

        <Panel eyebrow="Selective disclosure" title="O que esta visão pode verificar" action={<FileCheck2 size={18} className="text-verify" aria-hidden="true" />}>
          <ul className="space-y-3">
            {data.checks.map((check) => (
              <li key={check.label} className="flex gap-3 rounded-xl border border-line bg-ink-800/50 p-3.5">
                {check.result === 'verified' ? <FileCheck2 className="mt-0.5 shrink-0 text-verify" size={17} aria-hidden="true" /> : <EyeOff className="mt-0.5 shrink-0 text-fg-mute" size={17} aria-hidden="true" />}
                <div>
                  <div className="flex flex-wrap items-center gap-2">
                    <h3 className="text-[13px] font-semibold">{check.label}</h3>
                    <Badge tone={check.result === 'verified' ? 'verify' : 'neutral'}>{check.result}</Badge>
                  </div>
                  <p className="mt-1 text-[12px] leading-relaxed text-fg-mute">{check.detail}</p>
                </div>
              </li>
            ))}
          </ul>
        </Panel>
      </section>

      <Panel eyebrow="Evidência vinculada" title="Hashes apresentados ao merchant">
        <dl className="grid gap-x-6 md:grid-cols-3">
          <Field label="Checkout receipt">{shortHash(data.signedEvidence.checkoutReceiptHash)}</Field>
          <Field label="Payment receipt">{shortHash(data.signedEvidence.paymentReceiptHash)}</Field>
          <Field label="Authorization proof">{data.signedEvidence.authorizationProofRef}</Field>
        </dl>
      </Panel>

      <p className="safe-note"><EyeOff size={15} aria-hidden="true" />PAN, identidade do titular, saldo e teto mensal não fazem parte desta projeção.</p>
    </div>
  );
}
