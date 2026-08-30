import type {
  UiAuditProjection,
  UiBffGatewayContract,
  UiDisputeProjection,
  UiLoginRequest,
  UiRevocationProjection,
  UiRole,
  UiSessionMaterial,
  UiWorkspaceProjection,
} from '../contracts/avalGateway.ts';
import { parseAvalErrorEnvelope, presentAvalError } from '../errors/avalError.ts';

interface UiLoginResponse {
  role: UiRole;
  csrf_token: string;
  expires_at: string;
}

type FetchLike = (input: string, init?: RequestInit) => Promise<Response>;

export interface UiBffGatewayOptions {
  fetch?: FetchLike;
}

export class UiBffHttpError extends Error {
  readonly status: number;
  readonly code: string;
  readonly presentation;

  constructor(status: number, code: string) {
    const presentation = presentAvalError({ status, code });
    super(presentation.message);
    this.name = 'UiBffHttpError';
    this.status = status;
    this.code = code;
    this.presentation = presentation;
  }
}

export class UiBffGateway implements UiBffGatewayContract {
  readonly #fetch: FetchLike;

  constructor({ fetch: fetchImplementation = globalThis.fetch }: UiBffGatewayOptions = {}) {
    this.#fetch = fetchImplementation.bind(globalThis);
  }

  async #readJson<T>(response: Response): Promise<T> {
    let payload: unknown = null;
    try {
      payload = await response.json() as unknown;
    } catch {
      // BFF error bodies are untrusted and never reach the UI verbatim.
    }
    if (!response.ok) {
      throw new UiBffHttpError(response.status, parseAvalErrorEnvelope(payload));
    }
    return payload as T;
  }

  async login(request: UiLoginRequest): Promise<UiSessionMaterial> {
    const response = await this.#fetch('/ui-api/v1/session/login', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify(request),
    });
    const payload = await this.#readJson<UiLoginResponse>(response);
    return {
      role: payload.role,
      csrfToken: payload.csrf_token,
      expiresAt: payload.expires_at,
    };
  }

  async logout(csrfToken: string): Promise<void> {
    const response = await this.#fetch('/ui-api/v1/session/logout', {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'X-AVAL-CSRF': csrfToken },
    });
    if (!response.ok) {
      await this.#readJson<never>(response);
    }
  }

  async loadWorkspace(): Promise<UiWorkspaceProjection> {
    const response = await this.#fetch('/ui-api/v1/workspace', {
      method: 'GET',
      credentials: 'same-origin',
    });
    return this.#readJson<UiWorkspaceProjection>(response);
  }

  async loadAudit(mandateId: string): Promise<UiAuditProjection> {
    const response = await this.#fetch(
      `/ui-api/v1/mandates/${encodeURIComponent(mandateId)}/audit`,
      { method: 'GET', credentials: 'same-origin' },
    );
    return this.#readJson<UiAuditProjection>(response);
  }

  async loadDispute(mandateId: string): Promise<UiDisputeProjection> {
    const response = await this.#fetch(
      `/ui-api/v1/mandates/${encodeURIComponent(mandateId)}/dispute`,
      { method: 'GET', credentials: 'same-origin' },
    );
    return this.#readJson<UiDisputeProjection>(response);
  }

  async revokeMandate(
    mandateId: string,
    idempotencyKey: string,
    csrfToken: string,
  ): Promise<UiRevocationProjection> {
    const response = await this.#fetch(
      `/ui-api/v1/mandates/${encodeURIComponent(mandateId)}/revocations`,
      {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'content-type': 'application/json',
          'Idempotency-Key': idempotencyKey,
          'X-AVAL-CSRF': csrfToken,
        },
        body: '{}',
      },
    );
    return this.#readJson<UiRevocationProjection>(response);
  }
}
