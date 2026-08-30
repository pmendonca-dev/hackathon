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
  /** The card's last four, never its token: the trail is read by people who may not present it. */
  instrument_label: string | null;
  instrument_revoked: boolean;
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

export interface TelegramChat {
  chat_id: number;
  display_name: string;
  principal_id: string;
  mandate_id: string | null;
}

export interface AuthorizationGatewayOptions {
  baseUrl: string;
  fetch?: typeof globalThis.fetch;
  /**
   * Guards the processor switch, reconcile, the demo clock and the tamper tool. It is
   * deliberately powerless over money: raising a limit or approving an escalation
   * needs the holder's key, which lives in the browser wallet and never here.
   */
  operatorToken?: string;
}

export class AuthorizationGateway {
  readonly #baseUrl: string;
  readonly #fetch: typeof globalThis.fetch;
  readonly #operatorToken?: string;

  constructor({ baseUrl, fetch, operatorToken }: AuthorizationGatewayOptions) {
    this.#baseUrl = baseUrl.replace(/\/$/, '');
    this.#fetch = fetch ?? globalThis.fetch.bind(globalThis);
    this.#operatorToken = operatorToken;
  }

  get hasOperatorToken(): boolean {
    return Boolean(this.#operatorToken);
  }

  async #request<T>(
    path: string,
    { method = 'GET', body, operator = false }: {
      method?: string;
      body?: unknown;
      operator?: boolean;
    } = {},
  ): Promise<T> {
    const headers: Record<string, string> = {};
    if (body !== undefined) headers['content-type'] = 'application/json';
    if (operator) {
      // Fail before the request rather than after a 401: a judge who forgot the token
      // should be told what is missing, not shown a refusal from the server.
      if (!this.#operatorToken) {
        throw new GatewayError(
          'operator_token_missing',
          'Nenhum token de operador configurado nesta sessão.',
          0,
        );
      }
      headers['X-Aval-Operator'] = this.#operatorToken;
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
      throw new GatewayError(
        (payload as { reason_code?: string }).reason_code ?? detail?.code ?? 'request_failed',
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
   * The chat directory the bot keeps on disk. Operator-gated, and deliberately thin:
   * it never carries a chat's private key, so a screen built on it can follow a chat
   * without ever being able to act as one.
   */
  listTelegramChats(): Promise<{ chats: TelegramChat[] }> {
    return this.#request('/admin/telegram/chats', { operator: true });
  }

  readMandate(mandateId: string): Promise<MandateView> {
    return this.#request(`/mandates/${encodeURIComponent(mandateId)}`);
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

  humanLedger(mandateId: string): Promise<{ mandate: MandateView; entries: LedgerEntry[] }> {
    return this.#request(`/ledger?view=human&mandate_id=${encodeURIComponent(mandateId)}`);
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

  offers(): Promise<{ offers: Array<Record<string, unknown>> }> {
    return this.#request('/merchant/offers');
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

  listDisputes(mandateId: string): Promise<{ disputes: Array<Record<string, unknown>> }> {
    return this.#request(`/disputes?mandate_id=${encodeURIComponent(mandateId)}`);
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

  // ---- the card ----------------------------------------------------------
  //
  // A mandate is born unfunded: it is authority to spend, and the means of paying is
  // the person's to provide. These three calls are how they provide it, and the number
  // is typed on the processor's page — never here. All three are holder-signed, because
  // attaching a card decides whose money the agent will spend.

  openInstrumentSession(
    mandateId: string,
    authorizationJws: string,
  ): Promise<{ session_id: string; url: string }> {
    return this.#request(`/mandates/${encodeURIComponent(mandateId)}/instrument/session`, {
      method: 'POST',
      body: { authorization_jws: authorizationJws },
    });
  }

  /** `ready: false` is the normal answer while the person is still on the form. */
  readInstrumentSession(
    mandateId: string,
    sessionId: string,
    authorizationJws: string,
  ): Promise<{ ready: boolean; token?: string; label?: string }> {
    return this.#request(
      `/mandates/${encodeURIComponent(mandateId)}/instrument/session/` +
        `${encodeURIComponent(sessionId)}?authorization_jws=${encodeURIComponent(authorizationJws)}`,
    );
  }

  bindInstrument(
    mandateId: string,
    token: string,
    label: string,
    authorizationJws: string,
  ): Promise<{ instrument_label: string; instrument_revocation_scope: string }> {
    return this.#request(`/mandates/${encodeURIComponent(mandateId)}/instrument`, {
      method: 'POST',
      body: { token, label, authorization_jws: authorizationJws },
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

  openDispute(reservationId: string, reason: string): Promise<{ dispute_id: string }> {
    return this.#request('/disputes', {
      method: 'POST',
      body: { reservation_id: reservationId, reason },
    });
  }

  resolveDispute(disputeId: string): Promise<Record<string, unknown>> {
    return this.#request(`/disputes/${encodeURIComponent(disputeId)}/resolution`, {
      method: 'POST',
    });
  }

  // ---- operator surfaces -------------------------------------------------

  setPspMode(mode: 'online' | 'offline' | 'decline'): Promise<{ mode: string }> {
    return this.#request('/admin/psp', { method: 'POST', body: { mode }, operator: true });
  }

  reconcile(): Promise<Record<string, number>> {
    return this.#request('/reconcile', { method: 'POST', operator: true });
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
