import { EyeOff, FileCheck2, Store } from 'lucide-react';

import type {
  PaymentCaptureProjection,
  PaymentReceiptsProjection,
} from '../contracts/paymentRuntimeApi.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { shortHash } from '../utils/format.ts';

export function LiveMerchantView({
  capture,
  receipts,
}: {
  capture: PaymentCaptureProjection | null;
  receipts: PaymentReceiptsProjection | null;
}) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do merchant · API real</p>
          <h1>Liquidação e recibos — apenas o necessário.</h1>
          <p>Nenhuma credencial de cartão, identidade do titular, orçamento privado ou prova interna faz parte desta visão.</p>
        </div>
        <Badge tone={capture?.status === 'settled' ? 'allow' : 'hold'}>{capture?.status ?? 'sem captura'}</Badge>
      </header>

      {!capture ? (
        <EmptyNotice
          title="Captura não configurada"
          body="Informe um capture ID emitido pelo runtime para carregar a projeção canônica do merchant."
        />
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          <Panel eyebrow="Payment capture" title={capture.capture_id} action={<Store size={20} className="text-allow" aria-hidden="true" />}>
            <dl>
              <Field label="Status">{capture.status}</Field>
              <Field label="Reserva">{capture.reservation_id}</Field>
              <Field label="Referência PSP">{capture.settlement_reference}</Field>
            </dl>
          </Panel>

          <Panel eyebrow="AP2 receipts" title={receipts ? 'Recibos disponíveis' : 'Recibos indisponíveis'} action={<FileCheck2 size={20} className="text-verify" aria-hidden="true" />}>
            {receipts ? (
              <dl>
                <Field label="Captura">{receipts.capture_id}</Field>
                <Field label="Checkout receipt">{shortHash(receipts.checkout_receipt)}</Field>
                <Field label="Payment receipt">{shortHash(receipts.payment_receipt)}</Field>
              </dl>
            ) : (
              <p className="text-[13px] leading-relaxed text-fg-mute">O runtime ainda não publicou recibos para esta captura.</p>
            )}
          </Panel>
        </section>
      )}

      <p className="safe-note"><EyeOff size={15} aria-hidden="true" />PAN, identificadores privados, orçamento privado e segredos permanecem fora desta projeção.</p>
    </div>
  );
}
