import type {
  MockAvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
} from '../contracts/avalGateway.ts';
import type { View } from '../state/AvalContext.ts';
import { Badge, Field, Panel } from '../components/ui.tsx';
import { safeDisplayText } from '../utils/safePresentation.ts';
import { TrialConsole } from './TrialConsole.tsx';

export default function DevelopmentMockWorkspace({
  snapshot,
  view,
  receipt,
  onSubmit,
}: {
  snapshot: MockAvalSnapshot;
  view: View;
  receipt: TrialCommandReceipt | null;
  onSubmit(command: TrialCommand): Promise<void>;
}) {
  if (view === 'trial') {
    return (
      <TrialConsole
        mandateId={snapshot.human.mandate.id}
        dataSource="mock"
        receipt={receipt}
        onSubmit={onSubmit}
      />
    );
  }

  const title = view === 'merchant'
    ? snapshot.merchant.merchantName
    : view === 'auditor'
      ? 'Timeline de demonstração'
      : snapshot.human.principalName;
  const status = view === 'merchant'
    ? snapshot.merchant.receipt.status
    : view === 'auditor'
      ? snapshot.auditor.chainStatus
      : snapshot.human.mandate.status;

  return (
    <div className="page-shell">
      <header className="page-heading">
        <div>
          <p className="eyebrow">Dados de demonstração / mock</p>
          <h1>{safeDisplayText(title)}</h1>
          <p>Esta tela existe somente para desenvolvimento visual e não comprova estado do runtime.</p>
        </div>
        <Badge tone="escalate">MOCK</Badge>
      </header>
      <Panel eyebrow="Fixture local" title="Projeção não canônica">
        <dl>
          <Field label="Papel">{view}</Field>
          <Field label="Status">{safeDisplayText(status)}</Field>
          <Field label="Origem">sem rede</Field>
        </dl>
      </Panel>
    </div>
  );
}
