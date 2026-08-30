# Decision Log — 202 Alpha

NextWave Hackathon 2026 · São Paulo

Every decision recorded during the project, in the order it was made — 53 in
all. Two shorter cuts live in the repository: the 23 we expect to be asked to
defend, grouped by the invariants of the challenge, in
[`docs/decision-log.md`](https://github.com/pmendonca-dev/hackathon/blob/main/docs/decision-log.md), and the twelve that fit on
one screen in [`docs/decision-log-short.md`](https://github.com/pmendonca-dev/hackathon/blob/main/docs/decision-log-short.md).

Each entry records the decision, the alternatives that were real at the time, what
we chose, and why.

## Browser visual-system restoration

**Decision:** Restore the approved blue/lilac palette and desktop-collapsible
sidebar without changing the current header's information hierarchy.

**Options considered (one per line):**

Keep the translated paper/teal presentation
Restore the previous shell wholesale, including its older header
Restore the palette and sidebar interaction while keeping the current header

**What we chose:** Restore the indigo visual tokens, divider treatment, and
collapsible desktop navigation. The current header continues to show runtime
context on the left and Reload on the right.

**Why:** The earlier visual affordances were lost during the English frontend
integration, while the newer header arrangement is the preferred operational
layout. Preserving that arrangement avoids regressing the current workflow.

## Browser BFF session migration identity

**Decision:** Alembic revision number for durable browser sessions

**Options considered (one per line):**

Reuse the plan's historical `0006_browser_ui_sessions` identifier
Relabel the published browser-session revision after `0010_mandate_instrument`
Keep the published browser-session revision and join it with an Alembic merge revision

**What we chose:** Preserve `0009_browser_ui_sessions` and add
`0011_merge_browser_ui_sessions` with both it and `0010_mandate_instrument` as
parents.

**Why:** Revisions through `0010_mandate_instrument` are already published runtime
history on `main`, while databases initialized by the BFF branch already carry the
browser-session revision identity. Relabeling it would orphan those databases and
leaving the branch unmerged would make `alembic upgrade head` ambiguous. The merge
revision creates one upgrade head while preserving both durable histories.

## Browser projection scope for multi-merchant mandates

**Decision:** Merchant access to a mandate whose shared timeline cannot be partitioned safely

**Options considered (one per line):**

Return the complete mandate timeline to every merchant named by the mandate
Filter the current timeline heuristically by merchant fields
Deny merchant audit and dispute reads unless the mandate has exactly that merchant scope

**What we chose:** Deny merchant audit and dispute reads for multi-merchant
mandates; merchant reads are allowed only when the mandate scope is exactly the
merchant session's configured merchant.

**Why:** Current durable audit and dispute reconstruction contains mandate-level
facts and cannot prove that every event is attributable to one merchant. A
heuristic filter could disclose another merchant's checkout or settlement
facts, so the BFF fails closed until a future evidence model provides an
authoritative merchant partition.

## Browser workspace mandate source

**Decision:** Scope of the Core mandate read used by browser workspace projections

**Options considered (one per line):**

Keep the Core limited to principal-scoped mandate reads and omit auditor and operator workspaces
Expose a transport-level all-mandates endpoint for the browser
Provide an internal Core read that the already-authenticated BFF filters into role-scoped projections

**What we chose:** Provide the internal Core read and keep all role checks and redaction in the BFF projection service.

**Why:** The published BFF contract grants auditors a redacted cross-merchant summary and operators mandate status, while merchant and holder projections remain narrower. The new read is not an HTTP surface and does not bypass the BFF session and role checks; exposing it through the agent APIs would weaken their RFC 9421 boundary.

## Browser operator revocation idempotency binding

**Decision:** Idempotency fingerprint for a server-signed browser revocation

**Options considered (one per line):**

Use the fresh ES256 JWS bytes as the idempotency request hash
Persist browser-side JWS material to replay the original signature
Bind the BFF's separate idempotency scope to the canonical mandate action

**What we chose:** Use a dedicated Core idempotency scope and a canonical hash
of the mandate identifier plus the fixed operator-revocation action.

**Why:** ES256 signing produces a new signature for the same semantic command,
so hashing JWS bytes would turn a same-key browser retry into a mismatch.
Persisting the raw JWS in a browser session would unnecessarily retain signing
material. A distinct canonical action hash preserves the durable replay
contract without exposing or depending on the JWS.

## Local operator authority key continuity

**Decision:** Key lifetime for the local server-side browser revocation authority

**Options considered (one per line):**

Generate a new in-memory ES256 operator key on every runtime start
Persist an unencrypted private key in the local SQLite database
Derive the server authority deterministically from an explicit server-only environment seed

**What we chose:** Derive the local demo operator authority deterministically
inside `KeyCustodyService` from `AVAL_OPERATOR_AUTHORITY_SEED` and do not
persist private key material in SQLite.

**Why:** The mandate records the authority's public JWK. A newly generated key
after restart cannot validate against that durable registration, which made the
operator BFF return `revocation_invalid`. An explicit server-only seed produces
the same public identity on each start while keeping the private key material
inside KeyCustody and out of the database, browser, API responses, logs,
exceptions, receipts, and audit summaries. Without that seed (or injected
custody) the operator authority is disabled and the BFF fails closed.

## Existing-mandate operator authority adoption

**Decision:** Applying an explicit operator authority seed to an existing local runtime database

**Options considered (one per line):**

Leave pre-BFF and rotated-seed mandate authority registrations unchanged
Rewrite the entire seeded mandate whenever the configured operator key changes
Upsert only the named operator revocation authority through AuthorizationCore and append an audit event

**What we chose:** Upsert only `authority_operator_01` through
`AuthorizationCore` when an explicit server authority seed is configured,
recording `operator_authority.configured` in the append-only ledger.

**Why:** An existing mandate otherwise retains no operator authority or a JWK
from an old seed, which makes its configured server operator unavailable. A
full mandate rewrite could alter revocation, expiry, limits, or settlements.
The narrow Core-owned authority update adopts or rotates only the explicitly
configured server authority while preserving all existing authorization facts.

## Technical coverage objective

**Decision:** Primary product objective for the hackathon solution

**Options considered (one per line):**
Prioritize a distinctive business proposition
Prioritize the strongest technical capability with broad, efficient case coverage

**What we chose:** Prioritize building the tool with the strongest technical capability, designed to handle the largest practical set of cases efficiently, without business differentiation as the objective.

**Why:** The team selected technical breadth, robustness, and efficient handling of varied scenarios as the success criteria for the project. Business differentiation will not drive product decisions within this scope.

## Runtime and persistence foundation

**Decision:** Runtime and persistence foundation for the AVAL demonstration

**Options considered (one per line):**

Use the locally available Python 3.13 runtime with FastAPI, SQLAlchemy, Alembic, and SQLite WAL
Adopt an AP2 reference application or SDK as the application foundation
Introduce a separate service or frontend stack before the authorization core exists

**What we chose:** Use Python 3.13 with FastAPI, SQLAlchemy, Alembic, and SQLite WAL, with AVAL-owned domain and persistence code.

**Why:** The historical AP2 review identified Python as the compatible ecosystem while explicitly excluding its sample applications. SQLite WAL with `BEGIN IMMEDIATE` and a single writer is the documented demo boundary; it keeps durable authorization state local and leaves repositories isolatable for a later Postgres migration.

## Live authorization outcomes

**Decision:** Outcome for checkout policy violations before the capture commit point

**Options considered (one per line):**

Reject every policy violation immediately
Escalate recoverable scope and budget violations to a human while rejecting expired or revoked mandates
Allow protocol adapters to decide the outcome independently

**What we chose:** Escalate merchant-scope and budget violations to human approval, and reject missing, expired, or revoked mandates deterministically.

**Why:** This preserves the UCP `requires_escalation` path for consent that can be renewed while never silently authorizing a mandate that has lost validity or been revoked.

## Authorization state persistence boundary

**Decision:** Persistence ownership for live authorization state

**Options considered (one per line):**

Keep authorization state in process memory
Let protocol adapters maintain separate persistent state
Persist core state through SQLite repositories owned and orchestrated exclusively by AuthorizationCore

**What we chose:** Persist mandates, live policy, and signed revocations in isolated SQLite repositories that are invoked only by AuthorizationCore.

**Why:** A process-local store loses live authority after restart, while adapter-owned state would create competing policy and revocation sources. The repository boundary keeps SQLite replaceable without allowing an adapter to become an alternate writer.

## Capture commit and retry boundary

**Decision:** Transaction boundary for capture, revocation, and retries

**Options considered (one per line):**

Commit a mandate when a capture starts
Call settlement before recording a committed reservation
Atomically commit a reservation in the core before settlement, with durable idempotency

**What we chose:** Under the SQLite immediate-write transaction, the core checks fresh revocation, claims idempotency, commits a reservation, and persists its capture attempt before calling settlement outside the lock.

**Why:** This gives revocation and capture one serial decision boundary, prevents an adapter from receiving an uncommitted reservation, retains a recoverable pending attempt during external I/O, and makes retries deterministic across process restarts.

## Incremental authorization-schema evolution

**Decision:** Alembic strategy for authorization-core schema hardening

**Options considered (one per line):**

Keep `0001_initial_core` coupled to current SQLAlchemy metadata
Reset migrated demo databases when the schema changes
Freeze the historical initial schema and apply a forward-only incremental migration

**What we chose:** Preserve `0001_initial_core` as the original schema and add `0002_authorization_hardening` for persisted mandate fields and uniqueness constraints.

**Why:** A metadata-driven initial migration silently leaves an existing database stamped at `0001` without subsequent columns or constraints. An explicit forward migration upgrades both clean and already-migrated databases without treating a reset as a correctness mechanism.

## Authorization-proof replay storage

**Decision:** Storage boundary for one-use AuthorizationProof JTIs

**Options considered (one per line):**

Keep consumed JTIs in each process memory
Create a separate replay datastore for authorization proofs
Consume proof JTIs atomically in the shared durable idempotency store

**What we chose:** Store and atomically consume each AuthorizationProof JTI in the existing durable idempotency store under its own scope.

**Why:** Replay must remain blocked across new AuthorizationCore instances and process restarts. Reusing the transactionally protected idempotency store keeps one anti-replay authority instead of introducing a second, independently failing state source.

## Parallel implementation ownership

**Decision:** Work partition across two independent implementation laptops

**Options considered (one per line):**

Split work by arbitrary features across both laptops
Give both laptops access to all files and resolve conflicts later
Assign disjoint protocol/core and payments/UI ownership boundaries with a committed handoff contract

**What we chose:** Laptop A owns UCP/AP2 protocol and checkout work, while Laptop B owns ACP, settlement/receipts/audit and web work; shared files change only through an explicit handoff commit.

**Why:** The partition minimizes simultaneous edits to the same persistence and application files while allowing ACP, PSP, audit, and UI work to proceed independently of UCP checkout implementation. A committed API contract gives the UI a stable integration target without creating a second business authority.

## Durable retry retention

**Decision:** Retention boundary for durable idempotency records

**Options considered (one per line):**

Keep completed retries indefinitely
Delete retries opportunistically without a persisted deadline
Persist a retention deadline of at least 24 hours and clean up only after it expires

**What we chose:** Persist `retained_until` for every idempotency record with a minimum 24-hour retention period.

**Why:** A durable deadline preserves deterministic replay through process restarts while making deletion explicit and auditable instead of relying on memory or implicit database cleanup.

## Shared mandate serialization

**Decision:** Serialization boundary for capture and signed revocation

**Options considered (one per line):**

Rely only on SQLite's database-wide writer lock
Use separate capture and revocation synchronization paths
Persist and acquire one lock record per mandate inside the shared write transaction

**What we chose:** Use one durable `mandate_locks` record per mandate, acquired by both capture and signed revocation in their `BEGIN IMMEDIATE` transactions.

**Why:** The explicit shared resource documents and enforces the commit race boundary independently of the current SQLite implementation, so a revocation and a capture cannot make conflicting pre-commit decisions.

## Payment runtime authority boundary

**Decision:** Authority and composition boundary for ACP delegation and card settlement

**Options considered (one per line):**

Let ACP allowance and vault state become a second payment-policy source
Create a parallel demo capture flow outside the AuthorizationCore
Compose ACP, capture, PSP, receipts, and audit around live AuthorizationCore decisions

**What we chose:** Compose the runtime around AuthorizationCore as the exclusive authority; ACP projects a fresh allowance, and capture commits a Core reservation before the PSP receives a single-use proof.

**Why:** This preserves live revocation, canonical checkout scope, budget enforcement, durable retry behavior, and the post-commit settlement boundary without copying policy into adapters or allowing protocol-specific state to authorize a purchase.

## Settlement evidence persistence

**Decision:** When AP2 receipts become durable runtime facts

**Options considered (one per line):**

Issue receipts when a payment token is delegated
Issue receipts when the Core reservation is committed
Issue and persist receipts only after the mock PSP approves settlement

**What we chose:** Issue checkout and payment receipts only after approved settlement, then persist them under the settled reservation identifier.

**Why:** A committed reservation can still be released when settlement declines. Tying immutable receipt issuance to the approved settlement result prevents the audit trail from claiming payment completion before the PSP outcome is known.

## Runtime seed preservation

**Decision:** Startup behavior for already persisted demo mandates

**Options considered (one per line):**

Rewrite the seed mandate every time the FastAPI runtime starts
Create the seed mandate only when its identifier is absent
Keep the mandate only in process memory

**What we chose:** Seed the demo mandate only on an empty durable runtime and preserve it unchanged on subsequent starts.

**Why:** Rewriting a persisted mandate would silently extend expiry or replace policy/revocation facts after a restart, which contradicts continuous authorization and durable audit requirements.

## Operational request authentication

**Decision:** Authentication boundary for payment runtime HTTP surfaces

**Options considered (one per line):**

Accept an unsigned local runtime header for ACP and capture calls
Apply RFC 9421 only to the original UCP checkout routes
Require RFC 9421 signatures over the raw request body on every operational payment POST and authenticated reader requests

**What we chose:** Reuse the trusted RFC 9421 agent registry and raw-body Content-Digest verifier for delegation, capture, receipt reads, and audit/dispute reads.

**Why:** Reusing the existing trust registry prevents a second identity authority and makes body tampering, unknown profiles, and signature failures fail before tokenization, Core authorization, or evidence disclosure.

## Canonical capture binding

**Decision:** Source of capture mandate, merchant, and amount

**Options considered (one per line):**

Trust mandate, merchant, and amount supplied by the capture caller
Duplicate those values into a payment-specific request policy
Load all capture scope from the persisted canonical checkout and validate its AP2 evidence before Core commit

**What we chose:** Capture accepts only a checkout identifier, opaque token, key-binding inputs, and AP2 closed checkout evidence; it derives authoritative scope from the canonical checkout.

**Why:** A caller-controlled total or merchant would create a second authorization representation. Verifying merchant authorization JCS/JWS and closed AP2 evidence against the persisted checkout blocks divergent values before a reservation, PSP call, receipt, or settlement audit event exists.

## Browser runtime source selection

**Decision:** Default browser data source for the live demo

**Options considered (one per line):**

Keep the fixture gateway as the default until all runtime endpoints are merged
Fall back silently from HTTP to fixtures when the runtime is unavailable
Use HTTP by default and permit fixtures only behind an explicit development-only flag

**What we chose:** `HttpAvalGateway` is the default. The fixture gateway is selected only when Vite is in development mode and `VITE_AVAL_USE_MOCK=true`; the UI then renders a persistent mock-data provenance strip.

**Why:** A silent or default fixture can make presentation data look like canonical state and can make a demo appear successful while the runtime is unavailable. An explicit development gate keeps fixtures useful for layout work without weakening live-demo evidence.

## Trial command availability

**Decision:** Administrative commands exposed by the browser

**Options considered (one per line):**

Simulate unsupported limit, scope, and budget commands locally
Invent HTTP endpoints that are not in the published runtime contract
Enable only commands backed by authenticated, idempotent, audited runtime endpoints

**What we chose:** The browser will enable signed mandate revocation after the runtime is integrated. Limit reduction, scope change, and budget-zero remain visibly unavailable because the published contract does not define those APIs.

**Why:** Local mutation would create a second authority and speculative endpoints would couple the UI to an imaginary protocol. The signed revocation endpoint is the only published administrative seam that can provide a real authenticated and auditable effect.

## Live workspace composition

**Decision:** Projection strategy for human, merchant, and auditor views

**Options considered (one per line):**

Populate missing live fields with fixture literals or browser-derived policy
Require an undocumented aggregate workspace endpoint
Compose only the published capture, receipt, audit, and dispute responses and render unavailable fields as unavailable

**What we chose:** The live UI will compose documented read-only runtime responses identified by configured mandate and capture IDs, without synthesizing mandate limits, private budgets, identity, or authorization state.

**Why:** The payment runtime contract intentionally exposes no aggregate workspace or mandate-detail response. Rendering only returned facts preserves `AuthorizationCore` as the sole source of truth and prevents merchant-visible leakage of private fields.

## Task 12 runtime conformance gate

**Decision:** When Task 12 may be reported green

**Options considered (one per line):**

Treat Laptop A's focused integration tests as sufficient E2E evidence
Adapt Laptop B tests to the current implementation even when it diverges from the published contract
Keep public E2E assertions red until the integrated runtime implements the published authentication, AP2, revocation, and audit boundaries

**What we chose:** Task 12 stays red until tests in `tests/integration/e2e/` pass against `origin/main` after the Laptop A merge, using public HTTP calls and stable contract responses.

**Why:** Runtime commit `9904b06` currently accepts unauthenticated delegation, omits the signed revocation route, and rejects the contract's capture `ap2` object. Weakening the tests would turn implementation drift into a second de facto contract and would make the demo evidence misleading.

## Direct Task 12 validation target

**Decision:** Git base for the corrected runtime validation

**Options considered (one per line):**

Wait for the runtime PR to merge into main
Merge the runtime branch into Laptop B locally
Rebase Laptop B directly onto the exact published runtime commit requested by the user

**What we chose:** Rebase onto
`origin/codex/laptop-a-live-payments` at
`3191d3e647e52180fe2367bf0d1a2e3740ea2ad0` without merging main.

**Why:** This validates the precise corrected artifact while preserving a linear,
reviewable Laptop B history and respecting the instruction not to merge or open
the final PR yet.

## Public E2E evidence boundary

**Decision:** How Task 12 proves absence of downstream payment effects

**Options considered (one per line):**

Inspect reservation, receipt, and audit tables after each request
Call Core services directly from the E2E suite
Observe only signed HTTP responses, receipts, audit, and dispute projections

**What we chose:** Use authenticated public HTTP as the assertion boundary.
After invalid AP2 or divergent capture input, compare the signed audit timeline
and prove that the same delegated token can still complete one canonical
capture. Direct SQLite access is permitted only to inject revocation-store
unavailability, never to establish the outcome.

**Why:** Database assertions or direct Core calls would bypass the deployed
composition and could hide missing routers, authentication dependencies, or
response mapping defects.

## Browser signing trust boundary

**Decision:** Behavior when no safe RFC 9421 browser signer is published

**Options considered (one per line):**

Embed local runtime private keys in Vite configuration
Treat cookies as equivalent to the contract's RFC 9421 identity
Keep the live browser state unavailable until a server-side signing bridge or browser-owned registered key is defined

**What we chose:** Do not ship trusted runtime private keys or simulate signed
success in the browser. The HTTP gateway remains the default transport, but a
direct browser session may surface authentication/unavailable state until a
safe signer boundary is published.

**Why:** Vite variables are public client assets, and cookie-only requests do
not satisfy the runtime contract. Either shortcut would weaken the identity
boundary precisely where Task 12 is intended to test it.

## Mandatory scope on listings

**Decision:** how `GET /mandates` and `GET /escalations` answer without a known id

**Options considered (one per line):**

Global listing, optionally filterable by holder
Global listing protected by an operator token
Mandatory per-holder scope, with no global variant anywhere

**What we chose:** `principal_id` is required, and no global query exists anywhere in
the stack — the repositories only know how to answer per holder, and the escalations
one reaches its rows by joining the mandate that owns them.

**Why:** an unscoped listing would hand any caller every buyer in the system, their
limits, their spend and their pending purchases — the same disclosure the merchant view
exists to prevent. A holder with no mandates gets an empty list and not a 404, so the
route does not become an oracle of which ids exist.

## The evaluation trace and who may read it

**Decision:** publishing the ladder the core walked, and to whom

**Options considered (one per line):**

Keep returning only the first refusal reason
Publish the trace in every response, including the merchant's
Publish the trace on the agent and holder surfaces, never on the merchant's

**What we chose:** `evaluation_trace` in `/authorize` and `/agent/purchase`; absent
from `/merchant/verify`, with a test that fails if it appears there.

**Why:** the ladder's order is the rule — authority before money — and returning only
the first reason made that order invisible. But the trace names limit, ceiling and
spend: a merchant that learned them would learn the buyer's budget from a receipt it
has every right to check.

## A monotonic demo clock

**Decision:** which direction `POST /admin/clock` may move time

**Options considered (one per line):**

Allow advancing and rewinding, so the team can re-stage the demo
Accept a negative value and silently treat it as zero
Advance only, refusing negative and zero with 422

**What we chose:** monotonic, with an explicit 422.

**Why:** advancing only takes authority away — mandates expire, nothing is granted.
Rewinding would revive an expired mandate, which is an operator handing back spending
authority that the holder's own validity had already ended. Refusing silently would be
worse than refusing loudly: the judge would believe they had rewound time without
having rewound it.

## The audit-trail tampering tool

**Decision:** how to offer the demonstration that the chain catches its own editor

**Options considered (one per line):**

Route always mounted, protected only by the operator token
Route always mounted, refusing with 403 when an environment variable is unset
Route not mounted unless `AVAL_DEMO_TAMPER` is enabled

**What we chose:** conditional mounting — without the variable the route does not exist
(a real 404, absent from OpenAPI), and with it it still requires an operator token.

**Why:** it is a tool for corrupting an audit log. A permission check can be
misconfigured to the permissive side; a route that was never registered cannot be.
There is no counterpart that repairs the chain: a route able to rewrite it into a valid
state would destroy the very property this one exists to prove.

## Frequency as authority, not preference

**Decision:** where *"up to 3 times a month"* lives

**Options considered (one per line):**

In the agent, next to the target price, as a purchase preference
In the core, as a hard refusal with no approval path
In the core, on the ladder, approvable like the budget

**What we chose:** in the core, between the ceiling and the budget, with escalation
possible.

**Why:** frequency says *how many times* the agent may act, the same way the budget
says *how much* — it is authority, and authority does not live in the agent. Being
approvable is the right call: a human can say yes to a fourth purchase, while the
ceiling remains the only limit with no button. A use is burned by money actually held,
so a card declined by the processor does not eat one of the buyer's allowed purchases.

## The holder's key lives in the browser

**Decision:** how a judge produces a holder ES256 JWS from a page

**Options considered (one per line):**

Embed a trusted runtime key in a Vite variable
Have the server sign as `operator` on the holder's behalf
Have the browser generate and hold its own non-extractable key

**What we chose:** a P-256 pair generated in the browser with `extractable: false`, the
handle kept in IndexedDB, the public JWK registered as the mandate's authority at
creation.

**Why:** Vite variables are public assets, so the first option publishes the key. The
second gives the operator exactly the power the security model denies it — and would
break that model at the very point where it is being demonstrated. Keeping the
`CryptoKey` in IndexedDB is the only way to persist a non-extractable key: the browser
holds the material, the page holds a handle that signs and cannot read. There is no
export path in the module, and a structural test fails if one appears.

## No fixtures behind the browser

**Decision:** what the page shows when the runtime does not answer

**Options considered (one per line):**

Fall back to fixtures labelled as mock
Keep the last known projection in cache
Say the runtime did not answer, and show nothing else

**What we chose:** an explicit unavailable state; no fixture module survived in
`web/src`.

**Why:** a page that fills itself with invented data when the server goes down is
indistinguishable from one that works, exactly when that difference matters most — in
front of a judge testing the system live. And a network failure rendered as a refusal
would say the mandate said no when it was never asked.

## An LLM in the proposing half, with the rules as the floor

**Decision:** whether a real model goes into the buying agent

**Options considered (one per line):**

Keep rules only — no key, no timeout, no risk on stage
Replace the rules with a model, requiring a credential to run the case
An optional model, with automatic fallback to the rules

**What we chose:** `AVAL_LLM_AGENT=1` plus a credential turn the model on; any failure
falls back to the rules, and the unconfigured default is the rules.

**Why:** the case speaks of an agent that *hallucinates a purchase*, and a rule-based
reader does not hallucinate — the demonstration could only assert that the core would
hold, never show it. A real model proposes genuinely wrong things and is refused just
the same. The model is **not told the limit, the ceiling or the balance**: beyond being
unnecessary for reading a sentence, sending the buyer's budget to a third party would
be the leak the rest of the system avoids, and a prompt-injected model has no private
number to repeat.

## Checkout completion and settlement boundary

**Decision:** Meaning of the UCP checkout completion status

**Options considered (one per line):**

Let checkout completion invoke the Core capture and PSP settlement
Report a settled checkout before the payment-capture endpoint runs
Verify AP2 completion and return a durable ready-for-capture state

**What we chose:** Completion now verifies the canonical AP2 checkout and returns `ready_for_capture`; only `POST /payment-captures` may commit a reservation, call the PSP, settle, or issue receipts.

**Why:** One status must have one lifecycle meaning. Separating evidence readiness from settlement prevents a checkout response from claiming a settled payment before the explicit capture boundary and preserves AuthorizationCore as the sole settlement authority.

## Revocation audit before settlement

**Decision:** Audit projection when a mandate is revoked before any capture

**Options considered (one per line):**

Hide the revocation timeline until a receipt exists
Create a synthetic settlement receipt for the audit reader
Return the append-only revocation timeline as incomplete evidence

**What we chose:** The dispute reader exposes a mandate's recorded revocation events even when no capture exists, returning an inconclusive evidence chain rather than inventing payment facts.

**Why:** A signed revocation is itself a durable authorization fact. It must be auditable immediately, while the absence of a reservation or receipt must remain explicit.

## RFC 9421 idempotency component scope

**Decision:** Signature components for operational reads

**Options considered (one per line):**

Require an idempotency key on every signed request
Allow unsigned GET requests
Require RFC 9421 on all routes while signing idempotency only for POST

**What we chose:** Every route signs method, authority, path, profile, content digest, and content type; POST adds `Idempotency-Key`, while GET does not require it.

**Why:** Reads still receive full identity and raw-body integrity protection without inventing an idempotency requirement for an operation that cannot mutate state. This matches the runtime contract's durable POST retry rule.

## Settlement event naming

**Decision:** Audit event emitted after a capture attempt

**Options considered (one per line):**

Record every approved capture as `capture.committed`
Record every approved capture as `capture.settled`
Distinguish a Core-only commit from a PSP-approved settlement

**What we chose:** The Core emits `capture.committed` only when no settlement adapter runs, and emits `capture.settled` when the PSP returns an approved settlement reference.

**Why:** The audit timeline must not erase the difference between a durable reservation commit and a completed settlement. This aligns the runtime receipt boundary and `status: settled` response with the underlying event.

## Runtime database path consistency

**Decision:** Default persistence used by the application factory

**Options considered (one per line):**

Use a hidden `.aval/runtime.sqlite3` only from the factory
Let the factory and ASGI entrypoint independently select their defaults
Use the configured `AVAL_DATABASE_PATH` in both entrypoints

**What we chose:** `create_app()` now uses the same configured durable database path as the ASGI entrypoint whenever a caller does not explicitly supply one.

**Why:** A restarted runtime must reopen the database that operators migrated and verified. Divergent implicit locations can leave one entrypoint on an obsolete schema and break durable authorization facts.

## Browser-safe UI authentication boundary

**Decision:** Authentication mechanism for live browser views and operator actions

**Options considered (one per line):**

Embed trusted RFC 9421 private keys in browser assets
Treat an unsigned browser cookie as equivalent to an agent signature on existing APIs
Add a same-origin session-authenticated BFF while preserving RFC 9421 for agent APIs

**What we chose:** Add a same-origin BFF with server-side role sessions and CSRF protection for browser views and operator commands; retain RFC 9421 and raw-body verification for agent-facing APIs.

**Why:** Browser assets cannot safely hold runtime signing keys, while an unsigned cookie does not satisfy the agent identity contract. A role-scoped BFF keeps private signing material in `KeyCustodyService`, applies the existing Core services without creating another policy authority, and enables an authenticated operator revocation without asking the browser to handle a JWS.

## Browser CSRF material boundary

**Decision:** Scope of the BFF CSRF value in the same-origin UI

**Options considered (one per line):**

Remove the published CSRF header and replace it with a different browser protocol
Treat the CSRF value as a browser credential and persist it in a cookie or storage
Keep the published one-time CSRF value only in transient browser memory for the required request header

**What we chose:** Preserve the published `csrf_token` login response and `X-AVAL-CSRF` request header. The value is an anti-CSRF nonce, not an authority credential, and may exist only in the login response and transient browser memory; it must not enter static assets, URLs, cookies, storage, logs, exceptions, or projections.

**Why:** The BFF contract explicitly requires the browser to send this value while keeping the session bearer cookie HttpOnly. Removing it would change the published API and break the UI handoff. Restricting its lifetime and locations retains the intended CSRF boundary without treating it as payment or signing authority.

## Same-origin browser build delivery

**Decision:** How the FastAPI runtime serves the browser production build

**Options considered (one per line):**

Keep Vite Preview as a second origin and configure CORS
Add a reverse proxy that forwards browser requests to Vite Preview
Serve the already-built `web/dist` bytes from FastAPI after all API routers are mounted

**What we chose:** FastAPI serves `web/dist` directly. It reserves every documented API root before a final GET/HEAD-only SPA fallback, returns API JSON for unknown API paths, and returns `503 ui_build_unavailable` when the build directory or `index.html` is absent.

**Why:** A direct static response keeps the SPA and BFF on one scheme, host, and port without inventing identity or relying on CORS. Reserving API namespaces prevents an unknown BFF or agent path from receiving `index.html`, while the explicit unavailable response avoids a simulated UI when a production build has not been made.

## ASGI runtime dependency

**Decision:** How the documented FastAPI server command is supplied after a clean project sync

**Options considered (one per line):**

Require operators to add Uvicorn with an ephemeral `uv run --with` flag
Declare Uvicorn as a runtime dependency and resolve it in the committed lockfile

**What we chose:** Declare Uvicorn as a direct runtime dependency and commit its resolved lockfile entries.

**Why:** The published same-origin launch command is part of the application delivery path. A clean `uv sync` must make that command available without an operator adding an undeclared, unreviewed package at launch time.

## Browser authentication remains fail-closed

**Status:** Historical decision, superseded by the approved browser-safe BFF and same-origin build delivery decisions above.

**Decision:** Final UI validation without a published browser signing boundary

**Options considered (one per line):**

Embed an RFC 9421 private key in the Vite application
Add an unsigned proxy or relax runtime signature verification
Keep the direct browser unavailable and record an architecture blocker

**What we chose:** Keep live browser reads and commands unavailable until a
browser-safe authenticated boundary is explicitly designed. The final
validation does not add a proxy, ship a key, or bypass RFC 9421.

**Why:** The corrected runtime correctly rejects unsigned audit reads with
`422 ucp_agent_invalid`. Converting that safe rejection into browser success
would create a second trust boundary without an approved custody or identity
model. The public signed E2E client remains the runtime evidence while the
browser blocker is tracked separately.

## Production browser projection excludes credential-shaped fixture fields

**Decision:** How the development fixture and defensive redaction coexist with a production bundle that must contain no `vt_` literal

**Options considered (one per line):**

Rely only on dead-code elimination to hide credential-shaped fixture fields
Remove defensive runtime redaction so its pattern does not appear in the bundle
Remove sensitive fields from browser projection types and encode defensive patterns without embedding credential-shaped literals

**What we chose:** Browser projection types and the development fixture no longer model vault-token or authorization-proof references. Defensive presentation redaction remains, but its prefix match is represented without placing a credential-shaped literal in the emitted artifact. The artifact test scans every emitted file for any `vt_` occurrence.

**Why:** A development fixture should model the same safe projection boundary as the live BFF, and production safety must be proven on emitted bytes rather than inferred from source imports. Keeping the redactor preserves fail-safe presentation while avoiding a forbidden credential-shaped marker in production assets.

## Browser BFF same-origin delivery gate

**Decision:** Final browser validation after the browser-safe BFF exists

**Options considered (one per line):**

Add a Vite proxy without an approved deployment topology
Make the browser call the BFF cross-origin and weaken cookie semantics
Keep relative same-origin calls and report the missing SPA/BFF delivery seam

**What we chose:** Keep `UiBffGateway` on relative `/ui-api/v1/` routes with
`credentials: "same-origin"`. Public HTTP E2E proves the BFF contract, while
the production browser flow remains blocked until an approved server or
development topology serves the SPA and BFF from one origin.

**Why:** The BFF session cookie is intentionally `HttpOnly`, `Secure`, and
`SameSite=Strict`. An ad-hoc cross-origin workaround or unapproved proxy would
change the security architecture. A visible 404 with cleared credentials is
safer and more truthful than fixture fallback or weakened cookie handling.

## Mainline agent demonstrations remain visible but inactive at the BFF boundary

**Decision:** How to preserve PRs #19 and #20 after rebasing the browser-safe UI

**Options considered (one per line):**

Restore the retired browser gateway and call `/agent/*` and `/admin/*` directly
Delete the authority atlas, attack scenarios, and standing-order presentation
Adapt the presentation to safe BFF projections and mark unpublished commands unavailable

**What we chose:** The authority atlas and all attack scenarios remain in the
holder view and now consume only role-scoped BFF workspace, audit, and dispute
projections. Standing-order capability remains implemented in the runtime and
is explained in the browser, but its create, list, tick, and catalogue controls
stay disabled until an explicit `/ui-api/v1/` contract is approved.

**Why:** The current BFF contract publishes no browser-safe purchase or watch
intent. Restoring direct agent calls would require RFC 9421 material in the
browser, while deleting the presentation would make the rebased UI incomplete.
An explicit unavailable state preserves both the capability and the security
boundary without inventing successful local behavior.

## Head-stamped SQLite frequency-schema repair

**Decision:** How to recover a legacy SQLite database that is marked at the Alembic head but lacks `mandates.max_uses`

**Options considered (one per line):**

Rewrite the historical frequency migration
Reset or rebuild the durable database
Add a forward-only compatibility migration that detects and restores the missing column

**What we chose:** Add a new forward-only migration that inspects `mandates`, adds nullable `max_uses` only when missing, and backfills existing rows with `NULL`; its downgrade leaves the repaired column in place.

**Why:** `NULL` is the current domain representation of `Mandate.usage_limit is None`, so a mandate written before frequency limits has no implicit usage cap. Historical migrations and durable facts remain untouched, while a no-op downgrade avoids recreating a schema that the current demonstration runtime cannot boot.

## Idempotency retention purge boundary

**Decision:** Eligibility for explicit idempotency-record removal

**Options considered (one per line):**

Delete all records past `retained_until`, regardless of state
Delete completed records only after a startup sweep
Delete completed records only when an operator invokes maintenance at or after `retained_until`

**What we chose:** The explicit maintenance operation deletes only `COMPLETED` records with `retained_until <= now` and returns only the count removed.

**Why:** A completed record must remain available for the full replay window, while an `IN_FLIGHT` record protects an unfinished side effect indefinitely. A caller-supplied UTC cutoff makes the operation deterministic and prevents retention cleanup from becoming an implicit startup side effect.

## Alembic runtime database target

**Decision:** Which SQLite database the documented Alembic upgrade command migrates

**Options considered (one per line):**

Keep Alembic's independent configured database path
Require operators to override Alembic manually for every runtime database
Make Alembic honor the same explicit runtime database environment variable

**What we chose:** When `AVAL_DATABASE_PATH` is present, Alembic resolves and migrates that exact SQLite database; otherwise it retains its configured default.

**Why:** A clean rehearsal must migrate the durable database that FastAPI will open. A separate implicit Alembic target can report a green migration while leaving a legacy runtime database structurally stale.

## Browser session generation boundary

**Decision:** How the BFF UI handles responses that complete after a session transition

**Options considered (one per line):**

Accept every completed BFF read into the current React state
Clear state only when a session error is observed
Associate reads with an in-memory session generation and ignore stale completions

**What we chose:** The UI increments an in-memory session generation whenever protected state is cleared or a new login succeeds, and applies BFF projections only when the originating generation remains current.

**Why:** A delayed response from an expired or logged-out session must not repopulate the next user's projection. The generation is transient browser control state, not an authority credential, and is never persisted or transmitted.
