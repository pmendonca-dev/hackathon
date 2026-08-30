import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode } from 'react';

import {
  AuthorizationGateway,
  GatewayError,
  type AgentRun,
  type Escalation,
  type LedgerEntry,
  type MandateView,
  type CatalogOffer,
  type Dispute,
  type Metrics,
  type OperatorJournal,
  type Watch,
} from '../gateways/authorizationGateway.ts';
import { signCompactJws, type HolderWallet } from '../wallet/holderKey.ts';
import { mandateCreationClaims } from '../wallet/mandateCreation.ts';
import { loadOrCreateWallet } from '../wallet/walletStore.ts';
import {
  AvalContext,
  type AvalContextValue,
  type ChainStatus,
  type CommandReceipt,
  type View,
} from './AvalContext.ts';

// Read one variable at a time, never the object. `const environment = import.meta.env`
// makes Vite inline the *whole* env record at that position, so every VITE_* value
// present at build time ships — including `VITE_AVAL_OPERATOR_TOKEN`, which switches
// off the processor, moves the demo clock and, with tampering on, corrupts the trail.
// A named member access is replaced with just that value, and nothing else follows it.

/**
 * Built once, outside render. It holds the base URL and, once a judge opens one, the
 * operator session; rebuilding it per render would reopen the question of which
 * instance a command went to every time React re-rendered.
 *
 * There is deliberately no operator token here. Reading one from the environment baked
 * a permanent secret into the bundle, which is a permanent secret published: anyone who
 * opened devtools on the demo page kept the processor switch, the clock and the price
 * knob forever. The console asks for it instead, once, and holds a session in memory.
 */
/**
 * Same origin unless someone names another one. The FastAPI process serves this build
 * itself, so in a deployment the API is wherever the page came from — and a baked-in
 * `http://127.0.0.1:8099` would send every judge's browser to *their own* laptop, where
 * nothing is listening. The variable stays for `vite dev`, which does run on two ports.
 */
const DEFAULT_GATEWAY = new AuthorizationGateway({
  baseUrl: import.meta.env.VITE_AVAL_API_BASE_URL ?? '',
});

const DEFAULT_PRINCIPAL = import.meta.env.VITE_AVAL_PRINCIPAL_ID ?? 'usr_marta';

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
  const [metrics, setMetrics] = useState<Metrics | null>(null);
  const [watches, setWatches] = useState<Watch[]>([]);
  const [serverNow, setServerNow] = useState<string | null>(null);
  const [offers, setOffers] = useState<CatalogOffer[]>([]);
  const [disputes, setDisputes] = useState<Dispute[]>([]);
  // Mirrors the gateway's own credential so React re-renders when it comes and goes.
  // The token itself is never held here, or anywhere else in this page.
  const [operatorSessionExpiresAt, setOperatorSessionExpiresAt] = useState<string | null>(null);
  const [operatorJournal, setOperatorJournal] = useState<OperatorJournal | null>(null);

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
            'The holder wallet could not be opened in this browser. Without it no ' +
              'spending authority can be signed.',
          );
        }
      });
    return () => {
      active = false;
    };
  }, [principalId]);

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    // The footer reads the whole instance rather than this buyer, so it is loaded
    // before the wallet gate below — and its failure never blanks the page: a missing
    // footer is a missing footer, not a broken session.
    try {
      setMetrics(await gateway.metrics());
    } catch {
      setMetrics(null);
    }
    // Read before the wallet gate for the same reason as the footer: it describes the
    // instance, not this buyer. Null means the runtime did not say — and the form that
    // uses it falls back to this browser's clock rather than inventing an instant.
    try {
      setServerNow(await gateway.serverNow());
    } catch {
      setServerNow(null);
    }
    try {
      setOffers((await gateway.offers()).offers);
    } catch {
      setOffers([]);
    }
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
          gateway.humanLedger(current, readToken),
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
        // Standing orders are a surface, not the record. An instance that does not
        // serve them still shows the mandate, the trail and every decision — so their
        // absence must not blank the page the way a missing ledger would.
        try {
          setWatches((await gateway.listWatches(current)).watches);
        } catch {
          setWatches([]);
        }
        // Same reasoning as the standing orders: an instance that does not serve
        // disputes still shows the mandate and the trail, so their absence must not
        // blank a page that is otherwise answering.
        try {
          setDisputes((await gateway.listDisputes(current, readToken)).disputes);
        } catch {
          setDisputes([]);
        }
      } else {
        setDisputes([]);
        setHumanEntries([]);
        setAuditorEntries([]);
        setMerchantEntries([]);
        setWatches([]);
        setChain(null);
      }
    } catch (caught) {
      setError(describe(caught).message);
    } finally {
      setLoading(false);
    }
    // `wallet` belongs here: the listings are signed with it, so a reload captured
    // before it existed would hold a null key and the page would stay empty for good.
    // Depending on it is also what makes the first load happen the moment it is ready.
  }, [gateway, principalId, wallet]);

  useEffect(() => {
    void reload();
  }, [reload]);

  const requireWallet = useCallback((): HolderWallet => {
    if (!wallet) throw new Error('The holder wallet is not ready yet.');
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
      operatorAvailable: gateway.hasOperatorSession,
      operatorSessionExpiresAt,
      operatorJournal,
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
      metrics,
      watches,
      disputes,
      serverNow,
      offers,

      setView,
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
          const terms = {
            principal: { id: principalId, display_name: input.displayName },
            allowed_merchant_ids: input.merchants,
            allowed_categories: input.categories,
            limit: input.limit,
            ceiling: input.ceiling,
            expires_at: input.expiresAt,
            usage_limit: input.usageLimit,
          };
          const created = await gateway.createMandate({
            ...terms,
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
            // And the same key signs the mandate into existence. The runtime refuses a
            // creation it cannot attribute, so the person who will be able to revoke is
            // provably the person who authorized — from position 0 of the trail.
            creation_jws: await signCompactJws(mandateCreationClaims(terms), holder),
          });
          setSelectedMandateId(created.mandate_id);
          // A mandate is born unfunded: authority to spend, and no means of paying.
          // Registering the card here keeps that a single action for the person, and the
          // three calls it costs are signed by this key like everything else.
          const card = await gateway.registerCard(created.mandate_id, (claims) =>
            signCompactJws(claims, holder),
          );
          return (
            `Mandate ${created.mandate_id} created at policy version ${created.policy_version}` +
            (card ? `, paying with ${card}.` : '. No card registered: it cannot pay yet.')
          );
        });
        if (accepted) await reload();
      },

      async runAgent(instruction: string) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        await run('Instruction to the agent', async () => {
          const result = await gateway.agentPurchase(mandateId, instruction);
          setLastRun(result);
          return `${result.outcome} · ${result.reason_code}`;
        });
        await reload();
      },

      async watchInstruction(instruction: string) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        const accepted = await run('Deixar o agente vigiando', async () => {
          const watch = await gateway.registerWatch(mandateId, instruction);
          return `Watch ${watch.watch_id} opened. The agent keeps trying on its own until ${watch.expires_at}.`;
        });
        if (accepted) await reload();
      },

      async tickWatches() {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        const accepted = await run('Try the watches now', async () => {
          const { fired } = await gateway.tickWatches(mandateId);
          // A tick that fired nothing is not a failure: the standing order is still
          // standing. Saying "nada aconteceu" is the honest reading of a watch whose
          // condition the catalogue has not met yet.
          return fired.length === 0
            ? 'No watch found an offer. They stay open.'
            : `${fired.length} watch(es) fired; the record below shows what they did.`;
        });
        if (accepted) await reload();
      },

      async decideEscalation(escalationId, decision) {
        const holder = requireWallet();
        const escalation = escalations.find((item) => item.id === escalationId);
        if (!escalation) return;
        const accepted = await run(
          decision === 'approve' ? 'Approve the escalation' : 'Refuse the escalation',
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
              ? 'Approval signed; the purchase resumed.'
              : 'Signed decision recorded.';
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
          return `The limit applies from policy version ${answer.policy_version}.`;
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
          return `Revoked at epoch ${answer.epoch}. The next attempt fails.`;
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
              reason: 'full stop by the holder',
              epoch: 1,
            },
            holder,
          );
          const answer = await gateway.revokeEverything(principalId, token);
          return `${answer.revoked_mandate_ids.length} mandato(s) encerrado(s).`;
        });
        if (accepted) await reload();
      },

      async openOperatorSession(token: string) {
        const accepted = await run('Open an operator session', async () => {
          const issued = await gateway.openOperatorSession(token);
          setOperatorSessionExpiresAt(issued.expires_at);
          return `Session ${issued.session_id} open until ${issued.expires_at}.`;
        });
        // The typed token is not kept anywhere — not in state, not in storage. What
        // this tab holds from here on is a credential that dies on its own.
        if (!accepted) setOperatorSessionExpiresAt(null);
      },

      async closeOperatorSession() {
        await run('End the operator session', async () => {
          await gateway.closeOperatorSession();
          return 'Session ended. The operator surfaces ask for the token again.';
        });
        setOperatorSessionExpiresAt(null);
        setOperatorJournal(null);
      },

      async loadOperatorJournal() {
        const accepted = await run('Read the operator journal', async () => {
          const journal = await gateway.operatorJournal();
          setOperatorJournal(journal);
          return `${journal.entries.length} ato(s) de operador, cadeia ${
            journal.chain.intact ? 'intact' : `broken at ${journal.chain.broken_at}`
          }.`;
        });
        if (!accepted) {
          setOperatorJournal(null);
          // A session the runtime has stopped honouring is gone from the gateway too,
          // so the console must stop claiming this tab is operating anything.
          if (!gateway.hasOperatorSession) setOperatorSessionExpiresAt(null);
        }
      },

      async disputePurchase(reservationId: string, reason: string) {
        const holder = requireWallet();
        const accepted = await run('I do not recognise this purchase', async () => {
          // Signed here for the same reason revoking is: the trail is about to record
          // that *this person* denied the purchase, and it should be true.
          const opened = await gateway.openDispute(
            reservationId,
            reason,
            await signCompactJws({ principal_id: principalId }, holder),
          );
          return `Disputa ${opened.dispute_id} aberta sobre ${reservationId}.`;
        });
        if (accepted) await reload();
      },

      async resolveDispute(disputeId: string) {
        const holder = requireWallet();
        const accepted = await run('Resolver pela trilha', async () => {
          const resolved = await gateway.resolveDispute(
            disputeId,
            await signCompactJws({ principal_id: principalId }, holder),
          );
          const liability = resolved.liability;
          return `${resolved.status} · ${liability.verdict} — responde: ${liability.liable_party}.`;
        });
        if (accepted) await reload();
      },

      async rogueCharge(minorUnits: number) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        const accepted = await run('Charge that bypasses the core', async () => {
          const charged = await gateway.rogueCharge(mandateId, minorUnits);
          return `${charged.reservation_id} cobrada sem passar pelo mandato. Nenhuma prova foi emitida.`;
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
          return `Reconciliation complete: ${JSON.stringify(answer)}`;
        });
        await reload();
      },

      async advanceClock(seconds: number) {
        await run('Advance the clock', async () => {
          const answer = await gateway.advanceClock(seconds);
          return `It is now ${answer.now} (offset of ${answer.offset_seconds}s).`;
        });
        await reload();
      },

      async repriceOffer(sku: string, minorUnits: number) {
        await run('Drop the price', async () => {
          const answer = await gateway.repriceOffer(sku, minorUnits);
          return `${answer.sku} is now ${answer.minor_units} cents. Open watches can fire from here.`;
        });
        await reload();
      },

      async tamperLedger(sequence: number) {
        const mandateId = selectedRef.current;
        if (!mandateId) return;
        await run('Adulterar trilha', async () => {
          await gateway.tamperLedger(mandateId, sequence);
          return `Event ${sequence} rewritten. The chain should now name that position.`;
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
      metrics,
      watches,
      disputes,
      operatorSessionExpiresAt,
      operatorJournal,
      serverNow,
      offers,
      reload,
      requireWallet,
      run,
    ],
  );

  return <AvalContext.Provider value={value}>{children}</AvalContext.Provider>;
}
