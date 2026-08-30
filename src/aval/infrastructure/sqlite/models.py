from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
)


metadata = MetaData()

mandates = Table(
    "mandates",
    metadata,
    Column("id", String, primary_key=True),
    Column("principal_id", String, nullable=False),
    Column("principal_display_name", String, nullable=False),
    Column("allowed_merchant_ids", Text, nullable=False),
    Column("allowed_categories", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scale", Integer, nullable=False),
    Column("limit_minor_units", Integer, nullable=False),
    Column("ceiling_minor_units", Integer),
    # Frequency condition: "up to N purchases in a rolling window". Both columns
    # are set together or both null; the domain refuses a half-declared limit.
    Column("max_uses", Integer),
    Column("usage_window_seconds", Integer),
    # The payment method the mandate names. The token is what the agent presents at
    # capture; the label is the four digits a person recognises. Neither is a PAN, and
    # both are null on a mandate that accepts any instrument.
    Column("instrument_token", String),
    Column("instrument_label", String),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("policy_version", Integer, nullable=False),
    Column("revocation_epoch", Integer, nullable=False, default=0),
    Column("revocation_metadata", Text, nullable=False),
    CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="mandate_status"),
)

mandate_creation_proofs = Table(
    # The holder's signature over the terms the mandate was born with.
    #
    # Kept beside the mandate rather than inside it: the row is evidence about an event,
    # not a property of the live authority, and the mandate's own shape stays the shape
    # every decision reads. `nonce` is unique because a creation is replayable in a way a
    # revocation is not — the same signature twice would mint a second mandate with the
    # same terms, doubling authorized spend without a second signature.
    "mandate_creation_proofs",
    metadata,
    Column("mandate_id", ForeignKey("mandates.id"), primary_key=True),
    Column("kid", String, nullable=False),
    Column("nonce", String, nullable=False),
    Column("signed_jws", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Index("ux_mandate_creation_proof_nonce", "nonce", unique=True),
)

revocation_authorities = Table(
    "revocation_authorities",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("role", String, nullable=False),
    Column("kid", String, nullable=False),
    Column("public_jwk", Text, nullable=False),
    Column("allowed_scope", String, nullable=False),
)

revocations = Table(
    "revocations",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("authority_id", ForeignKey("revocation_authorities.id"), nullable=False),
    Column("scope", String, nullable=False),
    Column("reason", String, nullable=False),
    Column("epoch", Integer, nullable=False),
    Column("signed_jws", Text, nullable=False),
    Column("revoked_at", DateTime(timezone=True), nullable=False),
)

policy_rules = Table(
    "policy_rules",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("version", Integer, nullable=False),
    Column("rule_json", Text, nullable=False),
    Column("active", Integer, nullable=False, default=1),
)

checkout_intents = Table(
    "checkout_intents",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("merchant_id", String, nullable=False),
    Column("total_minor_units", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scale", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("canonical_payload", Text, nullable=False),
)

reservations = Table(
    "reservations",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("checkout_intent_id", ForeignKey("checkout_intents.id"), nullable=False),
    Column("amount_minor_units", Integer, nullable=False),
    Column("status", String, nullable=False),
    Column("transaction_hash", String),
    # When the money was actually held. A frequency limit counts these, so a
    # reservation the processor released clears it and does not burn a use.
    Column("committed_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('PENDING', 'COMMITTED', 'SETTLED', 'RELEASED')",
        name="reservation_status",
    ),
    UniqueConstraint("mandate_id", "transaction_hash", name="reservation_mandate_transaction"),
)

authorization_proofs = Table(
    "authorization_proofs",
    metadata,
    Column("id", String, primary_key=True),
    Column("reservation_id", ForeignKey("reservations.id"), nullable=False),
    Column("jti", String, nullable=False, unique=True),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("signed_proof", Text, nullable=False),
)

capture_attempts = Table(
    "capture_attempts",
    metadata,
    Column("id", String, primary_key=True),
    Column("reservation_id", ForeignKey("reservations.id"), nullable=False),
    Column("idempotency_key", String, nullable=False, unique=True),
    Column("status", String, nullable=False),
    Column("settlement_reference", String),
)

idempotency_records = Table(
    "idempotency_records",
    metadata,
    Column("id", String, primary_key=True),
    Column("scope", String, nullable=False),
    Column("idempotency_key", String, nullable=False),
    Column("request_hash", String, nullable=False),
    Column("state", String, nullable=False),
    Column("response_body", Text),
    Column("retained_until", DateTime(timezone=True), nullable=False),
    CheckConstraint("state IN ('IN_FLIGHT', 'COMPLETED')", name="idempotency_state"),
    UniqueConstraint("scope", "idempotency_key", name="idempotency_scope_key"),
)

# Browser sessions are an authentication boundary, separate from Core authority.
# Only hashes of the opaque cookie and CSRF bearer values are durable facts.
browser_ui_sessions = Table(
    "browser_ui_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("token_hash", String(64), nullable=False, unique=True),
    Column("csrf_hash", String(64), nullable=False),
    Column("role", String, nullable=False),
    Column("merchant_id", String),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
    Index(
        "ix_browser_ui_sessions_active_lookup",
        "token_hash",
        "expires_at",
        "revoked_at",
    ),
)

mandate_locks = Table(
    "mandate_locks",
    metadata,
    Column("mandate_id", ForeignKey("mandates.id"), primary_key=True),
    Column("touched_at", DateTime(timezone=True), nullable=False),
)

evidence = Table(
    "evidence",
    metadata,
    Column("id", String, primary_key=True),
    Column("kind", String, nullable=False),
    Column("origin", String, nullable=False),
    Column("sha256", String, nullable=False),
    Column("payload", Text, nullable=False),
)

audit_events = Table(
    "audit_events",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("event_type", String, nullable=False),
    Column("human_summary", Text, nullable=False),
    Column("evidence_id", ForeignKey("evidence.id")),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("sequence", Integer, nullable=False),
    UniqueConstraint("mandate_id", "sequence", name="audit_event_mandate_sequence"),
)

operator_sessions = Table(
    # A short-lived stand-in for the operator token.
    #
    # The token is a permanent secret, and a permanent secret shipped into a browser
    # bundle is a permanent secret published. What the console holds instead is one of
    # these: minted from the token, expiring on its own, revocable, and named in every
    # line it writes to the journal. Only the hash is stored — a stolen database does
    # not hand anyone a working session.
    "operator_sessions",
    metadata,
    Column("id", String, primary_key=True),
    Column("token_hash", String, nullable=False, unique=True),
    Column("issued_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("revoked_at", DateTime(timezone=True)),
)

operator_journal = Table(
    # What the operator did, chained the way the mandate trail is chained.
    #
    # The holder signs to spend; nobody signs to operate, so the operator's own actions
    # are the one authority in this system with no cryptographic author. A hash chain is
    # the honest substitute: it cannot prove who typed, and it can prove nothing was
    # quietly removed afterwards.
    "operator_journal",
    metadata,
    Column("id", String, primary_key=True),
    Column("sequence", Integer, nullable=False, unique=True),
    Column("action", String, nullable=False),
    Column("actor", String, nullable=False),
    Column("detail", Text, nullable=False),
    Column("occurred_at", DateTime(timezone=True), nullable=False),
    Column("sha256", String, nullable=False),
    Column("previous_sha256", String, nullable=False),
    Column("canonical_payload", Text, nullable=False),
)

agent_profiles = Table(
    "agent_profiles",
    metadata,
    Column("id", String, primary_key=True),
    Column("profile_url", String, nullable=False, unique=True),
    Column("profile_json", Text, nullable=False),
    Column("trusted", Integer, nullable=False, default=0),
)

vault_tokens = Table(
    "vault_tokens",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("checkout_intent_id", ForeignKey("checkout_intents.id"), nullable=False),
    Column("merchant_id", String, nullable=False),
    Column("max_amount_minor_units", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scale", Integer, nullable=False, default=2),
    Column("expires_at", DateTime(timezone=True), nullable=False),
)

disputes = Table(
    "disputes",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("reservation_id", ForeignKey("reservations.id"), nullable=False),
    Column("reason", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("resolution", Text),
    Column("opened_at", DateTime(timezone=True), nullable=False),
    Column("resolved_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('OPEN', 'MANDATE_HELD', 'MANDATE_FAILED')", name="dispute_status"
    ),
)

escalations = Table(
    "escalations",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("checkout_id", String, nullable=False),
    Column("merchant_id", String, nullable=False),
    Column("category", String, nullable=False),
    Column("amount_minor_units", Integer, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scale", Integer, nullable=False),
    Column("reason_code", String, nullable=False),
    Column("status", String, nullable=False),
    Column("agent_id", String),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("approval_jws", Text),
    Column("decided_at", DateTime(timezone=True)),
    CheckConstraint("status IN ('OPEN', 'APPROVED', 'DENIED')", name="escalation_status"),
)

agent_watches = Table(
    "agent_watches",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    # The sentence the person said, re-read on every tick. Freezing a parsed target
    # price here would let the row and the instruction disagree about what was asked.
    Column("instruction", Text, nullable=False),
    Column("status", String, nullable=False),
    Column("outcome", String),
    Column("settlement_reference", String),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("closed_at", DateTime(timezone=True)),
    CheckConstraint(
        "status IN ('OPEN', 'FIRED', 'EXPIRED', 'CANCELLED')", name="watch_status"
    ),
)

payment_runtime_captures = Table(
    "payment_runtime_captures",
    metadata,
    Column("id", String, primary_key=True),
    Column("mandate_id", ForeignKey("mandates.id"), nullable=False),
    Column("checkout_intent_id", ForeignKey("checkout_intents.id"), nullable=False),
    Column("settlement_reference", String, nullable=False),
    Column("checkout_mandate", Text, nullable=False),
    Column("payment_mandate", Text, nullable=False),
    Column("checkout_receipt", Text, nullable=False),
    Column("payment_receipt", Text, nullable=False),
)


edge_events = Table(
    # What Computer B has to tell Computer A, kept until A says it arrived.
    #
    # B closes a watch with nobody watching; A is the only half that can reach Telegram.
    # A direct call between them would lose the result whenever the network is down at
    # the wrong second — and the thing being lost is "your money moved". So B writes the
    # row in the same transaction that closes the watch, and A marks it delivered only
    # after Telegram has taken the message.
    #
    # `id` is an integer because it is a cursor before it is a name: A polls with
    # `after=<id>`, and the order has to be the order things happened.
    #
    # `payload` crosses to the computer that holds the OpenAI key and ends up in a chat
    # message. It carries a principal, an outcome, a title, a link and an amount — never
    # a payment token, never a signature.
    "edge_events",
    metadata,
    Column("id", Integer, primary_key=True, autoincrement=True),
    Column("principal_id", String, nullable=False),
    Column("event_type", String, nullable=False),
    Column("payload", Text, nullable=False),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("delivered_at", DateTime(timezone=True)),
    Index("ix_edge_events_undelivered", "delivered_at", "id"),
)


CORE_TABLE_NAMES = (
    "mandates",
    "revocation_authorities",
    "revocations",
    "policy_rules",
    "checkout_intents",
    "reservations",
    "authorization_proofs",
    "capture_attempts",
    "idempotency_records",
    "mandate_locks",
    "evidence",
    "audit_events",
    "agent_profiles",
    "vault_tokens",
    "disputes",
    "escalations",
    "agent_watches",
    "payment_runtime_captures",
    "edge_events",
)
