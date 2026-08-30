import type {
  CheckoutSessionProjection,
  CompleteCheckoutSessionRequest,
  CreateCheckoutSessionRequest,
} from '../contracts/checkoutApi.ts';
import type {
  AvalGateway,
  AvalSnapshot,
  TrialCommand,
  TrialCommandReceipt,
} from '../contracts/avalGateway.ts';
import type {
  AuditVerdictProjection,
  CreateRevocationRequest,
  CreatePaymentCaptureRequest,
  DelegatePaymentRequest,
  DelegatePaymentResponse,
  PaymentCaptureProjection,
  PaymentReceiptsProjection,
  RevocationProjection,
} from '../contracts/paymentRuntimeApi.ts';
import { PAYMENT_RUNTIME_API_CONTRACT_VERSION } from '../contracts/paymentRuntimeApi.ts';

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export class AvalHttpError extends Error {
  readonly status: number;
  readonly code: string;

  constructor(status: number, code: string) {
    super(`AVAL request failed with HTTP ${status} (${code}).`);
    this.name = 'AvalHttpError';
    this.status = status;
    this.code = code;
  }
}

export class AvalRuntimeUnavailableError extends Error {
  constructor(readonlyFeature: 'workspace' | 'trial-command') {
    super(
      readonlyFeature === 'workspace'
        ? 'A API de projeções do runtime ainda não está disponível.'
        : 'A API administrativa de trial-by-fire ainda não está disponível.',
    );
    this.name = 'AvalRuntimeUnavailableError';
  }
}

export interface HttpAvalGatewayOptions {
  baseUrl: string;
  mandateId?: string;
  captureId?: string;
  createIdempotencyKey?: () => string;
  fetch?: FetchLike;
}

export class HttpAvalGateway implements AvalGateway {
  readonly #baseUrl: string;
  readonly #mandateId?: string;
  readonly #captureId?: string;
  readonly #createIdempotencyKey: () => string;
  readonly #fetch: FetchLike;

  constructor({
    baseUrl,
    mandateId,
    captureId,
    createIdempotencyKey = () => globalThis.crypto.randomUUID(),
    fetch: fetchImplementation = globalThis.fetch,
  }: HttpAvalGatewayOptions) {
    this.#baseUrl = baseUrl.replace(/\/+$/, '');
    this.#mandateId = mandateId;
    this.#captureId = captureId;
    this.#createIdempotencyKey = createIdempotencyKey;
    this.#fetch = fetchImplementation.bind(globalThis);
  }

  async #readJson<T>(response: Response): Promise<T> {
    const payload = (await response.json()) as unknown;
    if (!response.ok) {
      const code =
        typeof payload === 'object'
        && payload !== null
        && 'detail' in payload
        && typeof payload.detail === 'object'
        && payload.detail !== null
        && 'code' in payload.detail
        && typeof payload.detail.code === 'string'
          ? payload.detail.code
          : 'http_error';
      throw new AvalHttpError(response.status, code);
    }
    return payload as T;
  }

  async loadWorkspace(): Promise<AvalSnapshot> {
    if (!this.#mandateId) {
      throw new AvalRuntimeUnavailableError('workspace');
    }

    const capturePromise = this.#captureId
      ? this.getPaymentCapture(this.#captureId)
      : Promise.resolve(null);
    const receiptsPromise = this.#captureId
      ? this.getPaymentReceipts(this.#captureId).catch((error: unknown) => {
          if (error instanceof AvalHttpError && error.code === 'receipts_not_available') {
            return null;
          }
          throw error;
        })
      : Promise.resolve(null);
    const [capture, receipts, audit, dispute] = await Promise.all([
      capturePromise,
      receiptsPromise,
      this.getAuditTimeline(this.#mandateId),
      this.getDispute(this.#mandateId),
    ]);

    return {
      meta: {
        dataSource: 'api',
        contractStatus: 'integrated',
        contractVersion: PAYMENT_RUNTIME_API_CONTRACT_VERSION,
        generatedAt: new Date().toISOString(),
        networkUsed: true,
      },
      live: {
        mandateId: this.#mandateId,
        captureId: this.#captureId ?? null,
        capture,
        receipts,
        audit,
        dispute,
      },
    };
  }

  async submitTrialCommand(command: TrialCommand): Promise<TrialCommandReceipt> {
    if (command.kind !== 'revoke-mandate') {
      throw new Error(`O comando ${command.kind} não está publicado na API administrativa.`);
    }
    if (!command.requestedValue.trim()) {
      throw new Error('A revogação assinada é obrigatória.');
    }

    const requestId = this.#createIdempotencyKey();
    const result = await this.revokeMandate(
      command.targetId,
      command.requestedValue,
      requestId,
    );
    return {
      requestId,
      dataSource: 'api',
      outcome: 'accepted',
      canonicalStateChanged: true,
      effectiveAt: null,
      message: `O runtime aceitou a revogação do mandato ${result.mandate_id}.`,
    };
  }

  async delegatePayment(
    request: DelegatePaymentRequest,
    idempotencyKey: string,
  ): Promise<DelegatePaymentResponse> {
    const response = await this.#fetch(`${this.#baseUrl}/agentic_commerce/delegate_payment`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'content-type': 'application/json',
        'idempotency-key': idempotencyKey,
      },
      body: JSON.stringify(request),
    });
    return this.#readJson<DelegatePaymentResponse>(response);
  }

  async createPaymentCapture(
    request: CreatePaymentCaptureRequest,
    idempotencyKey: string,
  ): Promise<PaymentCaptureProjection> {
    const response = await this.#fetch(`${this.#baseUrl}/payment-captures`, {
      method: 'POST',
      credentials: 'include',
      headers: {
        'content-type': 'application/json',
        'idempotency-key': idempotencyKey,
      },
      body: JSON.stringify(request),
    });
    return this.#readJson<PaymentCaptureProjection>(response);
  }

  async getPaymentCapture(captureId: string): Promise<PaymentCaptureProjection> {
    const response = await this.#fetch(
      `${this.#baseUrl}/payment-captures/${encodeURIComponent(captureId)}`,
      { method: 'GET', credentials: 'include' },
    );
    return this.#readJson<PaymentCaptureProjection>(response);
  }

  async getPaymentReceipts(captureId: string): Promise<PaymentReceiptsProjection> {
    const response = await this.#fetch(
      `${this.#baseUrl}/payment-captures/${encodeURIComponent(captureId)}/receipts`,
      { method: 'GET', credentials: 'include' },
    );
    return this.#readJson<PaymentReceiptsProjection>(response);
  }

  async getAuditTimeline(mandateId: string): Promise<AuditVerdictProjection> {
    const response = await this.#fetch(
      `${this.#baseUrl}/audit/mandates/${encodeURIComponent(mandateId)}`,
      { method: 'GET', credentials: 'include' },
    );
    return this.#readJson<AuditVerdictProjection>(response);
  }

  async getDispute(mandateId: string): Promise<AuditVerdictProjection> {
    const response = await this.#fetch(
      `${this.#baseUrl}/audit/mandates/${encodeURIComponent(mandateId)}/dispute`,
      { method: 'GET', credentials: 'include' },
    );
    return this.#readJson<AuditVerdictProjection>(response);
  }

  async revokeMandate(
    mandateId: string,
    signedRevocation: string,
    idempotencyKey: string,
  ): Promise<RevocationProjection> {
    const request: CreateRevocationRequest = { signed_revocation: signedRevocation };
    const response = await this.#fetch(
      `${this.#baseUrl}/mandates/${encodeURIComponent(mandateId)}/revocations`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          'content-type': 'application/json',
          'idempotency-key': idempotencyKey,
        },
        body: JSON.stringify(request),
      },
    );
    return this.#readJson<RevocationProjection>(response);
  }

  async createCheckout(
    request: CreateCheckoutSessionRequest,
  ): Promise<CheckoutSessionProjection> {
    const response = await this.#fetch(`${this.#baseUrl}/checkout-sessions`, {
      method: 'POST',
      credentials: 'include',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
    });

    return this.#readJson<CheckoutSessionProjection>(response);
  }

  async completeCheckout(
    checkoutId: string,
    request: CompleteCheckoutSessionRequest,
    idempotencyKey: string,
  ): Promise<CheckoutSessionProjection> {
    const response = await this.#fetch(
      `${this.#baseUrl}/checkout-sessions/${encodeURIComponent(checkoutId)}/complete`,
      {
        method: 'POST',
        credentials: 'include',
        headers: {
          'content-type': 'application/json',
          'idempotency-key': idempotencyKey,
        },
        body: JSON.stringify(request),
      },
    );

    return this.#readJson<CheckoutSessionProjection>(response);
  }
}
