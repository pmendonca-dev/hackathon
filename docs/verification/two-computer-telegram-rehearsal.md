# Two-computer real-offer watch — rehearsal

A person types *acompanhe um notebook até 2000 por 30 dias* into Telegram. Some minutes
later their phone says the agent bought one, names the shop, links the page, and shows
the charge reference. Nobody was at the keyboard when it happened.

This is how to set that up on two machines, and what to check before showing it.

## What each computer is

| | **A — conversation edge** | **B — authorization and settlement** |
|---|---|---|
| Runs | Telegram bot, discovery edge | AVAL API, SQLite, watch scheduler, Stripe |
| Holds | `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY` | `AVAL_CUSTODY_SEED`, `AVAL_STRIPE_SECRET_KEY`, operator token, the database |
| Must never hold | any of B's secrets | the Telegram token, the OpenAI key |
| Reads | `.env.edge` | `.env.core` |
| Launcher | `scripts/discovery_edge_up.sh` | `scripts/core_b_up.sh` |

Both launchers refuse to start if the other machine's secrets are in their environment,
and the Python entrypoint on A checks again before it listens. A launcher is a
convenience; the process is the boundary.

Both computers hold **both** edge secrets — that is inherent to HMAC and costs nothing.
Neither can create a mandate, authorize a spend or capture a payment with them: that
authority is a holder's ES256 signature, and only B can verify one. There are two
secrets rather than one so that a leak of the public-facing discovery credential is not
also a key to the event outbox.

## Setting up

Generate two different secrets and put them on both machines:

```bash
python -c "import secrets; print(secrets.token_urlsafe(48))"   # AVAL_EDGE_TO_CORE_SECRET
python -c "import secrets; print(secrets.token_urlsafe(48))"   # AVAL_CORE_TO_EDGE_SECRET
```

**`.env.edge`, on A:**

```
AVAL_EDGE_MODE=remote
AVAL_EDGE_TO_CORE_SECRET=<first>
AVAL_CORE_TO_EDGE_SECRET=<second>
TELEGRAM_BOT_TOKEN=<from @BotFather>
TELEGRAM_OPEN_MODE=1
OPENAI_API_KEY=<sk-...>
AVAL_DISCOVERY=1
AVAL_TELEGRAM_LLM=1
AVAL_API_BASE_URL=https://<B's public URL>
AVAL_DISCOVERY_HOST=0.0.0.0
AVAL_DISCOVERY_PORT=9100
```

**`.env.core`, on B:**

```
AVAL_EDGE_MODE=remote
AVAL_EDGE_TO_CORE_SECRET=<first>
AVAL_CORE_TO_EDGE_SECRET=<second>
AVAL_DISCOVERY_EDGE_URL=http://<A's address>:9100
AVAL_CUSTODY_SEED=<from scripts/production/new-secrets.ps1>
AVAL_PAIRWISE_SECRET=<same>
AVAL_OPERATOR_TOKEN=<same>
AVAL_PSP=stripe
AVAL_STRIPE_SECRET_KEY=sk_test_...
AVAL_WATCH_TICK_SECONDS=30
AVAL_DATABASE_PATH=var/aval.db
AVAL_ALLOWED_ORIGINS=https://<B's public URL>
```

`AVAL_CUSTODY_SEED` is not optional here. Without it every boot draws fresh keys while
the database keeps the old public halves, and every purchase after the first restart
dies as `signature_invalid`.

Stripe's Setup Checkout returns the buyer to B, so **B needs a public HTTPS URL** — a
tunnel is fine. A does not: B reaches it over the private network, and it should not be
publicly routable at all.

Start B first, then A. A checks `${AVAL_API_BASE_URL}/health` and refuses to start the
bot if the core is not answering, so the first person to tap `/start` never meets a raw
error.

```bash
# on B
./scripts/core_b_up.sh          # runs `alembic upgrade head`, then serves

# on A
./scripts/discovery_edge_up.sh  # discovery on :9100, then the bot
```

## The rehearsal

1. **`/start`** in Telegram. The chat gets its own key and its own mandate. Open mode is
   safe: each chat can only ever move its own authority, which is what lets a room of
   judges share one bot.
2. **`/cartao`** opens Stripe Setup Checkout. Use `4242 4242 4242 4242`, any future
   expiry, any CVC. What comes back is a `pm_...` token bound to the mandate — never a
   card number. The bot cannot show a card number because it never receives one.
3. **Type the request:** *acompanhe um notebook até 2000 por 30 dias*. The bot answers
   with two cards, and they are deliberately two decisions:
   - the **mandate** — what may be spent, on what, for how long;
   - the **watch** — that the agent will spend it without asking again.
4. **Confirm.** Only now does anything exist: the mandate is signed with the chat's own
   key, and the watch is registered against it.
5. **Wait one tick** (`AVAL_WATCH_TICK_SECONDS`). B asks A for candidates, A searches the
   web, B re-issues the best one as a signed offer, and `AuthorizationCore` decides.
6. **The phone buzzes.** Merchant, price, the page's link, and the Stripe reference.

### What to say out loud

> *No order was placed with that seller.* AVAL found a public page, and charged this
> person's own test-mode card. The message says so every time, and that sentence is not
> decoration — it is the boundary of what this demonstrates.

The link in the message is the point: a person can open it and check the claim instead
of believing it.

### The refusals, which are the real demo

- **Revoke mid-flight** (`/revogar`) and wait a tick. A still finds the page; B refuses
  to pay for it, and the chat says `mandate_revoked`. The agent kept working; the
  authority did not.
- **Set the cap below the market.** The search finds pages, the mandate refuses them,
  and the watch reports the refusal as loudly as it would report a purchase.
- **Scope the mandate to `travel` only.** Every discovered page comes back
  `category_not_allowed`. The marketplace that signs discovered pages is a merchant like
  any other, and scope applies to it.

### Cancelling

`/revogar` ends the mandate, and a watch may not outlive the authority that funds it. A
watch also stops on its own deadline, which the model clamps to the mandate's window at
draft time — a standing order against nothing is not a standing order.

## Restart behaviour

- **B restarts:** watches are rows, so they survive. With `AVAL_CUSTODY_SEED` set, so do
  the keys. Undelivered events survive too — they are a table, not a callback.
- **A restarts:** it re-polls the outbox and delivers whatever Telegram had not taken.
  Nothing is lost, because reading is not acknowledging: A marks an event delivered only
  after Telegram has accepted the message.
- **The network drops between them:** watches stay open (a search that could not run is
  not an answer about prices) and events queue. Both catch up on their own.

## Verifying without the two machines

The whole crossing is covered in one process, with real HMAC headers and fake OpenAI and
Stripe transports:

```bash
uv run pytest tests/integration/e2e/test_two_computer_real_offer_flow.py -q
```

It asserts the journey end to end, that no payment token or signature reaches the edge,
that tracking parameters are stripped from the link, that a revoked mandate stops the
charge on the far side of the boundary, and that neither computer serves the other's
half of the system.
