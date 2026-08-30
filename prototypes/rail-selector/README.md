# Deterministic rail selector prototype

Pure, non-integrated prototype for exploring how AVAL could choose a checkout
rail and an optional delegated-tokenization mode without touching payment
execution.

This directory is deliberately isolated from `src/aval`, the database, HTTP
routers, the web UI, E2E tests, blockchain, wallets, x402, and authorization.
It creates no key, PAN, token, credential, payment, or authorization decision.

## Decision model

The result uses separate axes because ACP delegated payment does not replace the
UCP/AP2 checkout rail:

- `checkout_rail`: `ucp_ap2` or `null`;
- `credential_mode`: `acp_delegate_payment` or `null`;
- `x402_status`: always `x402_disabled` in this prototype;
- `reason_code`: stable explanation for every selected, disabled, or rejected
  outcome.

x402 is hard-disabled even when caller-provided flags claim it is enabled or
that Task 12 is green. Enabling it requires a later group decision and a new
implementation after the real E2E gate is green.

The amount is parsed as a positive decimal and never used to authorize spending.
Unknown operations, rails, flags, malformed checkout context, floating-point
amounts, and sensitive input fail closed.

## Request

```json
{
  "operation_type": "delegate_payment",
  "mandate_allowed_rails": ["ucp_ap2", "acp_delegate_payment"],
  "amount": "49.90",
  "checkout_context": {
    "checkout_id": "checkout-demo",
    "merchant_id": "merchant-demo",
    "currency": "BRL",
    "ap2_version": "0.2"
  },
  "feature_flags": {
    "ucp_ap2_enabled": true,
    "acp_delegate_payment_enabled": true,
    "x402_enabled": false,
    "task_12_e2e_green": false
  }
}
```

## CLI

From this directory, pipe JSON through stdin:

```powershell
Get-Content -Raw request.json | python -m rail_selector
```

Or pass a request file:

```powershell
python -m rail_selector request.json
```

Selected outcomes exit with code `0`. Disabled and rejected outcomes emit JSON
and exit with code `2`; expected fail-closed results do not print tracebacks.

## Tests

From this directory:

```powershell
python -m pytest -q
```

This local pytest configuration is intentional: the repository-level config
only discovers `tests/`, and this prototype must not change it.

## Non-integration disclaimer

This is an executable design probe, not production routing logic. It must not be
merged into AVAL runtime code or presented as payment, authorization, x402, ACP,
UCP, AP2, or blockchain integration without a separate group decision.
