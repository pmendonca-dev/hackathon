# Runtime Error Resilience Plan

## Problem

The live browser currently reduces every failure to `Error.message`, always
offers the same retry action, and lets individual views decide how much of a
runtime payload to display. That is unsafe for payment failures: a revocation
storage outage must never look like a reason to resubmit a payment, a conflict
must preserve the original operation, and validation errors must not echo
credentials or request fields.

## Public seams under test

- `parseAvalErrorEnvelope(payload)` is the only parser for the documented
  `{"detail":{"code":"stable_code"}}` envelope.
- `presentAvalError(error)` is the safe, Portuguese UI projection for status,
  title, explanation, recovery guidance, tone, and allowed follow-up action.
- `AvalGateway.loadWorkspace()` and its thrown `AvalHttpError` remain the
  browser's external API seam.
- Role views are verified at their presentation boundary: merchant receives
  only capture/receipt-safe facts; holder and auditor render their authorized
  projections; no view renders PAN, vault tokens, JWS credentials, or proofs.
- Gateway selection remains HTTP in production. Fixture state is observable
  only with `DEV === true` and `VITE_AVAL_USE_MOCK === "true"`.

## Approach

Work in vertical red-green slices:

1. Specify and implement the single error-envelope parser and the required
   Portuguese message catalog.
2. Route `HttpAvalGateway` failures through that parser without retaining or
   interpolating response fields.
3. Project safe error state through `AvalProvider` and render a role-neutral
   operational failure rail with explicit 503, 409, 422, loading, and read-only
   recovery behavior.
4. Remove presentation-layer bindings to token/proof fields, stop rendering
   receipt JWS fragments, and sanitize API-authored explanatory text.
5. Prove development-only mock selection and production fail-visible behavior.

## Rejected approaches

- Echo the backend response body for diagnostics: it could expose PAN, tokens,
  AP2 credentials, or proofs.
- Automatically retry a failed payment: a 503 is a fail-closed decision, and a
  409 means the original operation must be observed rather than duplicated.
- Put role-specific policy in the browser: role projections remain server
  authored; the UI only limits what it renders.
- Add a second error parser in the provider or views: it would drift from the
  transport boundary.

## Visual system

- Color: existing graphite `#08090B`, panel `#101317`, safe authority
  `#C6F24E`, rejection `#FF5C5C`, verification `#4ED8F2`, and pending
  `#8B93FF`.
- Type: Inter Tight for headings, Inter for guidance, JetBrains Mono only for
  stable machine codes and safe identifiers.
- Layout: retain the role shell; place one compact operational rail above the
  current projection when stale data remains, or center it when no canonical
  projection loaded.
- Signature: the rail names the safety behavior first — "bloqueio seguro",
  "operação preservada", or "solicitação rejeitada" — and then gives exactly
  one safe next action.

```text
┌ status rail ──────────────────────────────────────────────────┐
│ BLOQUEIO SEGURO   Revogação indisponível                     │
│ Nenhum pagamento foi iniciado. Não repita automaticamente.   │
│ Próximo passo: verificar disponibilidade (read-only)          │
└───────────────────────────────────────────────────────────────┘
┌ canonical role projection, if one was already loaded ─────────┐
└────────────────────────────────────────────────────────────────┘
```

## Verification

From `web/`:

1. `npm test`
2. `npm run build`
3. `npm run lint`

No backend, migration, runtime contract, or Task 12 E2E file is modified.

## Outcome

- The transport accepts only the stable error code and discards every other
  error-body field, including malformed non-JSON bodies.
- One structured failure rail distinguishes safe block, preserved operation,
  rejected request, and read-only unavailability recovery.
- Role pages redact untrusted explanatory text and no longer bind vault token,
  payment token, JWS receipt, or authorization proof values to the DOM.
- Signed trial evidence is masked, never logged, and cleared after submission.
- The mock remains explicit development-only behavior; an absent live
  configuration fails visibly instead of loading fixture state.

## Production bundle hardening amendment — 2026-08-30

The public seam for this correction is the emitted production artifact, not a
source-code grep. A build-level regression must run a real Vite production
build into an isolated output directory and inspect every emitted JavaScript
asset for the mock module marker and synthetic `vt_`/`proof_` values.

The gateway factory will become asynchronous only at application bootstrap so
the explicit development path can use a dynamic import. Production and every
configuration other than `DEV === true` plus
`VITE_AVAL_USE_MOCK === "true"` must instantiate the HTTP gateway without
loading the fixture chunk. Missing runtime configuration continues to produce
the existing visible unavailable state. This amendment does not add browser
authentication, a proxy, signing code, or key material.
