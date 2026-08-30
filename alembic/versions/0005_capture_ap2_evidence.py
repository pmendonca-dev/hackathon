"""Persist the AP2 evidence actually validated before capture.

Revision ID: 0005_capture_ap2_evidence
Revises: 0004_payment_runtime
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_capture_ap2_evidence"
down_revision = "0004_payment_runtime"
branch_labels = None
depends_on = None

def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if {"payment_runtime_captures", "checkout_intents"} <= tables:
        with op.batch_alter_table("payment_runtime_captures", recreate="always") as batch_op:
            batch_op.add_column(sa.Column("checkout_mandate", sa.Text(), nullable=False, server_default=""))
            batch_op.add_column(sa.Column("payment_mandate", sa.Text(), nullable=False, server_default=""))

def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if {"payment_runtime_captures", "checkout_intents"} <= tables:
        with op.batch_alter_table("payment_runtime_captures", recreate="always") as batch_op:
            batch_op.drop_column("payment_mandate")
            batch_op.drop_column("checkout_mandate")
