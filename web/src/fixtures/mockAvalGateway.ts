import type {
  AvalGateway,
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
} from '../contracts/avalGateway.ts';
import { CHECKOUT_API_CONTRACT_VERSION } from '../contracts/checkoutApi.ts';

// MOCK FIXTURE — presentation-only projections over the integrated checkout contract.
// Laptop A exposes checkout, not workspace administration or trial commands, so this
// fixture contains no card number, makes no network call, and derives no core decision.
const MOCK_SNAPSHOT: AvalSnapshot = {
  meta: {
    dataSource: 'mock',
    fixtureId: 'mock_trial_room_001',
    contractStatus: 'integrated',
    contractVersion: CHECKOUT_API_CONTRACT_VERSION,
    generatedAt: '2026-08-29T18:42:31-03:00',
    networkUsed: false,
  },
  human: {
    principalName: 'Marta Silva',
    mandate: {
      id: 'mdt_demo_7f31',
      status: 'active',
      agentName: 'Nauta Compras',
      purpose: 'Comprar material de expedição para o ateliê',
      perTransactionLimit: { minorUnits: 25000, currency: 'BRL', scale: 2 },
      ceiling: { minorUnits: 60000, currency: 'BRL', scale: 2 },
      liveAllowance: { minorUnits: 18490, currency: 'BRL', scale: 2 },
      allowanceCheckedAt: '2026-08-29T18:42:29-03:00',
      scopes: ['embalagens', 'papelaria', 'merchant:nauta-suprimentos'],
      revocation: {
        state: 'clear',
        checkedAt: '2026-08-29T18:42:29-03:00',
        epoch: 12,
      },
      authorityRail: {
        maximumMinorUnits: 81000,
        zones: [
          { label: 'Autorização automática', fromMinorUnits: 0, toMinorUnits: 25000, tone: 'allow' },
          { label: 'Decisão humana', fromMinorUnits: 25000, toMinorUnits: 60000, tone: 'escalate' },
          { label: 'Fora do mandato', fromMinorUnits: 60000, toMinorUnits: 81000, tone: 'deny' },
        ],
        marker: { label: 'Compra atual', atMinorUnits: 18490, tone: 'allow' },
      },
    },
    latestDecision: {
      status: 'authorized',
      reasonCode: 'within_live_allowance',
      humanSummary: 'A compra respeitou o escopo e a autoridade viva verificada pelo core.',
      reservationState: 'settled',
      policyVersion: 'policy_42',
    },
    receipts: [
      {
        id: 'rcpt_pay_103',
        merchant: 'Nauta Suprimentos',
        item: 'Caixas de envio e etiquetas',
        amount: { minorUnits: 18490, currency: 'BRL', scale: 2 },
        status: 'settled',
        humanSummary: 'Pagamento capturado depois do commit da reserva.',
        occurredAt: '2026-08-29T18:42:30-03:00',
        receiptHash: 'sha256:9b71…e1c4',
      },
      {
        id: 'rcpt_checkout_102',
        merchant: 'Papel Vivo',
        item: 'Papel especial',
        amount: { minorUnits: 32900, currency: 'BRL', scale: 2 },
        status: 'awaiting_human',
        humanSummary: 'O core pediu decisão humana antes de comprometer qualquer reserva.',
        occurredAt: '2026-08-29T17:11:04-03:00',
        receiptHash: 'sha256:31a8…49f2',
      },
    ],
  },
  merchant: {
    merchantName: 'Nauta Suprimentos',
    receipt: {
      receiptId: 'rcpt_pay_103',
      transactionRef: 'txn_20260829_103',
      amount: { minorUnits: 18490, currency: 'BRL', scale: 2 },
      status: 'settled',
      itemSummary: 'Caixas de envio e etiquetas',
      occurredAt: '2026-08-29T18:42:30-03:00',
    },
    checks: [
      { label: 'Mandato AP2', result: 'verified', detail: 'Evidência v0.2 vinculada ao checkout.' },
      { label: 'Prova de autorização', result: 'verified', detail: 'Emitida após Reservation.COMMITTED.' },
      { label: 'Identidade do titular', result: 'not-shared', detail: 'Não necessária para liquidar esta compra.' },
      { label: 'Orçamento acumulado', result: 'not-shared', detail: 'Permanece privado no AVAL.' },
    ],
    signedEvidence: {
      ap2Version: 'v0.2',
      checkoutReceiptHash: 'sha256:51b2…c05a',
      paymentReceiptHash: 'sha256:9b71…e1c4',
    },
  },
  auditor: {
    chainStatus: 'verified',
    chainHead: 'sha256:af20…4d91',
    events: [
      {
        sequence: 1042,
        id: 'evt_1042',
        occurredAt: '2026-08-29T18:42:27-03:00',
        actor: 'nauta-agent',
        actorRole: 'agent',
        eventType: 'authorization.requested',
        reasonCode: 'request_received',
        humanSummary: 'O agente pediu autorização para comprar caixas e etiquetas.',
        reservationState: 'pending',
        integrityHash: 'sha256:7440…a921',
      },
      {
        sequence: 1043,
        id: 'evt_1043',
        occurredAt: '2026-08-29T18:42:29-03:00',
        actor: 'aval-core',
        actorRole: 'authorization_core',
        eventType: 'reservation.committed',
        reasonCode: 'within_live_allowance',
        humanSummary: 'O core verificou autoridade viva e comprometeu a reserva.',
        reservationState: 'committed',
        integrityHash: 'sha256:c310…73a0',
      },
      {
        sequence: 1044,
        id: 'evt_1044',
        occurredAt: '2026-08-29T18:42:30-03:00',
        actor: 'mock-card-psp',
        actorRole: 'settlement_adapter',
        eventType: 'settlement.confirmed',
        reasonCode: 'psp_approved',
        humanSummary: 'O adaptador devolveu aprovação; o core marcou a reserva como liquidada.',
        reservationState: 'settled',
        integrityHash: 'sha256:af20…4d91',
      },
    ],
    dispute: {
      id: 'dsp_021',
      status: 'reconstructed',
      merchant: 'Nauta Suprimentos',
      amount: { minorUnits: 18490, currency: 'BRL', scale: 2 },
      claim: 'Confirmar se a compra permaneceu autorizada após uma revogação tardia.',
      verdictSummary: 'A reserva já estava COMMITTED; a revogação posterior vale para decisões futuras e não cancela a liquidação em voo.',
    },
  },
};

const copy = <T>(value: T): T => JSON.parse(JSON.stringify(value)) as T;

export function createMockAvalGateway(): AvalGateway {
  return {
    async loadWorkspace() {
      return copy(MOCK_SNAPSHOT);
    },
    async submitTrialCommand(command: TrialCommand): Promise<TrialCommandReceipt> {
      return {
        requestId: `mock_request_${command.kind}`,
        dataSource: 'mock',
        outcome: 'fixture-only',
        canonicalStateChanged: false,
        effectiveAt: null,
        message: 'Intenção registrada apenas na fixture. Nenhum estado canônico foi alterado.',
      };
    },
  };
}
