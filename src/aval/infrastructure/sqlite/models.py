from __future__ import annotations

from sqlalchemy import (
    CheckConstraint,
    Column,
    DateTime,
    ForeignKey,
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
    Column("status", String, nullable=False),
    Column("currency", String(3), nullable=False),
    Column("scale", Integer, nullable=False),
    Column("limit_minor_units", Integer, nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False),
    Column("policy_version", Integer, nullable=False),
    Column("revocation_epoch", Integer, nullable=False, default=0),
    Column("revocation_metadata", Text, nullable=False),
    CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="mandate_status"),
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
    Column("expires_at", DateTime(timezone=True), nullable=False),
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
)
