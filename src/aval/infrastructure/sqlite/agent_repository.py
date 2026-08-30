"""Agent profiles: who is allowed to speak to the system, and with which key.

An agent identity is not a mandate and grants nothing on its own. It answers only
*who is calling*; what that caller may buy is decided afterwards, by the mandate.
"""

from __future__ import annotations

import json

from sqlalchemy import Connection, select, update

from aval.domain.entities import AgentIdentity
from aval.infrastructure.sqlite.models import agent_profiles


class SqliteAgentProfileRepository:
    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def put(self, identity: AgentIdentity) -> None:
        profile = json.dumps(
            {"name": identity.id, "keys": [dict(identity.public_jwk)]}, sort_keys=True
        )
        values = {
            "profile_url": identity.profile_url,
            "profile_json": profile,
            "trusted": 1 if identity.trusted else 0,
        }
        existing = self._connection.execute(
            select(agent_profiles.c.id).where(agent_profiles.c.id == identity.id)
        ).scalar()
        if existing:
            self._connection.execute(
                update(agent_profiles).where(agent_profiles.c.id == identity.id).values(**values)
            )
            return
        self._connection.execute(agent_profiles.insert().values(id=identity.id, **values))

    def find_by_kid(self, kid: str) -> AgentIdentity | None:
        """Profiles are few in this demo, so the scan is honest and cheap. The key id in
        the JWK is what a signature announces, so that is what we match on."""
        rows = self._connection.execute(select(agent_profiles)).mappings().all()
        for row in rows:
            profile = json.loads(row["profile_json"])
            for key in profile.get("keys", []):
                if key.get("kid") == kid:
                    return AgentIdentity(
                        id=row["id"],
                        profile_url=row["profile_url"],
                        public_jwk=key,
                        trusted=bool(row["trusted"]),
                    )
        return None
