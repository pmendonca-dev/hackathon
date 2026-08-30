# Browser-Safe BFF Authentication Design

**Status:** Approved for planning; implementation has not started.

## Goal

Make the human, merchant, auditor, and operator browser views live and authenticated without placing an RFC 9421 signing key, AP2 credential, payment token, or authorization proof in browser code, storage, logs, or rendered output.

## Decision

AVAL will use a same-origin backend-for-frontend (BFF) surface for browser views. The existing agent-facing UCP, ACP, capture, receipt, audit, and revocation HTTP contracts remain RFC 9421 boundaries. Browser calls do not emulate those agents and do not bypass their verification; they use separate UI routes that authenticate a server-side session and invoke the same application services and `AuthorizationCore` directly.

## Scope

In scope:

- Browser read projections for merchant, holder, and auditor roles.
- Browser operator revocation as an authenticated, audited command.
- Server-side sessions, CSRF protection, role authorization, redaction, and local-demo authentication.
- Production-bundle exclusion of fixtures and all sensitive runtime values.

Out of scope:

- Browser RFC 9421 signing, browser-held private keys, WebCrypto key registration, external IdP/OAuth, smart contracts, Web3, x402, real PSPs, and changes to agent API semantics.

## Architecture

```text
Browser
  -- HttpOnly session cookie + CSRF token --> /ui-api/v1/*
  -- no keys, JWS, proof, PAN, or vault token -->

Same-origin BFF
  -- role and CSRF checks --> application services / AuthorizationCore
  -- KeyCustodyService only for the authenticated operator's signed revocation -->

Existing agent APIs
  -- RFC 9421 + Content-Digest --> UCP / ACP / capture / audit / revocation
```

The BFF is an adapter, not a policy authority. It never writes a parallel mandate, allowance, checkout, reservation, or audit state. It selects only a role-scoped projection or submits a role-scoped command to the existing application services.

## Session and local-demo authentication

Sessions are opaque, random, server-side records with role, issued-at, expiry, and revocation state. The browser receives only an `HttpOnly`, `SameSite=Strict` cookie; `Secure` is required outside an explicitly documented local HTTP demo mode. Each state-changing UI request also supplies a per-session CSRF token. Session cookies and CSRF tokens must never be logged.

The demo login secret is supplied explicitly by environment configuration and is never minted into stdout or returned by an endpoint. A successful local login selects only the role the configured credential permits. The design intentionally does not claim production identity-provider support.

## UI routes

The implementation will use a distinct `/ui-api/v1/` namespace. It will not weaken or reclassify any existing RFC 9421 endpoint.

- `POST /ui-api/v1/session/login`: establishes a role-scoped session after local-demo credential verification.
- `POST /ui-api/v1/session/logout`: invalidates the server session and clears the cookie.
- `GET /ui-api/v1/workspace`: returns only the caller's safe role projection.
- `GET /ui-api/v1/mandates/{mandate_id}/audit`: returns the authorized role projection of the append-only timeline.
- `GET /ui-api/v1/mandates/{mandate_id}/dispute`: returns the authorized role projection of the dispute result.
- `POST /ui-api/v1/mandates/{mandate_id}/revocations`: requires an operator session and CSRF token; the server signs the canonical revocation request with the registered operator key in `KeyCustodyService` and records the actor and audit evidence.

The exact DTOs must reuse existing safe serializers. Merchant responses must not contain another merchant's facts, PAN, vault tokens, proofs, raw AP2 credentials, JWS values, private budgets, or internal key identifiers.

## Error and logging rules

All UI API errors use the existing stable error envelope. An unauthenticated browser session returns `401 ui_session_required`; an unauthorized role returns `403 ui_role_not_authorized`; CSRF failure returns `403 csrf_invalid`. Browser-facing errors are sanitized before rendering.

The server must not write tokens, credentials, JWS, AuthorizationProof values, cookie identifiers, or CSRF tokens to stdout, application logs, error messages, audit summaries, or receipt data.

## Security properties to prove

- The production web artifact contains no mock fixture module, synthetic `vt_`/`proof_` fixture values, signing code, private material, or AP2 credential.
- Browser storage and console contain no runtime secret, token, proof, or JWS.
- Browser calls to `/ui-api/v1/` work only with a valid session and, for writes, a valid CSRF token.
- Direct agent endpoints still reject unsigned browser requests with RFC 9421 errors.
- An operator UI revocation is server-signed, idempotent, role-authorized, and visible in the audit timeline.
- BFF calls preserve `AuthorizationCore` as the only state and authorization authority.

## Delivery and migration

This is a new authentication subsystem and requires a forward Alembic migration for server-side sessions. It must be implemented on a dedicated branch after the current A/B runtime branches are integrated or rebased onto the same `main` commit. Task 12 is green only after automated E2E and browser inspection cover this BFF boundary in addition to the existing agent API tests.
