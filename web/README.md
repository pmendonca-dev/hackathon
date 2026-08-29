# Yuno — Authorization Layer (visual prototype)

Navigable visual prototype of the authorization layer for agent-initiated payments,
built against the v4.0 briefing and `docs/aval-integration-architecture.md`.

**All data is mocked. There is no backend, no database, and no payment integration.**
Every state transition runs in a single client-side reducer.

```bash
cd web
npm install
npm run dev      # http://localhost:5173
```

## The argument the interface makes

> An agent may act on behalf of a human, but it can never exceed the authority it was granted.

The product is drawn as `MANDATE → POLICY → AUTHORIZATION → PAYMENT → EVIDENCE`, and under
attack as `ATTACK → VERIFICATION → DENY / SAFE STATE → LEDGER EVIDENCE`.

## Design system

Colour is semantic, never decorative. One colour, one meaning, on every screen:

| Token | Hex | Means |
|---|---|---|
| `allow` | `#C6F24E` | authority granted |
| `escalate` | `#F5B942` | human decision required |
| `deny` | `#FF5C5C` | refused by policy |
| `verify` | `#4ED8F2` | cryptographic verification — nothing else |
| `hold` | `#8B93FF` | indeterminate / in doubt |

Type splits machine truth from human narration: every amount, state, reason code, hash
and ID is set in JetBrains Mono; all prose is Inter. Headings are Inter Tight.

The signature element is the **Authority Rail** (`components/AuthorityRail.tsx`) — the
ALLOW / ESCALATE / DENY bands drawn to scale with a live marker at the transaction
amount. It reappears on the overview, the mandate, and every decision, so one picture
answers "was this allowed?" everywhere.

## Screens

| Route | What it shows |
|---|---|
| `#/overview` | Metrics, the seven-stage pipeline, authority drawn to scale |
| `#/mandates` | Mandate list, policy bands, live revocation, irreversible revoke |
| `#/payments` | Payment table plus the PSP outage → reconciliation simulation |
| `#/agent` | Agent attempts and the ALLOW / ESCALATE / DENY decision panel |
| `#/merchant` | The selective receipt, and what is deliberately withheld from it |
| `#/ledger` | Append-only event stream with integrity indicator |
| `#/disputes` | Verdicts reconstructed from the evidence chain |
| `#/judge` | Attack grid, scenario controller, live metrics footer |

## Driving the demo

`#/judge` has seven scenario buttons that put the whole product into a state in one
click: happy path, escalation, revocation, PSP failure, fake webhook, replay attack,
reservation griefing. The eight attack tests each report the reason code the layer
answers with. The reset control in the top bar restores all mock state.

## Behaviours worth pointing at

- **Revocation is monotonic.** Once revoked, a mandate cannot be restored, and every
  attempt still in flight against it loses its authority.
- **A timeout is not a decline.** A PSP failure moves a payment to `IN_CONFIRMATION`,
  keeps the budget reserved and delivery blocked, and reconciles when the processor
  returns. Nothing is ever released early or reported as a refusal.
- **A ceiling is not negotiable.** The DENY surface has no approval control, because
  the human cannot approve past the ceiling either.
- **The merchant receipt is selective.** Monthly budget, accumulated spend,
  `principal_id` and `mandate_id` are absent from the merchant payload by design, and
  the interface shows their absence rather than quietly omitting them.
- **`Unauthorized spend` is derived, never asserted.** It reads `$0.00` because the
  state contains no such spend, not because the string is hardcoded.

## Stack

React 19 · TypeScript · Tailwind CSS v4 · Lucide · Vite. No component library,
no router, no state library — a hash router and one reducer in `src/domain/store.tsx`.

```
src/
  domain/     types · policy engine · mock data · store
  components/ AuthorityRail · FlowSpine · Verification · Shell · ui primitives
  pages/      one file per screen
```

The policy engine in `domain/policy.ts` is the whole product in fifteen lines: authority
is checked before money, and money before scope, which is why a revoked mandate can
never be out-argued by a small enough purchase.
