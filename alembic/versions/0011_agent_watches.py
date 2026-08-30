"""Standing orders: what the agent keeps trying to buy after the conversation ends.

The case's own scenario is one — *buy me a flight to Córdoba if it drops below $150,
valid until the end of the month* — and every surface until now could only answer a
request. This is the row that lets the agent act while nobody is typing.

It stores the sentence rather than a parsed target, so the row can never disagree with
what the person actually asked for. It carries no authority: firing means asking the
core, which answers exactly as it answers a human.

Revision ID: 0011_agent_watches
Revises: 0010_mandate_instrument
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0011_agent_watches"
down_revision = "0010_mandate_instrument"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    if "agent_watches" in set(sa.inspect(bind).get_table_names()):
        return
    op.create_table(
        "agent_watches",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("mandate_id", sa.String(), sa.ForeignKey("mandates.id"), nullable=False),
        sa.Column("instruction", sa.Text(), nullable=False),
        sa.Column("status", sa.String(), nullable=False),
        sa.Column("outcome", sa.String()),
        sa.Column("settlement_reference", sa.String()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint(
            "status IN ('OPEN', 'FIRED', 'EXPIRED', 'CANCELLED')", name="watch_status"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    if "agent_watches" in set(sa.inspect(bind).get_table_names()):
        op.drop_table("agent_watches")
