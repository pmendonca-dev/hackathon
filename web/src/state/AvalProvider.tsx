import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  AuthorizationGateway,
  GatewayError,
  type AgentRun,
  type Escalation,
  type LedgerEntry,
  type MandateView,
} from '../gateways/authorizationGateway.ts';
import { signCompactJws, type HolderWallet } from '../wallet/holderKey.ts';
import { loadOrCreateWallet } from '../wallet/walletStore.ts';
import {
  AvalContext,
  type AvalContextValue,
  type ChainStatus,
  type CommandReceipt,
  type View,
} from './AvalContext.ts';

const environment = import.meta.env;

/**
 * Built once, outside render. The gateway holds the operator token and the base URL;
 * rebuilding it per render would reopen the question of which instance a command went
 * to every time React re-rendered.
 */
const DEFAULT_GATEWAY = new AuthorizationGateway({
  baseUrl: environment.VITE_AVAL_API_BASE_URL ?? 'http://127.0.0.1:8099',
  operatorToken: environment.VITE_AVAL_OPERATOR_TOKEN,
});

/** Fast enough that a judge sees their own tap land; slow enough to stay boring. */
const LIVE_INTERVAL_MS = 4000;

const DEFAULT_PRINCIPAL = environment.VITE_AVAL_PRINCIPAL_ID ?? 'usr_marta';

function describe(error: unknown): { reasonCode: string | null; message: string } {
  if (error instanceof GatewayError) return { reasonCode: error.reasonCode, message: error.message };
  return { reasonCode: null, message: error instanceof Error ? error.message : 'Falha desconhecida.' };
}

export function AvalProvider({
  children,
  gateway = DEFAULT_GATEWAY,
}: {
  children: ReactNode;
  gateway?: AuthorizationGateway;
}) {
  const [principalId, setPrincipalIdState] = useState(DEFAULT_PRINCIPAL);
  const [view, setView] = useState<View>('human');
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [wallet, setWallet] = useState<HolderWallet | null>(null);
  const [live, setLive] = useState(true);

  const [mandates, setMandates] = useState<MandateView[]>([]);
  const [selectedMandateId, setSelectedMandateId] = useState<string | null>(null);
  const [escalations, setEscalations] = useState<Escalation[]>([]);
  const [lastRun, setLastRun] = useState<AgentRun | null>(null);
  const [humanEntries, setHumanEntries] = useState<LedgerEntry[]>([]);
  const [auditorEntries, setAuditorEntries] = useState<LedgerEntry[]>([]);
  const [merchantEntries, setMerchantEntries] = useState<LedgerEntry[]>([]);
  const [merchantRedactions, setMerchantRedactions] = useState<string[]>([]);
  const [chain, setChain] = useState<ChainStatus | null>(null);
  const [receipts, setReceipts] = useState<CommandReceipt[]>([]);

  // `reload` must not depend on the selection — it would re-create the callback and
  // re-fire the load effect on every mandate click. The ref carries the current choice
  // to it instead, synced in an effect rather than during render.
  const selectedRef = useRef<string | null>(null);
  useEffect(() => {
    selectedRef.current = selectedMandateId;
  }, [selectedMandateId]);

  const note = useCallback((receipt: CommandReceipt) => {
    setReceipts((previous) => [receipt, ...previous].slice(0, 12));
  }, []);

  /**
   * Every command reports what the runtime actually answered — including "no answer".
   * A browser that rendered a network failure as a refusal would tell a judge the
   * mandate said no when it was never asked.
   */
  const run = useCallback(
    async (label: string, action: () => Promise<string>): Promise<boolean> => {
      try {
        const message = await action();
        note({ label, outcome: 'accepted', reasonCode: null, message, at: new Date().toISOString() });
        return true;
      } catch (caught) {
        const { reasonCode, message } = describe(caught);
        note({
          label,
          outcome: reasonCode === 'runtime_unreachable' ? 'unreachable' : 'refused',
          reasonCode,
          message,
          at: new Date().toISOString(),
        });
        return false;
      }
    },
    [note],
  );

  useEffect(() => {
    let active = true;
    loadOrCreateWallet(principalId)
      .then((loaded) => {
        if (active) setWallet(loaded);
      })
      .catch(() => {
        if (active) {
          setError(
            'Não foi possível abrir a carteira do titular neste navegador. Sem ela nenhuma ' +
              'autoridade de gasto pode ser assinada.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [principalId]);

  const reload = useCallback(async (silent = false) => {
    // A timed re-read must not paint. Flipping `loading` every few seconds would spin
    // the header button and blank the first paint's placeholder on a loop, which reads
    // as an unstable page rather than a live one.
    if (!silent) setLoading(true);
    setError(null);
    try {
      // Both principal-scoped listings are signed by the wallet: the id in the URL is a
      // guessable name, and the key is what decides which mandates come back. Before the
      // wallet exists there is nothing this page could be entitled to see anyway.
      if (!wallet) {
        setMandates([]);
        setEscalations([]);
        return;
      }
      const readToken = await signCompactJws({ principal_id: principalId }, wallet);
      const [listed, pending] = await Promise.all([
        gateway.listMandates(principalId, readToken),
        gateway.listEscalations(principalId, readToken),
      ]);
      setMandates(listed.mandates);
      setEscalations(pending.escalations);

      const current =
        selectedRef.current && listed.mandates.some((item) => item.mandate_id === selectedRef.current)
          ? selectedRef.current
          : (listed.mandates[0]?.mandate_id ?? null);
      setSelectedMandateId(current);

      if (current) {
        const [human, auditor] = await Promise.all([
          gateway.humanLedger(current),
          gateway.auditorLedger(current),
        ]);
        setHumanEntries(human.entries);
        setAuditorEntries(auditor.entries);
        setChain(auditor.chain);
        const merchantId = human.mandate.allowed_merchant_ids[0];
        if (merchantId) {
          const merchant = await gateway.merchantLedger(merchantId);
          setMerchantEntries(merchant.entries);
          setMerchantRedactions(merchant.redacted);
        }
      } else {
        setHumanEntries([]);
        setAuditorEntries([]);
        setMerchantEntries([]);
        setChain(null);
      }
    } catch (caught) {
      setError(describe(caught).message);
    } finally {
      if (!silent) setLoading(false);
    }
    // `wallet` belongs here: the listings are signed with it, so a reload captured
    // before it existed would hold a null key and the page would stay empty for good.
    // Depending on it is also what makes the first load happen the moment it is ready.
  }, [gateway, principalId, wallet]);

  useEffect(() => {
    void reload();
  }, [reload]);

  /**
   * Live mode. The demo is driven from a phone while this is on a projector, so the
   * screen re-reads on its own — and stops while the tab is hidden, because a laptop
   * left on a slide should not keep a connection warm for nothing.
   */
  useEffect(() => {
    if (!live) return;
    const timer = setInterval(() => {
      if (!document.hidden) void reload(true);
    }, LIVE_INTERVAL_MS);
    return () => clearInterval(timer);
  }, [live, reload]);

  // The token of the card each mandate currently names. The runtime deliberately never
  // serves it back, so the browser that bound it is the only thing that can name it as
  // the one a replacement supersedes.
  const boundCards = useRef<Record<string, string>>({});

  const requireWallet = useCallback((): HolderWallet => {
    if (!wallet) throw new Error('A carteira do titular ainda não está pronta.');
    return wallet;
  }, [wallet]);

  const value: AvalContextValue = useMemo(
    () => ({
      principalId,
      holderKid: wallet?.kid ?? null,
      walletReady: wallet !== null,
      view,
      loading,
      error,
      live,
      gateway,
      operatorAvailable: gateway.hasOperatorToken,
      mandates,
      selectedMandateId,
      escalations,
      lastRun,
      humanEntries,
      auditorEntries,
      merchantEntries,
      merchantRedactions,
      chain,
      receipts,

      setView,
      setLive,
      setPrincipalId: (next: string) => {
        setPrincipalIdState(next);
        setSelectedMandateId(null);
        setWallet(null);
      },
      selectMandate: setSelectedMandateId,
      reload,

      async createMandate(input) {
        const holder = requireWallet();
        const accepted = await run('Criar mandato', async () => {
          const created = await gateway.createMandate({
            principal: { id: principalId, display_name: input.displayName },
            allowed_merchant_ids: input.merchants,
            allowed_categories: input.categories,
            limit: input.limit,
            ceiling: input.ceiling,
            expires_at: input.expiresAt,
            usage_limit: input.usageLimit,
            // The browser's own public key becomes the mandate's holder authority.
            // This is what makes later revocation and approval signable here — and what
            // keeps the server from ever being able to produce them.
            authorities: [
              {
                kid: holder.kid,
                role: 'holder',
                public_jwk: holder.publicJwk,
                allowed_scopes: ['mandate', 'budget:zero'],
              },
            ],
          });
          setSelectedMandateId(created.mandate_id);
          return `Mandato ${created.mandate_id} criado na versão de política ${created.policy_version}.`;
        });
        if (accepted) await reload();
      },

      async registerCard() {
        const holder = requireWallet();
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        const accepted = await run('Cadastrar cartão', async () => {
          // Both calls carry the same scoped claim: opening the processor's form
          // creates objects over there, and an endpoint anyone who guesses a mandate
          // id can drive is an abuse surface even when it grants nothing.
          const sessionClaim = { mandate_id: mandateId, scope: 'instrument_session' };
          const session = await gateway.openInstrumentSession(
            mandateId,
            await signCompactJws(sessionClaim, holder),
          );
          const card = await gateway.readInstrumentSession(
            mandateId,
            session.session_id,
            await signCompactJws(sessionClaim, holder),
          );
          if (!card.ready || !card.token || !card.label) {
            return `Formulário aberto em ${session.url}. Ainda não há cartão nele.`;
          }
          const answer = await gateway.bindInstrument(
            mandateId,
            card.token,
            card.label,
            await signCompactJws(
              {
                mandate_id: mandateId,
                scope: 'instrument',
                instrument_token: card.token,
                instrument_label: card.label,
                // Compare-and-swap: names the card bound right now, so a captured
                // binding is dead the moment any other one lands.
                supersedes: boundCards.current[mandateId] ?? null,
              },
              holder,
            ),
          );
          // The API never serves the token back — it is a credential, not a field —
          // so the only place that can remember it for the next swap is here.
          boundCards.current[mandateId] = card.token;
          return `Cartão ${answer.instrument_label} vinculado ao mandato.`;
        });
        if (accepted) await reload();
      },

      async runAgent(instruction: string) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        await run('Instrução ao agente', async () => {
          const result = await gateway.agentPurchase(mandateId, instruction);
          setLastRun(result);
          return `${result.outcome} · ${result.reason_code}`;
        });
        await reload();
      },

      async decideEscalation(escalationId, decision) {
        const holder = requireWallet();
        const escalation = escalations.find((item) => item.id === escalationId);
        if (!escalation) return;
        const accepted = await run(
          decision === 'approve' ? 'Aprovar escalação' : 'Recusar escalação',
          async () => {
            // The signature names the exact purchase, so an approval lifted from one
            // decision cannot be replayed onto a larger one.
            const approval = await signCompactJws(
              {
                decision_handle: escalation.id,
                mandate_id: escalation.mandate_id,
                decision,
                amount_minor_units: escalation.amount.minor_units,
              },
              holder,
            );
            const answer = await gateway.decideEscalation(escalationId, decision, approval);
            return (answer as { resumed?: boolean }).resumed
              ? 'Aprovação assinada; a compra retomou.'
              : 'Decisão assinada registrada.';
          },
        );
        if (accepted) await reload();
      },

      async changeLimit(minorUnits: number) {
        const holder = requireWallet();
        const mandate = mandates.find((item) => item.mandate_id === selectedRef.current);
        if (!mandate) return;
        const accepted = await run('Mudar limite', async () => {
          const authorization = await signCompactJws(
            {
              mandate_id: mandate.mandate_id,
              limit_minor_units: minorUnits,
              currency: mandate.limit.currency,
              scale: mandate.limit.scale,
              // The version this change supersedes. It is what stops the token being
              // replayed later to restore a limit the holder has already lowered.
              policy_version: mandate.policy_version,
            },
            holder,
          );
          const answer = await gateway.changeLimit(
            mandate.mandate_id,
            { minor_units: minorUnits, currency: mandate.limit.currency, scale: mandate.limit.scale },
            authorization,
          );
          return `Limite vale a partir da política ${answer.policy_version}.`;
        });
        if (accepted) await reload();
      },

      async revokeSelected() {
        const holder = requireWallet();
        const mandate = mandates.find((item) => item.mandate_id === selectedRef.current);
        if (!mandate) return;
        const accepted = await run('Revogar mandato', async () => {
          const token = await signCompactJws(
            {
              mandate_id: mandate.mandate_id,
              scope: 'mandate',
              reason: 'revogado pelo titular',
              epoch: mandate.revocation_epoch + 1,
            },
            holder,
          );
          const answer = await gateway.revokeMandate(mandate.mandate_id, token);
          return `Revogado na época ${answer.epoch}. A próxima tentativa falha.`;
        });
        if (accepted) await reload();
      },

      async revokeEverything() {
        const holder = requireWallet();
        const accepted = await run('Revogar tudo', async () => {
          const token = await signCompactJws(
            {
              principal_id: principalId,
              scope: 'mandate',
              reason: 'interrupção total pelo titular',
              epoch: 1,
            },
            holder,
          );
          const answer = await gateway.revokeEverything(principalId, token);
          return `${answer.revoked_mandate_ids.length} mandato(s) encerrado(s).`;
        });
        if (accepted) await reload();
      },

      async setPspMode(mode) {
        await run(`Processador ${mode}`, async () => {
          await gateway.setPspMode(mode);
          return `Processador agora em modo ${mode}.`;
        });
      },

      async reconcile() {
        await run('Reconciliar', async () => {
          const answer = await gateway.reconcile();
          return `Reconciliação concluída: ${JSON.stringify(answer)}`;
        });
        await reload();
      },

      async advanceClock(seconds: number) {
        await run('Avançar relógio', async () => {
          const answer = await gateway.advanceClock(seconds);
          return `Agora é ${answer.now} (deslocamento de ${answer.offset_seconds}s).`;
        });
        await reload();
      },

      async tamperLedger(sequence: number) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        await run('Adulterar trilha', async () => {
          await gateway.tamperLedger(mandateId, sequence);
          return `Evento ${sequence} reescrito. A cadeia deve acusar a posição.`;
        });
        await reload();
      },
    }),
    [
      principalId,
      wallet,
      view,
      loading,
      error,
      live,
      gateway,
      mandates,
      escalations,
      selectedMandateId,
      lastRun,
      humanEntries,
      auditorEntries,
      merchantEntries,
      merchantRedactions,
      chain,
      receipts,
      reload,
      requireWallet,
      run,
    ],
  );

  return <AvalContext.Provider value={value}>{children}</AvalContext.Provider>;
}
