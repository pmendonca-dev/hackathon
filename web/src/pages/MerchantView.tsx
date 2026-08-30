import { EyeOff, Store } from 'lucide-react';

import type { UiWorkspaceProjection } from '../contracts/avalGateway.ts';
import { Badge, EmptyNotice, Field, Panel } from '../components/ui.tsx';
import { safeDisplayText } from '../utils/safePresentation.ts';

export function MerchantView({ workspace }: { workspace: UiWorkspaceProjection }) {
  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Visão do merchant · BFF</p>
          <h1>Somente os mandatos da projeção comercial autorizada.</h1>
          <p>Saldo do titular, limite privado e evidência criptográfica permanecem fora desta resposta.</p>
        </div>
        <Badge tone="verify">{workspace.mandates.length} mandato(s)</Badge>
      </header>

      {workspace.mandates.length === 0 ? (
        <EmptyNotice title="Nenhum mandato disponível" body="A sessão não recebeu mandatos para este merchant." />
      ) : (
        <section className="grid gap-4 lg:grid-cols-2">
          {workspace.mandates.map((mandate) => (
            <Panel
              key={mandate.mandate_id}
              eyebrow="Projeção comercial"
              title={safeDisplayText(mandate.mandate_id)}
              action={<Store size={18} className="text-allow" aria-hidden="true" />}
            >
              <dl>
                <Field label="Merchant">{safeDisplayText(mandate.merchant_id ?? 'não publicado')}</Field>
                <Field label="Status">{safeDisplayText(mandate.status)}</Field>
              </dl>
            </Panel>
          ))}
        </section>
      )}

      <p className="safe-note"><EyeOff size={15} aria-hidden="true" />A página não consulta timeline de outro merchant nem renderiza dados privados do titular.</p>
    </div>
  );
}
