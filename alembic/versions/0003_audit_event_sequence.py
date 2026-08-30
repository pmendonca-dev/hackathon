"""Give every audit event its place in the mandate's hash chain.

Revision ID: 0003_audit_event_sequence
Revises: 0002_mandate_scope_and_disputes
Create Date: 2026-08-29

The trail is verified by walking it in order, and `occurred_at` cannot carry that
order: two events written inside one transaction share a timestamp. `sequence` is
the mandate-local position the chain is built on.

Like 0002, this revision inspects before it alters, so it is a no-op on a database
created from the live metadata and a real migration on one stamped at 0002. Rows
written before this revision get sequence 0, which fails chain verification on
purpose: a trail whose order was never recorded must not claim to be intact.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0003_audit_event_sequence"
down_revision = "0002_mandate_scope_and_disputes"
branch_labels = None
depends_on = None


def _columns(table: str) -> set[str]:
    inspector = sa.inspect(op.get_bind())
    return {column["name"] for column in inspector.get_columns(table)}


def upgrade() -> None:
    if "sequence" not in _columns("audit_events"):
        op.add_column(
            "audit_events",
            sa.Column("sequence", sa.Integer(), nullable=False, server_default="0"),
        )


def downgrade() -> None:
    if "sequence" in _columns("audit_events"):
        op.drop_column("audit_events", "sequence")
