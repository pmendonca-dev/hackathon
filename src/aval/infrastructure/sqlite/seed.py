from __future__ import annotations

from sqlalchemy import Engine, insert

from aval.infrastructure.sqlite.models import agent_profiles
from aval.infrastructure.sqlite.transaction import run_in_write_transaction


def seed_demo_data(engine: Engine) -> None:
    """Insert the stable local identity used by the repeatable demo."""

    def insert_profile(connection) -> None:
        connection.execute(
            insert(agent_profiles)
            .prefix_with("OR IGNORE")
            .values(
                id="agent_demo",
                profile_url="https://agent.aval.local/.well-known/ucp",
                profile_json='{"keys":[],"name":"AVAL Demo Agent"}',
                trusted=1,
            )
        )

    run_in_write_transaction(engine, insert_profile)
