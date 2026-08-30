# Telegram Real-Offer Watch Design

## Goal

Turn AVAL's existing Telegram bot into a shopping assistant that captures a
buyer’s mandate, safely collects a Stripe payment method, discovers real offers
on the web, and watches for a matching offer until the mandate expires.

## Scope and boundary

The MVP discovers live public offers and returns the seller URL and price. It
can create an off-session Stripe **test-mode** charge once AVAL's authorization
core approves the purchase. It does not claim to place an order at the external
seller: that requires a seller-specific checkout API and credentials, which are
outside this three-hour MVP.

## Architecture

`TelegramConversation` accepts free text and uses the OpenAI Responses API to
produce a validated shopping request: search query, desired category, maximum
price, and an optional watch deadline. A new `OfferDiscovery` port turns that
request into normalized candidates. Its first adapter calls OpenAI Responses
with the built-in web-search tool and accepts only candidates with a URL,
merchant name, ISO currency, positive price, and short evidence text.

The existing `WatchService` remains the owner of durable scheduled work. A
watch stores the shopping request as its instruction; on each tick the new
proposer refreshes candidates rather than reading the fixed travel catalogue.
The existing `AuthorizationCore` remains the only authorizer. It evaluates the
normalized offer against the mandate and, only after approval, the existing
`StripePspAdapter` may create its test-mode PaymentIntent.

## Two-computer topology

| Computer | Role | Holds | Must not hold |
| --- | --- | --- | --- |
| A — Conversation edge | Telegram polling/webhook, conversational extraction, OpenAI web discovery, and outgoing Telegram messages | `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, a narrowly scoped service credential for B | Stripe secret key, AVAL SQLite database, operator token, payment-method tokens |
| B — Authorization and settlement | AVAL API, SQLite, `WatchService` scheduler, mandate evaluation, Stripe Setup Checkout callback, and Stripe test-mode settlement | mandate/watch database, `AVAL_STRIPE_SECRET_KEY`, AVAL signing keys, operator token | Telegram bot token and OpenAI API key |

The computers communicate only over an authenticated private HTTP interface.
Computer A sends signed commands to create, amend, cancel, and inspect a watch.
Computer B owns the durable event outbox. It asks A to discover offers for an
open watch and treats the response as untrusted candidate data; it never grants
authority from the response. A polls B's outbox with a cursor and delivers
status messages to Telegram. This avoids inbound notification endpoints on A
and gives failed Telegram delivery a durable retry path.

Stripe Setup Checkout and the AVAL API on B require a public HTTPS tunnel or
deployment URL for the user return flow. The private A-to-B and B-to-A service
interfaces use separate scoped credentials and request signatures; neither
credential can call operator or payment endpoints.

## Telegram flow

1. `/start` identifies the chat and creates or resumes its holder identity.
2. The user sends a request such as “monitor a Nintendo Switch OLED for up to
   R$ 2.000 for 30 days”.
3. The bot asks only for missing mandate fields, then creates the mandate and
   replies with a Stripe Setup Checkout URL when no payment method is attached.
4. After Stripe reports a `pm_...` token, the bot confirms that the watch is
   active and tells the user its amount, deadline, and cancellation command.
5. A scheduled tick finds candidates. If none matches, the watch remains open.
   If one matches, authorization and test-mode settlement occur; Telegram sends
   the merchant, price, offer URL, and Stripe reference. A refusal or failed
   payment closes the watch and reports the reason.

## Data and safety rules

- Telegram messages never contain PAN, CVV, or Stripe secret keys.
- A stored card is only a Stripe `pm_...` token attached to the mandate.
- Search text and results are untrusted. The discovery adapter normalizes data;
  the LLM cannot issue payment calls or choose an amount outside a cited offer.
- A watch cannot outlive its mandate, and revocation is checked at the final
  authorization moment.
- A search result is evidence for discovery, not evidence of an external
  checkout. Customer-facing copy states this boundary explicitly.

## Configuration

Computer A needs `TELEGRAM_BOT_TOKEN`, `OPENAI_API_KEY`, and its scoped
service credential. Computer B needs `AVAL_PSP=stripe`, a Stripe **test**
secret key, and its separate scoped service credential. The Stripe return URL
must be public HTTPS so Telegram users can complete the Setup Checkout page.
Secrets live only in the ignored environment files of the computer that owns
them.

## Verification

Unit tests cover request extraction, result normalization, malformed and
price-less search results, and the no-match path. Integration tests cover a
persisted watch using a fake discovery adapter, authorization/revocation at
tick time, and the Telegram response that contains only the Stripe Checkout
URL. Integration tests cover a rejected inter-computer signature and a
redelivered outbox event. A manual demo uses Stripe test cards and verifies
that no external seller order is claimed.
