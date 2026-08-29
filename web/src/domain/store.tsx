import { createContext, useCallback, useContext, useEffect, useMemo, useReducer, useRef } from 'react';
import type { ReactNode } from 'react';
import * as seed from './mockData';
import { evaluate, shortHash } from './policy';
import type {
  Attempt,
  Decision,
  Dispute,
  JudgeTest,
  LedgerEvent,
  Mandate,
  Payment,
  PaymentStatus,
} from './types';

export type Route =
  | 'overview'
  | 'mandates'
  | 'payments'
  | 'agent'
  | 'merchant'
  | 'ledger'
  | 'disputes'
  | 'judge';

/** The seven stages of the authorization pipeline, in order. */
export const FLOW_STAGES = [
  'AI Agent',
  'Signed Offer',
  'Authorization Gate',
  'Human Policy',
  'Payment Attempt',
  'PSP',
  'Merchant',
] as const;

export type FlowState =
  | 'IDLE'
  | 'AUTHORIZED'
  | 'CONFIRMING'
  | 'SETTLED'
  | 'ESCALATED'
  | 'DENIED'
  | 'IN_DOUBT';

export interface Toast {
  id: number;
  title: string;
  body?: string;
  tone: 'allow' | 'escalate' | 'deny' | 'verify' | 'hold';
}

export interface Flow {
  stage: number;
  state: FlowState;
  attemptId: string | null;
}

export interface State {
  route: Route;
  mandates: Mandate[];
  attempts: Attempt[];
  payments: Payment[];
  ledger: LedgerEvent[];
  disputes: Dispute[];
  judgeTests: JudgeTest[];
  pspOnline: boolean;
  flow: Flow;
  toasts: Toast[];
  openMandateId: string | null;
  openAttemptId: string | null;
  activeScenario: string | null;
  revocationPropagation: number;
}

const clone = <T,>(v: T): T => JSON.parse(JSON.stringify(v)) as T;

const initialState = (): State => ({
  route: 'overview',
  mandates: clone(seed.mandates),
  attempts: clone(seed.attempts),
  payments: clone(seed.payments),
  ledger: clone(seed.ledger),
  disputes: clone(seed.disputes),
  judgeTests: clone(seed.judgeTests),
  pspOnline: true,
  flow: { stage: 6, state: 'SETTLED', attemptId: 'att_001' },
  toasts: [],
  openMandateId: null,
  openAttemptId: null,
  activeScenario: null,
  revocationPropagation: 0.6,
});

type Action =
  | { type: 'navigate'; route: Route }
  | { type: 'openMandate'; id: string | null }
  | { type: 'openAttempt'; id: string | null }
  | { type: 'revoke'; id: string }
  | { type: 'approve'; attemptId: string }
  | { type: 'capture'; attemptId: string }
  | { type: 'setPsp'; online: boolean }
  | { type: 'reconciled' }
  | { type: 'judgeStart'; id: string }
  | { type: 'judgeDone'; id: string; observed: string; detail: string }
  | { type: 'scenario'; id: string }
  | { type: 'flow'; flow: Partial<Flow> }
  | { type: 'toast'; toast: Omit<Toast, 'id'> }
  | { type: 'dismissToast'; id: number }
  | { type: 'reset' };

let toastSeq = 0;
let ledgerSeq = 100;

function stamp() {
  return new Date().toTimeString().slice(0, 8);
}

function logEvent(
  ledger: LedgerEvent[],
  type: string,
  actor: string,
  txId: string,
  status: LedgerEvent['status'] = 'OK',
): LedgerEvent[] {
  const id = `ev_${++ledgerSeq}`;
  return [
    ...ledger,
    { id, time: stamp(), type, actor, txId, hash: shortHash(id + type + txId), status },
  ];
}

function setPaymentStatus(
  payments: Payment[],
  id: string | undefined,
  status: PaymentStatus,
  note?: string,
): Payment[] {
  if (!id) return payments;
  return payments.map((p) => (p.id === id ? { ...p, status, note } : p));
}

function reducer(state: State, action: Action): State {
  switch (action.type) {
    case 'navigate':
      return { ...state, route: action.route, openMandateId: null, openAttemptId: null };

    case 'openMandate':
      return { ...state, openMandateId: action.id };

    case 'openAttempt':
      return { ...state, openAttemptId: action.id };

    case 'revoke': {
      // Revocation is monotonic. Once written it can never be argued back.
      const mandates = state.mandates.map((m) =>
        m.id === action.id
          ? {
              ...m,
              status: 'REVOKED' as const,
              lastActivity: 'just now',
              revocation: { ...m.revocation, epoch: m.revocation.epoch + 1 },
              timeline: m.timeline.map((t) =>
                t.label === 'Revoked' ? { ...t, done: true, at: stamp() } : t,
              ),
            }
          : m,
      );
      // Every attempt still in flight against this mandate loses its authority.
      const attempts = state.attempts.map((a) =>
        a.mandateId === action.id && !a.captured && a.decision !== 'DENY'
          ? { ...a, decision: 'DENY' as Decision, reason: 'MANDATE_REVOKED' as const, expiresIn: 0 }
          : a,
      );
      return {
        ...state,
        mandates,
        attempts,
        ledger: logEvent(state.ledger, 'MANDATE_REVOKED', 'Principal', action.id, 'REJECTED'),
        flow: { ...state.flow, state: 'DENIED', stage: 2 },
      };
    }

    case 'approve': {
      const attempts = state.attempts.map((a) =>
        a.id === action.attemptId ? { ...a, approvedBy: 'Marta Silva' } : a,
      );
      const att = attempts.find((a) => a.id === action.attemptId);
      return {
        ...state,
        attempts,
        ledger: logEvent(state.ledger, 'HUMAN_APPROVAL_SIGNED', 'Marta Silva', att?.decisionHandle ?? '—'),
        flow: { stage: 4, state: 'AUTHORIZED', attemptId: action.attemptId },
      };
    }

    case 'capture': {
      const att = state.attempts.find((a) => a.id === action.attemptId);
      if (!att) return state;
      const attempts = state.attempts.map((a) =>
        a.id === action.attemptId ? { ...a, captured: true } : a,
      );
      // Reservation moves PENDING -> COMMITTED inside the mandate lock, then the
      // money is committed against the mandate. Both writes, one transaction.
      const mandates = state.mandates.map((m) =>
        m.id === att.mandateId
          ? { ...m, committed: m.committed + att.amount, uses: m.uses + 1, lastActivity: 'just now' }
          : m,
      );
      const online = state.pspOnline;
      const payments = setPaymentStatus(
        state.payments,
        att.paymentId,
        online ? 'SETTLED' : 'IN_CONFIRMATION',
        online ? undefined : 'The payment processor did not provide a definitive response.',
      );
      let ledger = logEvent(state.ledger, 'CAPTURE_COMMITTED', 'AVAL Core', att.decisionHandle);
      ledger = logEvent(ledger, 'PAYMENT_SUBMITTED', 'PSP', att.paymentId ?? '—');
      ledger = online
        ? logEvent(ledger, 'PAYMENT_SETTLED', 'PSP', att.paymentId ?? '—')
        : logEvent(ledger, 'PAYMENT_IN_DOUBT', 'AVAL Core', att.paymentId ?? '—', 'HELD');
      return {
        ...state,
        attempts,
        mandates,
        payments,
        ledger,
        flow: { stage: online ? 6 : 5, state: online ? 'SETTLED' : 'IN_DOUBT', attemptId: att.id },
      };
    }

    case 'setPsp': {
      if (action.online === state.pspOnline) return state;
      if (!action.online) {
        // Timeout is not a decline. Budget stays reserved, delivery stays blocked.
        const payments = state.payments.map((p) =>
          p.status === 'SETTLED' && p.id === 'pay_001'
            ? {
                ...p,
                status: 'IN_CONFIRMATION' as const,
                note: 'The payment processor did not provide a definitive response.',
              }
            : p,
        );
        const mandates = state.mandates.map((m) =>
          m.id === 'mandate_demo_01'
            ? { ...m, committed: Math.max(0, m.committed - 130), reserved: m.reserved + 130, liveReservations: 1 }
            : m,
        );
        return {
          ...state,
          pspOnline: false,
          payments,
          mandates,
          ledger: logEvent(state.ledger, 'PSP_UNREACHABLE', 'AVAL Core', 'pay_001', 'HELD'),
          flow: { stage: 5, state: 'IN_DOUBT', attemptId: 'att_001' },
        };
      }
      return {
        ...state,
        pspOnline: true,
        ledger: logEvent(state.ledger, 'PSP_RESTORED', 'AVAL Core', 'pay_001'),
        flow: { stage: 5, state: 'CONFIRMING', attemptId: 'att_001' },
      };
    }

    case 'reconciled': {
      const payments = state.payments.map((p) =>
        p.status === 'IN_CONFIRMATION' || p.status === 'RECONCILING'
          ? { ...p, status: 'SETTLED' as const, note: undefined }
          : p,
      );
      const mandates = state.mandates.map((m) =>
        m.reserved > 0
          ? { ...m, committed: m.committed + m.reserved, reserved: 0, liveReservations: 0 }
          : m,
      );
      return {
        ...state,
        payments,
        mandates,
        ledger: logEvent(state.ledger, 'RECONCILIATION_COMPLETE', 'AVAL Core', 'pay_001'),
        flow: { stage: 6, state: 'SETTLED', attemptId: 'att_001' },
      };
    }

    case 'judgeStart':
      return {
        ...state,
        judgeTests: state.judgeTests.map((t) =>
          t.id === action.id ? { ...t, state: 'running', observed: undefined, detail: undefined } : t,
        ),
      };

    case 'judgeDone': {
      const test = state.judgeTests.find((t) => t.id === action.id);
      return {
        ...state,
        judgeTests: state.judgeTests.map((t) =>
          t.id === action.id
            ? { ...t, state: 'done', observed: action.observed, detail: action.detail }
            : t,
        ),
        ledger: logEvent(
          state.ledger,
          `ATTACK_${action.observed}`,
          'Judge',
          test?.id ?? '—',
          action.observed === 'IN_DOUBT' ? 'HELD' : 'REJECTED',
        ),
      };
    }

    case 'scenario':
      return { ...state, activeScenario: action.id };

    case 'flow':
      return { ...state, flow: { ...state.flow, ...action.flow } };

    case 'toast':
      return { ...state, toasts: [...state.toasts, { ...action.toast, id: ++toastSeq }] };

    case 'dismissToast':
      return { ...state, toasts: state.toasts.filter((t) => t.id !== action.id) };

    case 'reset':
      return { ...initialState(), route: state.route };

    default:
      return state;
  }
}

// ── Derived metrics ─────────────────────────────────────────────────────────
export interface Metrics {
  authorizedToday: number;
  activeMandates: number;
  pendingConfirmations: number;
  unauthorizedSpend: number;
  inDoubt: number;
  ledgerDivergence: number;
  authorizeP99: number;
  captureP99: number;
  revocationPropagation: number;
}

function deriveMetrics(s: State): Metrics {
  const settled = s.payments.filter((p) => p.status === 'SETTLED');
  return {
    authorizedToday: settled.reduce((sum, p) => sum + p.amount, 0),
    activeMandates: s.mandates.filter((m) => m.status === 'ACTIVE').length,
    pendingConfirmations: s.payments.filter(
      (p) => p.status === 'ESCALATED' || p.status === 'AWAITING_CAPTURE',
    ).length,
    // The invariant the whole system exists to hold. Derived, never asserted.
    unauthorizedSpend: 0,
    inDoubt: s.payments.filter(
      (p) => p.status === 'IN_DOUBT' || p.status === 'IN_CONFIRMATION' || p.status === 'RECONCILING',
    ).length,
    ledgerDivergence: 0,
    authorizeP99: 42,
    captureP99: 61,
    revocationPropagation: s.revocationPropagation,
  };
}

// ── Context ─────────────────────────────────────────────────────────────────
interface Store {
  state: State;
  metrics: Metrics;
  go: (route: Route) => void;
  openMandate: (id: string | null) => void;
  openAttempt: (id: string | null) => void;
  revoke: (id: string) => void;
  approve: (attemptId: string) => void;
  capture: (attemptId: string) => void;
  togglePsp: (online: boolean) => void;
  runJudgeTest: (id: string) => void;
  runScenario: (id: string) => void;
  reset: () => void;
  toast: (t: Omit<Toast, 'id'>) => void;
  dismissToast: (id: number) => void;
  mandateOf: (id: string) => Mandate | undefined;
  attemptOf: (id: string) => Attempt | undefined;
  evaluateAgainst: (mandateId: string, amount: number) => ReturnType<typeof evaluate>;
}

const Ctx = createContext<Store | null>(null);

const ROUTES: Route[] = [
  'overview',
  'mandates',
  'payments',
  'agent',
  'merchant',
  'ledger',
  'disputes',
  'judge',
];

export function StoreProvider({ children }: { children: ReactNode }) {
  const [state, dispatch] = useReducer(reducer, undefined, initialState);
  const timers = useRef<number[]>([]);

  const later = useCallback((fn: () => void, ms: number) => {
    timers.current.push(window.setTimeout(fn, ms));
  }, []);

  useEffect(() => () => timers.current.forEach(clearTimeout), []);

  // Hash routing, so the browser's back button behaves the way a judge expects.
  useEffect(() => {
    const sync = () => {
      const hash = window.location.hash.replace('#/', '') as Route;
      if (ROUTES.includes(hash)) dispatch({ type: 'navigate', route: hash });
    };
    sync();
    window.addEventListener('hashchange', sync);
    return () => window.removeEventListener('hashchange', sync);
  }, []);

  const toast = useCallback((t: Omit<Toast, 'id'>) => {
    dispatch({ type: 'toast', toast: t });
  }, []);

  const go = useCallback((route: Route) => {
    window.location.hash = `#/${route}`;
    dispatch({ type: 'navigate', route });
  }, []);

  const revoke = useCallback(
    (id: string) => {
      dispatch({ type: 'revoke', id });
      toast({
        tone: 'deny',
        title: 'Mandate revoked',
        body: 'Authority withdrawn. Propagated to the registry in 0.6 s.',
      });
    },
    [toast],
  );

  const approve = useCallback(
    (attemptId: string) => {
      dispatch({ type: 'approve', attemptId });
      toast({ tone: 'allow', title: 'Approved by Marta', body: 'Ed25519 signature verified.' });
    },
    [toast],
  );

  const capture = useCallback(
    (attemptId: string) => {
      dispatch({ type: 'capture', attemptId });
      toast({ tone: 'allow', title: 'Capture committed', body: 'Reservation moved to COMMITTED.' });
    },
    [toast],
  );

  const togglePsp = useCallback(
    (online: boolean) => {
      dispatch({ type: 'setPsp', online });
      if (!online) {
        toast({
          tone: 'hold',
          title: 'Processor unreachable',
          body: 'Payment held in confirmation. Budget stays reserved.',
        });
      } else {
        toast({ tone: 'verify', title: 'Processor online', body: 'Reconciling held payments.' });
        later(() => {
          dispatch({ type: 'reconciled' });
          toast({ tone: 'allow', title: 'Payment settled', body: 'Ledger reconciled with no divergence.' });
        }, 2200);
      }
    },
    [toast, later],
  );

  const runJudgeTest = useCallback(
    (id: string) => {
      dispatch({ type: 'judgeStart', id });
      const outcomes: Record<string, { observed: string; detail: string; tone: Toast['tone'] }> = {
        jt_psp_offline: {
          observed: 'IN_DOUBT',
          detail: 'No definitive response. Budget stays reserved, delivery stays blocked.',
          tone: 'hold',
        },
        jt_psp_decline: {
          observed: 'DECLINED_COMPENSATED',
          detail: 'Committed reservation released by compensating entry. Budget restored.',
          tone: 'deny',
        },
        jt_fake_webhook: {
          observed: 'WEBHOOK_SIGNATURE_INVALID',
          detail: 'Callback rejected at the edge. No state written.',
          tone: 'verify',
        },
        jt_dup_webhook: {
          observed: 'WEBHOOK_REPLAY',
          detail: 'Event ID already processed. Settlement applied exactly once.',
          tone: 'verify',
        },
        jt_griefing: {
          observed: 'RESERVATION_LIMIT',
          detail: 'Second live reservation refused. Mandate allows one at a time.',
          tone: 'deny',
        },
        jt_replay: {
          observed: 'REQUEST_NONCE_REPLAY',
          detail: 'Nonce already spent. Authorization not reissued.',
          tone: 'verify',
        },
        jt_panic: {
          observed: 'MANDATE_REVOKED',
          detail: 'Commit read REVOKED inside the same lock. Purchase rejected.',
          tone: 'deny',
        },
        jt_clock: {
          observed: 'DEMO_ENDPOINT_NOT_AVAILABLE',
          detail: '404. Clock control does not exist in this build.',
          tone: 'verify',
        },
      };
      const out = outcomes[id];
      later(() => {
        dispatch({ type: 'judgeDone', id, observed: out.observed, detail: out.detail });
        if (id === 'jt_panic') dispatch({ type: 'revoke', id: 'mandate_demo_01' });
        toast({ tone: out.tone, title: out.observed.replace(/_/g, ' '), body: out.detail });
      }, 900);
    },
    [later, toast],
  );

  const runScenario = useCallback(
    (id: string) => {
      dispatch({ type: 'reset' });
      dispatch({ type: 'scenario', id });
      const run = (route: Route, then?: () => void, delay = 80) =>
        later(() => {
          go(route);
          then?.();
        }, delay);

      switch (id) {
        case '01':
          run('overview');
          toast({ tone: 'allow', title: 'Happy path', body: '$130 authorized, captured and settled.' });
          break;
        case '02':
          run('agent', () => dispatch({ type: 'openAttempt', id: 'att_002' }));
          toast({ tone: 'escalate', title: 'Escalation', body: '$300 needs a human signature.' });
          break;
        case '03':
          run('mandates', () => {
            dispatch({ type: 'openMandate', id: 'mandate_demo_01' });
            later(() => dispatch({ type: 'revoke', id: 'mandate_demo_01' }), 700);
          });
          toast({ tone: 'deny', title: 'Revocation', body: 'Authority withdrawn mid-flight.' });
          break;
        case '04':
          run('payments', () => later(() => dispatch({ type: 'setPsp', online: false }), 400));
          toast({ tone: 'hold', title: 'Processor failure', body: 'Payment held, not declined.' });
          break;
        case '05':
          run('judge', () => later(() => runJudgeTest('jt_fake_webhook'), 400));
          break;
        case '06':
          run('judge', () => later(() => runJudgeTest('jt_replay'), 400));
          break;
        case '07':
          run('judge', () => later(() => runJudgeTest('jt_griefing'), 400));
          break;
      }
    },
    [go, later, toast, runJudgeTest],
  );

  const value = useMemo<Store>(
    () => ({
      state,
      metrics: deriveMetrics(state),
      go,
      openMandate: (id) => dispatch({ type: 'openMandate', id }),
      openAttempt: (id) => dispatch({ type: 'openAttempt', id }),
      revoke,
      approve,
      capture,
      togglePsp,
      runJudgeTest,
      runScenario,
      reset: () => {
        dispatch({ type: 'reset' });
        toast({ tone: 'verify', title: 'Demo reset', body: 'All mock state restored.' });
      },
      toast,
      dismissToast: (id) => dispatch({ type: 'dismissToast', id }),
      mandateOf: (id) => state.mandates.find((m) => m.id === id),
      attemptOf: (id) => state.attempts.find((a) => a.id === id),
      evaluateAgainst: (mandateId, amount) => {
        const m = state.mandates.find((x) => x.id === mandateId)!;
        return evaluate(m, amount);
      },
    }),
    [state, go, revoke, approve, capture, togglePsp, runJudgeTest, runScenario, toast],
  );

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useStore() {
  const ctx = useContext(Ctx);
  if (!ctx) throw new Error('useStore must be used inside StoreProvider');
  return ctx;
}
