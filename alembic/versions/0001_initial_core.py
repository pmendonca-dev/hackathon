"""Create the original AVAL authorization-core schema.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0001_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mandates",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("principal_id", sa.String(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("scale", sa.Integer(), nullable=False),
        sa.Column("limit_minor_units", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("revocation_epoch", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("revocation_metadata", sa.Text(), nullable=False),
        sa.CheckConstraint("status IN ('ACTIVE', 'REVOKED', 'EXPIRED')", name="mandate_status"),
    )
    op.create_table(
        "revocation_authorities",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("kid", sa.String(), nullable=False),
        sa.Column("public_jwk", sa.Text(), nullable=False),
        sa.Column("allowed_scope", sa.String(), nullable=False),
    )
    op.create_table(
        "revocations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("authority_id", sa.String(), sa.ForeignKey("revocation_authorities.id"), nullable=False),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("reason", sa.String(), nullable=False),
        sa.Column("epoch", sa.Integer(), nullable=False),
        sa.Column("signed_jws", sa.Text(), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "policy_rules",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("rule_json", sa.Text(), nullable=False),
        sa.Column("active", sa.Integer(), nullable=False, server_default="1"),
    )
    op.create_table(
        "checkout_intents",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("merchant_id", sa.String(), nullable=False),
        sa.Column("total_minor_units", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("scale", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("canonical_payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "reservations",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("checkout_intent_id", sa.String(), sa.ForeignKey("checkout_intents.id"), nullable=False),
        sa.Column("amount_minor_units", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("transaction_hash", sa.String()),
        sa.CheckConstraint("status IN ('PENDING', 'COMMITTED', 'SETTLED', 'RELEASED')", name="reservation_status"),
    )
    op.create_table(
        "authorization_proofs",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("reservation_id", sa.String(), sa.ForeignKey("reservations.id"), nullable=False),
        sa.Column("jti", sa.String(), nullable=False, unique=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signed_proof", sa.Text(), nullable=False),
    )
    op.create_table(
        "capture_attempts",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("reservation_id", sa.String(), sa.ForeignKey("reservations.id"), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False, unique=True),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("settlement_reference", sa.String()),
    )
    op.create_table(
        "idempotency_records",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("scope", sa.String(), nullable=False),
        sa.Column("idempotency_key", sa.String(), nullable=False),
        sa.Column("request_hash", sa.String(), nullable=False),
        sa.Column("state", sa.String(), nullable=False),
        sa.Column("response_body", sa.Text()),
        sa.CheckConstraint("state IN ('IN_FLIGHT', 'COMPLETED')", name="idempotency_state"),
    )
    op.create_table(
        "evidence",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("kind", sa.String(), nullable=False),
        sa.Column("origin", sa.String(), nullable=False),
        sa.Column("sha256", sa.String(), nullable=False),
        sa.Column("payload", sa.Text(), nullable=False),
    )
    op.create_table(
        "audit_events",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("event_type", sa.String(), nullable=False),
        sa.Column("human_summary", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.String(), sa.ForeignKey("evidence.id")),
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "agent_profiles",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("profile_url", sa.String(), nullable=False, unique=True),
        sa.Column("profile_json", sa.Text(), nullable=False),
        sa.Column("trusted", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "vault_tokens",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("checkout_intent_id", sa.String(), sa.ForeignKey("checkout_intents.id"), nullable=False),
        sa.Column("merchant_id", sa.String(), nullable=False),
        sa.Column("max_amount_minor_units", sa.Integer(), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    for table in (
        "vault_tokens", "agent_profiles", "audit_events", "evidence", "idempotency_records",
        "capture_attempts", "authorization_proofs", "reservations", "checkout_intents",
        "policy_rules", "revocations", "revocation_authorities", "mandates",
    ):
        op.drop_table(table)
