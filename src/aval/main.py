from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Callable

from fastapi import FastAPI

from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import MerchantAuthorizationSigner, MerchantAuthorizationVerifier
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.middleware.raw_body import RawBodyMiddleware
from aval.api.routers.ucp_checkout import create_ucp_checkout_router
from aval.api.routers.ucp_discovery import create_ucp_discovery_router
from aval.application.authorization_core import AuthorizationCore
from aval.application.services.checkout import CheckoutService
from aval.domain.entities import AgentIdentity, Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.agent_registry_repository import (
    SqliteAgentRegistryRepository,
    SqliteTrustedAgentRegistry,
)
from aval.infrastructure.sqlite.checkout_repository import SqliteCheckoutRepository
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.security.key_custody import KeyCustodyService


@dataclass(frozen=True)
class AvalRuntime:
    custody: KeyCustodyService


def _now() -> datetime:
    return datetime.now(UTC)


def _seed_runtime(*, core: AuthorizationCore, custody: KeyCustodyService, engine, clock: Callable[[], datetime]) -> None:
    core.register_mandate(
        Mandate(
            id="mandate_01",
            principal=Principal("principal_01", "Marta"),
            allowed_merchant_ids=frozenset({"merchant_01"}),
            limit=Money(10_000, "BRL", 2),
            expires_at=clock() + timedelta(days=1),
            policy_version=1,
            revocation_metadata={"revocation_id": "revocation_01", "epoch": 0},
            authorities=(
                RevocationAuthority(
                    id="authority_01",
                    kid="holder-key",
                    role=RevocationRole.HOLDER,
                    public_jwk=custody.public_jwk("holder-key"),
                    allowed_scopes=frozenset({"mandate"}),
                ),
            ),
        )
    )
    identity = AgentIdentity(
        id="agent_01",
        profile_url="https://agent.aval.local/.well-known/ucp",
        public_jwk=custody.public_jwk("agent-key"),
        trusted=True,
    )
    run_in_write_transaction(engine, lambda connection: SqliteAgentRegistryRepository(connection).put(identity))


def create_app(
    *,
    database_path: Path | None = None,
    clock: Callable[[], datetime] = _now,
    custody: KeyCustodyService | None = None,
) -> FastAPI:
    database_path = database_path or Path(".aval") / "runtime.sqlite3"
    engine = create_sqlite_engine(database_path)
    metadata.create_all(engine)
    if custody is None:
        custody = KeyCustodyService()
        for key_id in ("merchant-key", "agent-key", "issuer-key", "holder-key"):
            custody.generate_es256(key_id)
    core = AuthorizationCore(clock=clock, engine=engine)
    _seed_runtime(core=core, custody=custody, engine=engine, clock=clock)
    checkout_service = CheckoutService(
        core=core,
        store=SqliteCheckoutRepository(engine),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(custody.public_jwk("merchant-key")),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"),
            holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
        clock=clock,
    )
    app = FastAPI(title="AVAL")
    app.state.runtime = AvalRuntime(custody=custody)
    app.add_middleware(RawBodyMiddleware)
    app.include_router(create_ucp_discovery_router(custody=custody, key_id="merchant-key"))
    app.include_router(
        create_ucp_checkout_router(
            checkout_service,
            verifier=Rfc9421Verifier(SqliteTrustedAgentRegistry(engine)),
        )
    )

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
