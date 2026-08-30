"""Add frequency conditions to mandates and a commit stamp to reservations.

A mandate may now carry "up to N uses in a rolling window of S seconds" — the case's
"up to 3 times a month". Counting those uses needs to know *when* money was actually
held, which the reservation row did not record, so `committed_at` lands here too.

The stamp is deliberately nullable and is cleared when a reservation is released: a
purchase the processor refused must not consume one of the buyer's allowed uses.

Revision ID: 0009_mandate_usage_frequency
Revises: 0008_capture_ap2_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_mandate_usage_frequency"
down_revision = "0008_capture_ap2_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "mandates" in tables:
        existing = {column["name"] for column in inspector.get_columns("mandates")}
        with op.batch_alter_table("mandates") as batch_op:
            if "max_uses" not in existing:
                batch_op.add_column(sa.Column("max_uses", sa.Integer(), nullable=True))
            if "usage_window_seconds" not in existing:
                batch_op.add_column(
                    sa.Column("usage_window_seconds", sa.Integer(), nullable=True)
                )

    if "reservations" in tables:
        existing = {column["name"] for column in inspector.get_columns("reservations")}
        if "committed_at" not in existing:
            with op.batch_alter_table("reservations") as batch_op:
                batch_op.add_column(
                    sa.Column("committed_at", sa.DateTime(timezone=True), nullable=True)
                )


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "reservations" in tables:
        with op.batch_alter_table("reservations") as batch_op:
            batch_op.drop_column("committed_at")
    if "mandates" in tables:
        with op.batch_alter_table("mandates") as batch_op:
            batch_op.drop_column("usage_window_seconds")
            batch_op.drop_column("max_uses")
