"""Add durable authorization-core constraints.

Revision ID: 0002_authorization_hardening
Revises: 0001_initial_core
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0002_authorization_hardening"
down_revision = "0001_initial_core"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("mandates", recreate="always") as batch_op:
        batch_op.add_column(
            sa.Column("principal_display_name", sa.String(), nullable=False, server_default="Unknown principal")
        )
        batch_op.add_column(
            sa.Column("allowed_merchant_ids", sa.Text(), nullable=False, server_default="[]")
        )
    with op.batch_alter_table("reservations", recreate="always") as batch_op:
        batch_op.create_unique_constraint(
            "reservation_mandate_transaction", ["mandate_id", "transaction_hash"]
        )
    with op.batch_alter_table("idempotency_records", recreate="always") as batch_op:
        batch_op.create_unique_constraint("idempotency_scope_key", ["scope", "idempotency_key"])


def downgrade() -> None:
    with op.batch_alter_table("idempotency_records", recreate="always") as batch_op:
        batch_op.drop_constraint("idempotency_scope_key", type_="unique")
    with op.batch_alter_table("reservations", recreate="always") as batch_op:
        batch_op.drop_constraint("reservation_mandate_transaction", type_="unique")
    with op.batch_alter_table("mandates", recreate="always") as batch_op:
        batch_op.drop_column("allowed_merchant_ids")
        batch_op.drop_column("principal_display_name")
