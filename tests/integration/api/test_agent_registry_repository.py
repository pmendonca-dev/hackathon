from __future__ import annotations

from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from aval.domain.entities import AgentIdentity
from aval.infrastructure.sqlite.agent_registry_repository import SqliteAgentRegistryRepository
from aval.infrastructure.sqlite.models import metadata


def test_local_registry_resolves_only_the_persisted_trusted_profile() -> None:
    """Catches a registry that treats a request-supplied profile as trusted."""
    engine = create_engine("sqlite+pysqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    metadata.create_all(engine)
    identity = AgentIdentity(
        id="agent_1",
        profile_url="https://agent.example/.well-known/ucp",
        public_jwk={"kid": "agent-key", "kty": "EC", "crv": "P-256", "x": "x", "y": "y"},
        trusted=True,
    )

    with engine.begin() as connection:
        registry = SqliteAgentRegistryRepository(connection)
        registry.put(identity)

        assert registry.resolve(identity.profile_url) == identity
        assert registry.resolve("https://impostor.example/.well-known/ucp") is None
