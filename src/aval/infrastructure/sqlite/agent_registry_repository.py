from __future__ import annotations

import json

from sqlalchemy import Connection, Engine, select, update

from aval.domain.entities import AgentIdentity
from aval.infrastructure.sqlite.models import agent_profiles


class SqliteAgentRegistryRepository:
    """Persistence implementation behind the local, pre-approved UCP profile registry."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def put(self, identity: AgentIdentity) -> None:
        profile = {"keys": [dict(identity.public_jwk)]}
        values = {
            "profile_json": json.dumps(profile, separators=(",", ":")),
            "trusted": int(identity.trusted),
        }
        existing = self._connection.execute(
            select(agent_profiles.c.id).where(agent_profiles.c.profile_url == identity.profile_url)
        ).scalar_one_or_none()
        if existing is None:
            self._connection.execute(
                agent_profiles.insert().values(id=identity.id, profile_url=identity.profile_url, **values)
            )
            return
        self._connection.execute(
            update(agent_profiles).where(agent_profiles.c.profile_url == identity.profile_url).values(**values)
        )

    def resolve(self, profile_url: str) -> AgentIdentity | None:
        row = self._connection.execute(
            select(agent_profiles).where(agent_profiles.c.profile_url == profile_url)
        ).mappings().one_or_none()
        if row is None:
            return None
        profile = json.loads(row["profile_json"])
        keys = profile.get("keys")
        if not isinstance(keys, list) or len(keys) != 1 or not isinstance(keys[0], dict):
            return None
        return AgentIdentity(
            id=row["id"], profile_url=row["profile_url"], public_jwk=keys[0], trusted=bool(row["trusted"])
        )


class SqliteTrustedAgentRegistry:
    """Read-only UCP registry facade; adapters receive this port, never a database session."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    def resolve(self, profile_url: str) -> AgentIdentity | None:
        with self._engine.connect() as connection:
            return SqliteAgentRegistryRepository(connection).resolve(profile_url)
