"""Add the mandate purchase scope, the hard ceiling and the dispute record.

Revision ID: 0004_mandate_scope_and_disputes
Revises: 0003_core_retention_and_mandate_locks
Create Date: 2026-08-29

`0001_initial_core` builds the schema from the live metadata, so a database created
after this change already carries the new columns and table. This revision is written
to be idempotent for exactly that reason: it inspects before it alters, so it is a
no-op on a fresh database and a real migration on one stamped at 0001.

`allowed_categories` arrives with an empty-list default because SQLite cannot add a
NOT NULL column without one. A mandate written before this revision therefore declares
no purchase scope, and the `Mandate` invariant refuses to load it. That is deliberate:
a mandate that never said what may be bought must not authorize anything. Re-register
any such mandate rather than backfilling a category into it.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from aval.infrastructure.sqlite.models import disputes


revision = "0004_mandate_scope_and_disputes"
down_revision = "0003_core_retention_and_mandate_locks"
branch_labels = None
depends_on = None


def _mandate_columns() -> set[str]:
    return {column["name"] for column in sa.inspect(op.get_bind()).get_columns("mandates")}


def upgrade() -> None:
    bind = op.get_bind()
    columns = _mandate_columns()
    if "allowed_categories" not in columns:
        op.add_column(
            "mandates",
            sa.Column("allowed_categories", sa.Text(), nullable=False, server_default="[]"),
        )
    if "ceiling_minor_units" not in columns:
        op.add_column("mandates", sa.Column("ceiling_minor_units", sa.Integer(), nullable=True))
    if "disputes" not in set(sa.inspect(bind).get_table_names()):
        disputes.create(bind)


def downgrade() -> None:
    bind = op.get_bind()
    if "disputes" in set(sa.inspect(bind).get_table_names()):
        disputes.drop(bind)
    columns = _mandate_columns()
    if "ceiling_minor_units" in columns:
        op.drop_column("mandates", "ceiling_minor_units")
    if "allowed_categories" in columns:
        op.drop_column("mandates", "allowed_categories")
