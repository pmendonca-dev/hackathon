/**
 * The browser's transport to AVAL's authorization lane.
 *
 * This is the lane the case is about: mandates, the agent's free-text purchase,
 * escalations, the trail and the trial-by-fire commands. Its human surfaces are
 * unauthenticated by design, which is what makes them reachable from a page at all —
 * the protocol lane demands an RFC 9421 signature over the raw request bytes, and a
 * browser cannot produce one without being handed a trusted key it must never hold.
 *
 * Nothing here decides anything. It carries requests and returns what the runtime
 * said, including refusals: a `reason_code` from the core is surfaced verbatim rather
 * than reinterpreted, because the browser inventing its own explanation of a refusal
 * is how a UI ends up disagreeing with the system it is describing.
 */

export interface Money {
  minor_units: number;
  currency: string;
  scale: number;
}

export interface EvaluationStep {
  check: string;
  passed: boolean;
  detail: string | null;
}

export interface UsageLimit {
  max_uses: number;
  window_seconds: number;
}

export interface MandateView {
  mandate_id: string;
  status: string;
  principal: { id: string; display_name: string };
  allowed_merchant_ids: string[];
  allowed_categories: string[];
  limit: Money;
  ceiling: Money | null;
  spent: Money;
  remaining: Money;
  expires_at: string;
  policy_version: number;
  revocation_epoch: number;
  usage_limit: UsageLimit | null;
  uses_in_window: number;
}

export interface AgentRun {
  outcome: string;
  reason_code: string;
  human_summary: string;
  offer: Record<string, unknown> | null;
  escalation_id: string | null;
  reservation_id: string | null;
  settlement_reference: string | null;
  authorization_proof: string | null;
  offers_considered: number;
  evaluation_trace: EvaluationStep[];
}

/** Who answers for a purchase, recomputed from the trail on every read. */
export interface Liability {
  verdict: string;
  liable_party: string;
  basis: string[];
  holder_signatures: Array<{ kind: string; kid: string }>;
  mandate_repudiation: string;
  repudiation_note: string;
}

/** A purchase the holder says they do not recognise, and what the trail answered. */
export interface Dispute {
  id: string;
  reservation_id: string;
  reason: string;
  status: string;
  resolution: string | null;
  opened_at: string;
  resolved_at: string | null;
  liability: Liability;
}

/** What operator credentials did, and the chain that proves nothing was removed. */
export interface OperatorJournal {
  entries: Array<{
    sequence: number;
    action: string;
    actor: string;
    occurred_at: string;
    sha256: string;
  }>;
  chain: { intact: boolean; checked: number; broken_at: number | null };
}

/** A signed offer from the merchant. The price is what a standing order waits on. */
export interface CatalogOffer {
  offer_id: string;
  merchant_id: string;
  item: { sku: string; title: string; category: string };
  total: Money;
}

/** A standing order the agent keeps trying after the person stopped typing. */
export interface Watch {
  watch_id: string;
  mandate_id: string;
  instruction: string;
  status: string;
  outcome: string | null;
  settlement_reference: string | null;
  created_at: string;
  expires_at: string;
  closed_at: string | null;
}

export interface Escalation {
  id: string;
  mandate_id: string;
  checkout_id: string;
  merchant_id: string;
  category: string;
  amount: Money;
  reason_code: string;
  status: string;
  created_at: string;
  expires_at: string;
}

export interface LedgerEntry {
  sequence?: number;
  event_type: string;
  human_summary: string;
  occurred_at: string;
  [key: string]: unknown;
}

export interface Metrics {
  decisions: { authorized: number; awaiting_human: number; rejected: number };
  reasons: Record<string, number>;
  payments: { settled: number; declined: number; in_doubt: number };
  /** Money held or settled with no authorization proof bound to it. Reads zero. */
  spend_outside_mandate: Money;
  edge_refusals: Record<string, number>;
  latency_ms: Record<string, { count: number; p50: number; p99: number; max: number }>;
}

/** A refusal or a transport failure, carrying the runtime's own vocabulary. */
export class GatewayError extends Error {
  readonly reasonCode: string;
  readonly status: number;

  constructor(reasonCode: string, message: string, status: number) {
    super(message);
    this.name = 'GatewayError';
    this.reasonCode = reasonCode;
    this.status = status;
  }
}

export interface AuthorizationGatewayOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
}

export class AuthorizationGateway {
  readonly #baseUrl: string;
  readonly #fetch: typeof globalThis.fetch;
  /**
   * The operator credential this page holds, if someone opened one.
   *
   * It is a *session*, never the token. The token used to be built into the bundle,
   * which means anyone who opened devtools on the demo page walked away with the
   * processor switch, the clock and the price knob — permanently. Now the token is
   * typed once, exchanged here, and what stays in memory expires on its own and can be
   * closed. It is still deliberately powerless over money: raising a limit or approving
   * an escalation needs the holder's key, which lives in the wallet and never here.
   */
  #operatorSession?: string;

  constructor({ baseUrl, fetch }: AuthorizationGatewayOptions) {
    this.#baseUrl = baseUrl.replace(/\/$/, '');
    this.#fetch = fetch ?? globalThis.fetch.bind(globalThis);
  }

  get hasOperatorSession(): boolean {
    return Boolean(this.#operatorSession);
  }

  /** Present the token once, keep the session. Nothing is written to storage: a
   *  credential persisted across reloads is a credential a shared laptop inherits. */
  async openOperatorSession(token: string): Promise<{ session_id: string; expires_at: string }> {
    const issued = await this.#request<{
      session_id: string;
      session_token: string;
      expires_at: string;
    }>('/admin/operator/sessions', { method: 'POST', headers: { 'X-Aval-Operator': token } });
    this.#operatorSession = issued.session_token;
    return { session_id: issued.session_id, expires_at: issued.expires_at };
  }

  async closeOperatorSession(): Promise<void> {
    if (!this.#operatorSession) return;
    try {
      await this.#request('/admin/operator/sessions/current', { method: 'DELETE', operator: true });
    } finally {
      // Forgotten here whatever the runtime answered: a console that kept a credential
      // it just tried to end would be lying about what it holds.
      this.#operatorSession = undefined;
    }
  }

  /** What operator credentials did, and the chain that proves nothing was removed. */
  operatorJournal(): Promise<OperatorJournal> {
    return this.#request('/admin/operator/journal', { operator: true });
  }

  /** A charge that never passed the core, so the reversal can be watched instead of
   *  described. Mounted only when the runtime was started with AVAL_DEMO_ROGUE. */
  rogueCharge(mandateId: string, minorUnits: number): Promise<{ reservation_id: string }> {
    return this.#request('/admin/demo/rogue-charge', {
      method: 'POST',
      body: { mandate_id: mandateId, minor_units: minorUnits },
      operator: true,
    });
  }

  async #request<T>(
    path: string,
    { method = 'GET', body, operator = false, headers: extraHeaders }: {
      method?: string;
      body?: unknown;
      operator?: boolean;
      headers?: Record<string, string>;
    } = {},
  ): Promise<T> {
    const headers: Record<string, string> = { ...extraHeaders };
    if (body !== undefined) headers['content-type'] = 'application/json';
    if (operator) {
      // Fail before the request rather than after a 403: a judge whose session ran out
      // should be asked for the token again, not shown a refusal from the server.
      if (!this.#operatorSession) {
        throw new GatewayError(
          'operator_session_missing',
          'Nenhuma sessão de operador aberta nesta aba.',
          0,
        );
      }
      headers['X-Aval-Operator-Session'] = this.#operatorSession;
    }

    let response: Response;
    try {
      response = await this.#fetch(`${this.#baseUrl}${path}`, {
        method,
        headers,
        ...(body === undefined ? {} : { body: JSON.stringify(body) }),
      });
    } catch {
      // Unreachable is not refused. Rendering a network failure as a denial would tell
      // a judge the mandate said no when the runtime never answered at all.
      throw new GatewayError(
        'runtime_unreachable',
        'O runtime não respondeu. Nenhuma decisão foi tomada.',
        0,
      );
    }

    const payload = await response.json().catch(() => ({}));
    if (!response.ok) {
      const detail = (payload as { detail?: { code?: string } }).detail;
      const reasonCode =
        (payload as { reason_code?: string }).reason_code ?? detail?.code ?? 'request_failed';
      // A credential the runtime has stopped honouring is not a credential. Dropping it
      // here is what makes the console ask for the token again instead of retrying with
      // something dead and reporting a mystery.
      if (reasonCode === 'operator_session_expired' || reasonCode === 'operator_session_invalid') {
        this.#operatorSession = undefined;
      }
      throw new GatewayError(
        reasonCode,
        (payload as { human_summary?: string }).human_summary ?? `HTTP ${response.status}`,
        response.status,
      );
    }
    return payload as T;
  }

  // ---- reading -----------------------------------------------------------

  /**
   * A principal id is a name anyone can guess — `usr_tg_{chat_id}` in the bot,
   * `usr_marta` here — so both principal-scoped listings carry a holder signature and
   * answer only for the mandates that key actually holds. A key that holds nothing gets
   * an empty list, which is also what a holder sees before creating their first mandate.
   */
  listMandates(
    principalId: string,
    authorizationJws: string,
  ): Promise<{ principal_id: string; mandates: MandateView[] }> {
    return this.#request(
      `/mandates?principal_id=${encodeURIComponent(principalId)}` +
        `&authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  /**
   * One mandate, read with the holder's signature.
   *
   * The id is not a secret — it is in the receipt, in the address bar and in any
   * screenshot — so sight is proved by the key that holds the mandate, the same way
   * revoking it is. The signature is over `{principal_id}` and reaches exactly the
   * mandates that key could already end.
   */
  readMandate(mandateId: string, authorizationJws: string): Promise<MandateView> {
    return this.#request(
      `/mandates/${encodeURIComponent(mandateId)}` +
        `?authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  listEscalations(
    principalId: string,
    authorizationJws: string,
  ): Promise<{ escalations: Escalation[] }> {
    return this.#request(
      `/escalations?principal_id=${encodeURIComponent(principalId)}` +
        `&authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  /** The person's own record: limits, spend and what was bought. Holder-signed for the
   *  same reason `readMandate` is — the auditor view stays open, this one does not. */
  humanLedger(
    mandateId: string,
    authorizationJws: string,
  ): Promise<{ mandate: MandateView; entries: LedgerEntry[] }> {
    return this.#request(
      `/ledger?view=human&mandate_id=${encodeURIComponent(mandateId)}` +
        `&authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  auditorLedger(
    mandateId: string,
  ): Promise<{
    mandate: MandateView;
    entries: LedgerEntry[];
    chain: { intact: boolean; checked: number; broken_at: number | null };
  }> {
    return this.#request(`/ledger?view=auditor&mandate_id=${encodeURIComponent(mandateId)}`);
  }

  /** By merchant id only. Passing a mandate id would hand the merchant the very
   *  identifier this projection exists to withhold. */
  merchantLedger(
    merchantId: string,
  ): Promise<{ entries: LedgerEntry[]; redacted: string[] }> {
    return this.#request(`/ledger?view=merchant&merchant_id=${encodeURIComponent(merchantId)}`);
  }

  verifyLedger(
    mandateId: string,
  ): Promise<{ intact: boolean; checked: number; broken_at: number | null }> {
    return this.#request(`/ledger/verify?mandate_id=${encodeURIComponent(mandateId)}`);
  }

  offers(merchantId = 'vuelaya'): Promise<{ offers: CatalogOffer[] }> {
    return this.#request(`/merchant/offers?merchant_id=${encodeURIComponent(merchantId)}`);
  }

  /**
   * The live footer. Aggregates of the same hash-chained trail the auditor tab reads,
   * so the two can never disagree — which is the reason the page asks for them instead
   * of counting what it happens to have loaded.
   *
   * No operator token: it reads counters and decides nothing.
   */
  metrics(): Promise<Metrics> {
    return this.#request('/metrics');
  }

  merchantVerify(
    authorizationProof: string,
    merchantAuthorization: string,
  ): Promise<{ accepted: boolean; checks: Array<{ name: string; passed: boolean }> }> {
    return this.#request('/merchant/verify', {
      method: 'POST',
      body: { authorization_proof: authorizationProof, merchant_authorization: merchantAuthorization },
    });
  }

  /** Disputes on one mandate, read by the key that holds it: the listing carries the
   *  reasons a person wrote about their own purchases. */
  listDisputes(mandateId: string, authorizationJws: string): Promise<{ disputes: Dispute[] }> {
    return this.#request(
      `/disputes?mandate_id=${encodeURIComponent(mandateId)}` +
        `&authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  /** The standing orders this mandate is carrying, open and closed. */
  listWatches(mandateId: string): Promise<{ watches: Watch[] }> {
    return this.#request(`/agent/watches?mandate_id=${encodeURIComponent(mandateId)}`);
  }

  /**
   * The instant the runtime reads validity against — which is not the browser's.
   *
   * A judge may move the demo clock forward at any point, and a form that dated
   * `expires_at` off this laptop would then create mandates that are already expired.
   */
  async serverNow(): Promise<string> {
    const { now } = await this.#request<{ status: string; now: string }>('/health');
    return now;
  }

  // ---- acting ------------------------------------------------------------

  createMandate(payload: Record<string, unknown>): Promise<{
    mandate_id: string;
    policy_version: number;
    revocation_id: string;
  }> {
    return this.#request('/mandates', { method: 'POST', body: payload });
  }

  agentPurchase(mandateId: string, instruction: string): Promise<AgentRun> {
    return this.#request('/agent/purchase', {
      method: 'POST',
      body: { mandate_id: mandateId, instruction },
    });
  }

  /**
   * A standing order: the same free text, kept for later.
   *
   * It carries no authority of its own. Firing means calling the very same purchase
   * path, so a watch against a revoked mandate is refused exactly like a typed
   * instruction would be — the autonomy is in *when* the agent acts, never in *what*
   * it may do.
   */
  registerWatch(mandateId: string, instruction: string): Promise<Watch> {
    return this.#request('/agent/watches', {
      method: 'POST',
      body: { mandate_id: mandateId, instruction },
    });
  }

  /** Try every open watch on this mandate once. This is the agent acting unwatched. */
  tickWatches(mandateId: string): Promise<{ fired: Array<Record<string, unknown>> }> {
    return this.#request('/agent/watches/tick', {
      method: 'POST',
      body: { mandate_id: mandateId },
    });
  }

  /** Holder-signed. The JWS is produced in the wallet; this only carries it. */
  changeLimit(
    mandateId: string,
    limit: Money,
    authorizationJws: string,
  ): Promise<{ policy_version: number; epoch: number }> {
    return this.#request(`/mandates/${encodeURIComponent(mandateId)}/limit`, {
      method: 'PATCH',
      body: { limit, authorization_jws: authorizationJws },
    });
  }

  revokeMandate(mandateId: string, token: string): Promise<{ revoked: boolean; epoch: number }> {
    return this.#request(`/mandates/${encodeURIComponent(mandateId)}/revocation`, {
      method: 'POST',
      body: { token },
    });
  }

  revokeEverything(
    principalId: string,
    token: string,
  ): Promise<{ principal_id: string; revoked_mandate_ids: string[] }> {
    return this.#request(`/principals/${encodeURIComponent(principalId)}/revocations`, {
      method: 'POST',
      body: { token },
    });
  }

  decideEscalation(
    escalationId: string,
    decision: 'approve' | 'deny',
    approvalJws: string,
  ): Promise<Record<string, unknown>> {
    return this.#request(`/escalations/${encodeURIComponent(escalationId)}/decision`, {
      method: 'POST',
      body: { decision, approval_jws: approvalJws },
    });
  }

  /**
   * Deny a purchase, signed by the key that holds the mandate it was made under.
   *
   * The trail records this as the holder contesting a purchase and names the key that
   * did it, so an unsigned dispute would write a claim about who acted into the evidence
   * an arbitration reads later.
   */
  openDispute(
    reservationId: string,
    reason: string,
    authorizationJws: string,
  ): Promise<{ dispute_id: string }> {
    return this.#request('/disputes', {
      method: 'POST',
      body: { reservation_id: reservationId, reason, authorization_jws: authorizationJws },
    });
  }

  /** Signed too: resolution stopped being a harmless read when the verdict began
   *  moving money — it decides when the value goes back. */
  resolveDispute(
    disputeId: string,
    authorizationJws: string,
  ): Promise<{
    dispute_id: string;
    status: string;
    resolution: string | null;
    liability: Liability;
  }> {
    return this.#request(`/disputes/${encodeURIComponent(disputeId)}/resolution`, {
      method: 'POST',
      body: { authorization_jws: authorizationJws },
    });
  }

  // ---- operator surfaces -------------------------------------------------

  setPspMode(mode: 'online' | 'offline' | 'decline'): Promise<{ mode: string }> {
    return this.#request('/admin/psp', { method: 'POST', body: { mode }, operator: true });
  }

  reconcile(): Promise<Record<string, number>> {
    return this.#request('/reconcile', { method: 'POST', operator: true });
  }

  /**
   * Move a catalogue price so a standing order has something to fire on.
   *
   * It sits among the operator commands because it authorizes nothing: the watch it
   * wakes still has to survive the same mandate the typed instruction would.
   */
  repriceOffer(sku: string, minorUnits: number): Promise<{ sku: string; minor_units: number }> {
    return this.#request('/admin/catalog/price', {
      method: 'POST',
      body: { sku, minor_units: minorUnits },
      operator: true,
    });
  }

  /** Forward only. The runtime refuses a rewind; the browser does not pretend otherwise. */
  advanceClock(seconds: number): Promise<{ now: string; offset_seconds: number }> {
    return this.#request('/admin/clock', {
      method: 'POST',
      body: { advance_seconds: seconds },
      operator: true,
    });
  }

  tamperLedger(mandateId: string, sequence: number): Promise<Record<string, unknown>> {
    return this.#request(`/admin/ledger/${encodeURIComponent(mandateId)}/tamper`, {
      method: 'POST',
      body: { sequence },
      operator: true,
    });
  }
}
