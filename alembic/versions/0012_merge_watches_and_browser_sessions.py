"""Merge the standing-orders and browser-session histories.

Two branches added a revision numbered 0011 on top of 0010_mandate_instrument —
standing orders on one side, the browser-safe UI sessions on the other. Both are
real heads, so `alembic upgrade head` refuses to choose between them. This joins
them; it carries no schema change of its own.

Revision ID: 0012_merge_watches_and_browser_sessions
Revises: 0011_agent_watches, 0011_merge_browser_ui_sessions
"""

from __future__ import annotations


revision = "0012_merge_watches_and_browser_sessions"
down_revision = ("0011_agent_watches", "0011_merge_browser_ui_sessions")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
