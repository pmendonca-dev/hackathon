"""Persist payment-runtime receipts and vault amount scale.

Revision ID: 0004_payment_runtime
Revises: 0003_core_retention_and_mandate_locks
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0004_payment_runtime"
down_revision = "0003_core_retention_and_mandate_locks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    existing_tables = set(sa.inspect(bind).get_table_names())
    if "vault_tokens" in existing_tables:
        op.add_column("vault_tokens", sa.Column("scale", sa.Integer(), nullable=False, server_default="2"))
    op.create_table(
        "payment_runtime_captures",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("checkout_intent_id", sa.String(), sa.ForeignKey("checkout_intents.id"), nullable=False),
        sa.Column("settlement_reference", sa.String(), nullable=False),
        sa.Column("checkout_receipt", sa.Text(), nullable=False),
        sa.Column("payment_receipt", sa.Text(), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("payment_runtime_captures")
    with op.batch_alter_table("vault_tokens", recreate="always") as batch_op:
        batch_op.drop_column("scale")
