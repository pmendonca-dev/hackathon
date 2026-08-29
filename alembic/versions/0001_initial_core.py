"""Create the AVAL authorization-core schema.

Revision ID: 0001_initial_core
Revises:
Create Date: 2026-08-29
"""

from __future__ import annotations

from alembic import op

from aval.infrastructure.sqlite.models import metadata


revision = "0001_initial_core"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    metadata.create_all(op.get_bind())


def downgrade() -> None:
    metadata.drop_all(op.get_bind())
