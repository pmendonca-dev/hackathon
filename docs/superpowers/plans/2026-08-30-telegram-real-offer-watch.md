# Telegram Real-Offer Watch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Run an autonomous Telegram shopping watch across two computers, using real web-discovered offers and Stripe test-mode settlement while AVAL remains the only authority over spending.

**Architecture:** Computer A is the Telegram/OpenAI edge; Computer B owns AVAL, SQLite, the scheduler, Stripe, and a durable notification outbox. A's discovery response is untrusted candidate data; B turns a selected candidate into an AVAL-signed test-marketplace offer and only then runs the existing authorization and capture flow. Scoped HMAC-authenticated edge endpoints carry commands, discovery, and events between the computers.

**Tech Stack:** Python 3.12+, FastAPI, SQLAlchemy/Alembic, stdlib HTTP, OpenAI Python SDK Responses API with web search, Telegram Bot API, Stripe API, pytest.

**Spec:** docs/superpowers/specs/2026-08-30-telegram-real-offer-watch-design.md

## Global Constraints

- Computer A owns TELEGRAM_BOT_TOKEN and OPENAI_API_KEY; Computer B must not read either.
- Computer B owns AVAL_STRIPE_SECRET_KEY, signing keys, SQLite, and scheduler state; Computer A must not read them.
- Use Stripe test mode only, and always tell users that a discovered seller has not received an external order.
- Never accept PAN, CVV, or a payment-method token from Telegram text or a discovery response.
- A candidate may affect a purchase only after B normalizes it, signs an AVAL test-marketplace offer, and AuthorizationCore authorizes it.
- Inter-computer calls use timestamped HMAC headers, body digest verification, a five-minute freshness window, and distinct credentials in each direction.

---

### Task 1: Scoped edge authentication and configuration

**Files:**
- Create: src/aval/security/edge_auth.py
- Modify: src/aval/interfaces/telegram/config.py
- Modify: .env.example
- Test: tests/unit/security/test_edge_auth.py

**Interfaces:**
- Produces EdgeSigner(secret, clock).sign(method, path, body) -> dict[str, str].
- Produces verify_edge_request(secret, method, path, body, headers, now) -> None; it raises EdgeAuthError for missing, stale, malformed, or mismatched headers.
- Adds BotConfig.edge_to_core_secret and BotConfig.core_event_secret; both are mandatory only when AVAL_EDGE_MODE=remote.

- [ ] **Step 1: Write the failing test**

~~~python
def test_hmac_signature_binds_method_path_and_body(clock):
    signer = EdgeSigner("edge-secret", clock=lambda: clock)
    headers = signer.sign("POST", "/edge/v1/discover", b'{"query":"switch"}')
    verify_edge_request("edge-secret", "POST", "/edge/v1/discover", b'{"query":"switch"}', headers, clock)

def test_stale_or_modified_requests_are_rejected(clock):
    headers = EdgeSigner("edge-secret", clock=lambda: clock).sign("POST", "/edge/v1/discover", b"{}")
    with pytest.raises(EdgeAuthError):
        verify_edge_request("edge-secret", "POST", "/edge/v1/discover", b'{"changed":true}', headers, clock)
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: uv run pytest tests/unit/security/test_edge_auth.py -q

Expected: FAIL because edge_auth does not exist.

- [ ] **Step 3: Write the minimal implementation**

~~~python
canonical = b"\n".join([method.encode(), path.encode(), timestamp.encode(), sha256(body).hexdigest().encode()])
signature = hmac.new(secret.encode(), canonical, hashlib.sha256).hexdigest()
~~~

Require X-Aval-Edge-Timestamp and X-Aval-Edge-Signature, use hmac.compare_digest, and reject timestamps outside 300 seconds. Add the two direction-specific environment settings without printing their values.

- [ ] **Step 4: Run the test to verify it passes**

Run: uv run pytest tests/unit/security/test_edge_auth.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/aval/security/edge_auth.py src/aval/interfaces/telegram/config.py .env.example tests/unit/security/test_edge_auth.py
git commit -m "feat: authenticate telegram edge requests"
~~~

### Task 2: Computer A discovery service using OpenAI web search

**Files:**
- Create: src/aval/discovery/models.py
- Create: src/aval/discovery/openai_web.py
- Create: src/aval/interfaces/discovery/app.py
- Modify: pyproject.toml
- Test: tests/unit/discovery/test_openai_web.py
- Test: tests/integration/api/test_discovery_edge.py

**Interfaces:**
- Produces ShoppingRequest(query, category, max_minor_units, currency).
- Produces DiscoveredOffer(title, source_merchant, source_url, amount_minor_units, currency, evidence).
- OfferDiscovery.find(request) -> list[DiscoveredOffer] returns at most five normalized candidates.
- Computer A exposes POST /edge/v1/discover; only requests signed with B-to-A credentials receive {"offers": [...]}.

- [ ] **Step 1: Write failing normalization and edge-auth tests**

~~~python
def test_response_with_url_price_and_evidence_becomes_a_candidate():
    discovery = OpenAIWebDiscovery(responder=lambda _: valid_response())
    offer = discovery.find(ShoppingRequest("Nintendo Switch OLED", "shopping", 200000, "BRL"))[0]
    assert offer.source_url == "https://shop.example/switch"

def test_candidate_without_https_url_or_positive_price_is_dropped():
    assert OpenAIWebDiscovery(responder=lambda _: invalid_response()).find(request) == []
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: uv run pytest tests/unit/discovery/test_openai_web.py tests/integration/api/test_discovery_edge.py -q

Expected: FAIL because discovery types and route do not exist.

- [ ] **Step 3: Write the minimal implementation**

Call client.responses.create with tools=[{"type": "web_search"}], a structured JSON response request, and a prompt that permits only public discovery. Coerce its output into DiscoveredOffer; strip tracking query strings, require HTTPS, currency matching the request, a positive price at or below the cap, merchant, and evidence. Return an empty list on OpenAI, parsing, or search failure. Verify B-to-A HMAC before parsing the FastAPI request, and do not import AVAL runtime or Stripe modules on A.

- [ ] **Step 4: Run tests to verify they pass**

Run: uv run pytest tests/unit/discovery/test_openai_web.py tests/integration/api/test_discovery_edge.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add pyproject.toml src/aval/discovery src/aval/interfaces/discovery tests/unit/discovery tests/integration/api/test_discovery_edge.py
git commit -m "feat: add authenticated real-offer discovery edge"
~~~

### Task 3: Computer B candidate issuer and watch execution

**Files:**
- Create: src/aval/discovery/core_client.py
- Create: src/aval/merchant/discovered_offers.py
- Modify: src/aval/agent/purchasing_agent.py
- Modify: src/aval/agent/watches.py
- Modify: src/aval/agent/scheduler.py
- Modify: src/aval/runtime.py
- Test: tests/unit/merchant/test_discovered_offers.py
- Test: tests/integration/api/test_real_offer_watches.py

**Interfaces:**
- CoreDiscoveryClient.find(request) signs B-to-A requests and returns no offers when A is unavailable.
- DiscoveredOfferIssuer.issue(candidate) emits the existing purchase shape with merchant_id="aval_test_marketplace", category "shopping", signed terms, and source metadata.
- PurchasingAgent.run(..., offers=None) uses supplied offers for a watch and preserves the existing catalog path when offers is None.

- [ ] **Step 1: Write failing issuer and watch tests**

~~~python
def test_discovered_offer_is_signed_as_the_test_marketplace(runtime):
    offer = DiscoveredOfferIssuer(runtime).issue(candidate())
    assert offer["merchant_id"] == "aval_test_marketplace"
    assert offer["item"]["source_url"] == "https://shop.example/switch"
    assert offer["merchant_authorization"]

def test_revoked_watch_does_not_charge_even_when_discovery_matches(runtime, holder):
    watch = register_real_offer_watch(runtime, holder)
    revoke(runtime, holder, watch.mandate_id)
    tick_once(runtime)
    assert read_watch(runtime, watch.id).outcome == "mandate_revoked"
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: uv run pytest tests/unit/merchant/test_discovered_offers.py tests/integration/api/test_real_offer_watches.py -q

Expected: FAIL because external candidates cannot become offers.

- [ ] **Step 3: Write the minimal implementation**

Register an AVAL-owned aval_test_marketplace signing key and allow shopping as the MVP category. The issuer copies only normalized candidate fields, signs the existing merchant offer payload, and adds source_merchant, source_url, and evidence as display metadata. A watch tick parses its stored shopping request, calls CoreDiscoveryClient, issues offers, and passes them to PurchasingAgent.run. Preserve no_offer as an open watch; close only expiry or an authorization/settlement outcome. The B scheduler, not Telegram, invokes this tick.

- [ ] **Step 4: Run relevant tests**

Run: uv run pytest tests/integration/api/test_agent_watches.py tests/integration/api/test_watch_scheduler.py tests/unit/merchant/test_discovered_offers.py tests/integration/api/test_real_offer_watches.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/aval/discovery/core_client.py src/aval/merchant/discovered_offers.py src/aval/agent src/aval/runtime.py tests/unit/merchant/test_discovered_offers.py tests/integration/api/test_real_offer_watches.py
git commit -m "feat: run watches against real discovered offers"
~~~

### Task 4: Durable event outbox and private Computer A API

**Files:**
- Create: src/aval/application/services/edge_events.py
- Create: src/aval/infrastructure/sqlite/edge_event_repository.py
- Create: src/aval/api/routes/edge.py
- Create: alembic/versions/0014_edge_events.py
- Modify: src/aval/infrastructure/sqlite/models.py
- Modify: src/aval/api/app.py
- Modify: src/aval/agent/watches.py
- Test: tests/integration/api/test_edge_events.py

**Interfaces:**
- EdgeEvent(id, principal_id, event_type, payload, created_at, delivered_at) is persisted by B.
- GET /edge/v1/events?after=<id> returns A's events only after A-to-B HMAC verification.
- POST /edge/v1/events/{id}/ack marks one delivered event and is idempotent.

- [ ] **Step 1: Write the failing outbox test**

~~~python
def test_closed_watch_emits_one_event_and_ack_is_idempotent(client, signed_edge_headers):
    event = close_matching_watch(client)
    events = client.get("/edge/v1/events", headers=signed_edge_headers).json()["events"]
    assert events[0]["event_type"] == "watch_closed"
    assert client.post(f"/edge/v1/events/{event.id}/ack", headers=signed_edge_headers).status_code == 204
    assert client.post(f"/edge/v1/events/{event.id}/ack", headers=signed_edge_headers).status_code == 204
~~~

- [ ] **Step 2: Run the test to verify it fails**

Run: uv run pytest tests/integration/api/test_edge_events.py -q

Expected: FAIL because the event table and private endpoints do not exist.

- [ ] **Step 3: Write the minimal implementation**

Add an edge_events SQLite table and migration. In the same write transaction that closes a watch, append a watch_closed payload containing principal id, safe offer title, source URL, amount, outcome, and Stripe reference—never a payment token or JWS. Require A-to-B HMAC, return only undelivered events after the cursor, and make repeated acknowledgement succeed.

- [ ] **Step 4: Run API and migration tests**

Run: uv run pytest tests/integration/api/test_edge_events.py tests/integration/test_database_migrations.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/aval/application/services/edge_events.py src/aval/infrastructure/sqlite/edge_event_repository.py src/aval/api/routes/edge.py src/aval/api/app.py src/aval/agent/watches.py src/aval/infrastructure/sqlite/models.py alembic/versions/0014_edge_events.py tests/integration/api/test_edge_events.py
git commit -m "feat: deliver watch results through durable edge events"
~~~

### Task 5: Telegram shopping workflow on Computer A

**Files:**
- Modify: src/aval/interfaces/telegram/conversation.py
- Modify: src/aval/interfaces/telegram/gateway.py
- Modify: src/aval/interfaces/telegram/bot.py
- Modify: src/aval/interfaces/telegram/views.py
- Modify: src/aval/interfaces/telegram/config.py
- Test: tests/unit/interfaces/test_telegram_conversation.py
- Test: tests/unit/interfaces/test_telegram_bot.py

**Interfaces:**
- ShoppingDraft(query, category, max_minor_units, currency, watch_days) is shown before a mandate/watch is created.
- AvalGateway.edge_events(after=None) -> Sequence[EdgeEventView] and ack_edge_event(event_id) use A-to-B HMAC.
- The bot has no tick_watches call; it polls events and maps principal_id back to its local chat identity.

- [ ] **Step 1: Write failing conversation and delivery tests**

~~~python
def test_shopping_sentence_requires_budget_and_deadline_before_confirmation():
    draft = talker.respond(history("acompanhe um notebook"), categories=["shopping"], defaults=defaults)
    assert draft.spec is None

def test_bot_sends_offer_link_then_acknowledges_event(bot, aval):
    aval.enqueue_watch_closed(principal_id="usr_tg_9", source_url="https://shop.example/item")
    bot.push_watch_results()
    assert "shop.example/item" in bot.sent_messages[-1].text
    assert aval.acknowledged_event_ids
~~~

- [ ] **Step 2: Run tests to verify they fail**

Run: uv run pytest tests/unit/interfaces/test_telegram_conversation.py tests/unit/interfaces/test_telegram_bot.py -q

Expected: FAIL because the shopping draft and event polling are absent.

- [ ] **Step 3: Write the minimal implementation**

Extend the strict LLM schema with query, maximum price, category shopping, and days; retain a no-network fallback that asks for missing values. Show a confirmation card stating cap, deadline, automatic test-mode charge, and external-order limitation. Reuse /cartao for the Stripe Setup Checkout URL. Replace edge-side watch ticking with event polling; acknowledge only after Telegram confirms delivery.

- [ ] **Step 4: Run Telegram regression tests**

Run: uv run pytest tests/unit/interfaces/test_telegram_conversation.py tests/unit/interfaces/test_telegram_bot.py -q

Expected: PASS.

- [ ] **Step 5: Commit**

~~~bash
git add src/aval/interfaces/telegram tests/unit/interfaces/test_telegram_conversation.py tests/unit/interfaces/test_telegram_bot.py
git commit -m "feat: make telegram shopping watches conversational"
~~~

### Task 6: Two-machine launch, security regression, and demo rehearsal

**Files:**
- Create: scripts/discovery_edge_up.sh
- Create: scripts/core_b_up.sh
- Modify: scripts/bot_up.sh
- Modify: .env.example
- Modify: README.md
- Create: docs/verification/two-computer-telegram-rehearsal.md
- Test: tests/integration/e2e/test_two_computer_real_offer_flow.py

**Interfaces:**
- A starts discovery edge and Telegram bot using only A variables.
- B runs migrations, AVAL API, and the watch scheduler using only B variables.
- E2E uses fake OpenAI/Stripe transports and real HMAC headers; it does not call external services.

- [ ] **Step 1: Write the failing end-to-end test**

~~~python
def test_real_offer_watch_crosses_boundary_without_secret_leak(two_machine_harness):
    two_machine_harness.create_confirmed_watch("notebook", max_brl=2000)
    two_machine_harness.tick_core()
    event = two_machine_harness.poll_telegram_edge()
    assert event.source_url.startswith("https://")
    assert "pm_" not in event.text
    assert two_machine_harness.stripe_payment_intents == 1
~~~

- [ ] **Step 2: Run the E2E test to verify it fails**

Run: uv run pytest tests/integration/e2e/test_two_computer_real_offer_flow.py -q

Expected: FAIL until both processes and event interfaces are wired.

- [ ] **Step 3: Add least-privilege launch instructions**

Make separate launcher scripts load separate environment files and fail before startup if another computer's secret is present. Document the HTTPS return URL, Stripe test card rehearsal, explicit demo wording, migration command, restart behavior, and cancel/revoke flow.

- [ ] **Step 4: Run focused and full verification**

Run: uv run pytest tests/unit/security/test_edge_auth.py tests/unit/discovery/test_openai_web.py tests/integration/api/test_real_offer_watches.py tests/integration/api/test_edge_events.py tests/integration/e2e/test_two_computer_real_offer_flow.py -q

Run: uv run pytest -q

Expected: PASS for both; no credential-shaped values appear in logs, API payloads, or Telegram test messages.

- [ ] **Step 5: Commit**

~~~bash
git add scripts/discovery_edge_up.sh scripts/core_b_up.sh scripts/bot_up.sh .env.example README.md docs/verification/two-computer-telegram-rehearsal.md tests/integration/e2e/test_two_computer_real_offer_flow.py
git commit -m "docs: rehearse two-computer shopping watch demo"
~~~
