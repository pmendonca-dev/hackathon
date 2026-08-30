"""Record escalations so an approval can be answered later, and proved later still.

Revision ID: 0004_escalations
Revises: 0003_audit_event_sequence
Create Date: 2026-08-29

Before this table `awaiting_human` was a dead end: the core said a purchase needed a
person, and nothing carried that request anywhere. The row holds the exact purchase
that was escalated, so the approval that comes back approves that purchase and not a
larger one someone substituted in the meantime.

`approval_jws` keeps the signed touch itself. It is the answer to a later
"I never authorized this".
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

from aval.infrastructure.sqlite.models import escalations


revision = "0004_escalations"
down_revision = "0003_audit_event_sequence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    if "escalations" not in sa.inspect(op.get_bind()).get_table_names():
        escalations.create(op.get_bind())


def downgrade() -> None:
    if "escalations" in sa.inspect(op.get_bind()).get_table_names():
        escalations.drop(op.get_bind())
