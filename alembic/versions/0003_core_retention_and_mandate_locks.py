"""Add durable idempotency retention and the shared mandate lock resource.

Revision ID: 0003_core_retention_and_mandate_locks
Revises: 0002_authorization_hardening
Create Date: 2026-08-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_core_retention_and_mandate_locks"
down_revision = "0002_authorization_hardening"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("idempotency_records", sa.Column("retained_until", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE idempotency_records SET retained_until = datetime('now', '+1 day')")
    with op.batch_alter_table("idempotency_records", recreate="always") as batch_op:
        batch_op.alter_column("retained_until", nullable=False)
    op.create_table(
        "mandate_locks",
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), primary_key=True),
        sa.Column("touched_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("mandate_locks")
    with op.batch_alter_table("idempotency_records", recreate="always") as batch_op:
        batch_op.drop_column("retained_until")
