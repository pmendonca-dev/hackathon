"""Merge the published browser-session and mandate-instrument histories.

Revision ID: 0011_merge_browser_ui_sessions
Revises: 0010_mandate_instrument, 0009_browser_ui_sessions
"""

from __future__ import annotations


revision = "0011_merge_browser_ui_sessions"
down_revision = ("0010_mandate_instrument", "0009_browser_ui_sessions")
branch_labels = None
depends_on = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
