"""Repair a head-stamped SQLite mandates table missing its frequency column.

Some durable demo databases were marked at the previous Alembic head even though
their historical frequency migration had not added ``mandates.max_uses``.  Alembic
therefore had no pending revision to run, while the current mandate repository
rightly expects the column.  This forward-only repair makes that historical drift
safe without changing any released migration.

Revision ID: 0013_repair_legacy_mandate_frequency
Revises: 0012_merge_watches_and_browser_sessions
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0013_repair_legacy_mandate_frequency"
down_revision = "0012_merge_watches_and_browser_sessions"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mandates" not in set(inspector.get_table_names()):
        return
    columns = {column["name"] for column in inspector.get_columns("mandates")}
    if "max_uses" in columns:
        return

    op.add_column("mandates", sa.Column("max_uses", sa.Integer(), nullable=True))
    # A row written before frequency limits means Mandate.usage_limit is None.  There
    # is no valid usage count to infer, so NULL is the domain's explicit no-limit value.
    bind.execute(sa.text("UPDATE mandates SET max_uses = NULL"))


def downgrade() -> None:
    # This repair is intentionally forward-only.  Removing the column would recreate
    # the head-stamped legacy schema that the demonstration runtime cannot boot.
    pass
