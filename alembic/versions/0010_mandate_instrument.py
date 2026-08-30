"""Name the payment method inside the mandate.

The case asks the human to authorize *what may be bought, the limits, the validity and
the payment method* without ever exposing the raw card to the agent. The first three
lived here already; this adds the fourth.

Two columns, set together or both null. `instrument_token` is the scoped credential the
agent presents at capture — the PAN is tokenized at the edge and never reaches this
table, this agent or this ledger. `instrument_label` is the four digits a person needs
to recognise which card they authorized, and it cannot pay for anything.

Nullable on purpose: a mandate that names no instrument accepts any, which is what
every mandate written before this migration meant.

Revision ID: 0010_mandate_instrument
Revises: 0009_mandate_usage_frequency
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0010_mandate_instrument"
down_revision = "0009_mandate_usage_frequency"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "mandates" not in set(inspector.get_table_names()):
        return
    existing = {column["name"] for column in inspector.get_columns("mandates")}
    with op.batch_alter_table("mandates") as batch_op:
        if "instrument_token" not in existing:
            batch_op.add_column(sa.Column("instrument_token", sa.String(), nullable=True))
        if "instrument_label" not in existing:
            batch_op.add_column(sa.Column("instrument_label", sa.String(), nullable=True))


def downgrade() -> None:
    bind = op.get_bind()
    if "mandates" not in set(sa.inspect(bind).get_table_names()):
        return
    with op.batch_alter_table("mandates") as batch_op:
        batch_op.drop_column("instrument_label")
        batch_op.drop_column("instrument_token")
