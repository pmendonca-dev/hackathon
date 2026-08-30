"""Persist server-side browser BFF sessions.

Revision ID: 0009_browser_ui_sessions
Revises: 0008_capture_ap2_evidence
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "0009_browser_ui_sessions"
down_revision = "0008_capture_ap2_evidence"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "browser_ui_sessions",
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("token_hash", sa.String(length=64), nullable=False, unique=True),
        sa.Column("csrf_hash", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(), nullable=False),
        sa.Column("merchant_id", sa.String(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "ix_browser_ui_sessions_active_lookup",
        "browser_ui_sessions",
        ["token_hash", "expires_at", "revoked_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_browser_ui_sessions_active_lookup", table_name="browser_ui_sessions")
    op.drop_table("browser_ui_sessions")
