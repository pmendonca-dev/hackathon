"""Server entrypoint — one app carrying both halves of the system.

    uvicorn aval.main:app --reload

Two lanes built against the same core meet here:

- the **protocol ingress** (UCP discovery and checkout, AP2 mandates and merchant
  authorization), mounted from `aval.api.routers`;
- the **authorization surfaces** (mandates, authorize, capture, escalations, ledger,
  merchant offers, the agent and the operator controls), mounted from `aval.api.app`.

Neither reimplements a decision. Both call `AuthorizationCore`, which stays the only
thing in the system that decides authority.

The database is a file by default so a restart does not erase the demo. Set
`AVAL_DATABASE_PATH=:memory:` for a throwaway instance — which is also what a judge
gets when the team resets between runs.

The operator surfaces (`/agents`, `/admin/psp`, `/reconcile`) need a token. Set
`AVAL_OPERATOR_TOKEN`, or let one be minted and read it off the startup line: a default
deployment starts closed rather than open.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI

from aval.adapters.ap2.mandates import ClosedCheckoutMandateVerifier
from aval.adapters.ap2.merchant_authorization import (
    MerchantAuthorizationSigner,
    MerchantAuthorizationVerifier,
)
from aval.adapters.ucp.http_signatures import Rfc9421Verifier
from aval.api.app import create_app as create_authorization_app
from aval.api.middleware.raw_body import RawBodyMiddleware
from aval.api.routers.ucp_checkout import create_ucp_checkout_router
from aval.api.routers.ucp_discovery import create_ucp_discovery_router
from aval.application.services.checkout import CheckoutService
from aval.domain.entities import AgentIdentity, Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.agent_registry_repository import (
    SqliteAgentRegistryRepository,
    SqliteTrustedAgentRegistry,
)
from aval.infrastructure.sqlite.checkout_repository import SqliteCheckoutRepository
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.runtime import AvalRuntime, build_runtime
from aval.security.key_custody import KeyCustodyService

__all__ = ["app", "create_app", "database_path", "PROTOCOL_KEY_IDS"]

# The protocol lane signs and verifies with these four roles. They live in the runtime's
# custody so one process has one set of keys, whichever door a request arrives through.
PROTOCOL_KEY_IDS = ("merchant-key", "agent-key", "issuer-key", "holder-key")

SEED_MANDATE_ID = "mandate_01"
SEED_AGENT_ID = "agent_01"


def _now() -> datetime:
    return datetime.now(UTC)


def database_path() -> Path | None:
    configured = os.environ.get("AVAL_DATABASE_PATH", "var/aval.db").strip()
    if configured.lower() in ("", ":memory:"):
        return None
    return Path(configured)


def _seed_protocol_fixtures(runtime: AvalRuntime, clock: Callable[[], datetime]) -> None:
    """The mandate and agent the protocol lane expects to find.

    Registration is idempotent in the core, so restarting against the same file re-reads
    them instead of duplicating them.
    """
    custody = runtime.custody
    runtime.core.register_mandate(
        Mandate(
            id=SEED_MANDATE_ID,
            principal=Principal("principal_01", "Marta"),
            allowed_merchant_ids=frozenset({"merchant_01"}),
            # A mandate must say what may be bought. The protocol fixture buys travel.
            allowed_categories=frozenset({"travel"}),
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
        id=SEED_AGENT_ID,
        profile_url="https://agent.aval.local/.well-known/ucp",
        public_jwk=custody.public_jwk("agent-key"),
        trusted=True,
    )
    # Two registries, one identity: the protocol lane reads through its own repository,
    # the authorization edge through `agent_for_kid`. Writing both keeps a single agent
    # recognisable at either door.
    run_in_write_transaction(
        runtime.engine, lambda connection: SqliteAgentRegistryRepository(connection).put(identity)
    )
    runtime.core.register_agent(identity)


def _mount_protocol_lane(app: FastAPI, runtime: AvalRuntime, clock: Callable[[], datetime]) -> None:
    custody = runtime.custody
    checkout_service = CheckoutService(
        core=runtime.core,
        store=SqliteCheckoutRepository(runtime.engine),
        merchant_authorization=MerchantAuthorizationSigner(custody=custody, key_id="merchant-key"),
        merchant_authorization_verifier=MerchantAuthorizationVerifier(
            custody.public_jwk("merchant-key")
        ),
        mandate_verifier=ClosedCheckoutMandateVerifier(
            issuer_jwk=custody.public_jwk("issuer-key"),
            holder_jwk=custody.public_jwk("holder-key"),
            clock=clock,
        ),
        clock=clock,
    )
    # RFC 9421 over UCP needs the unparsed bytes, which FastAPI would otherwise consume.
    app.add_middleware(RawBodyMiddleware)
    app.include_router(create_ucp_discovery_router(custody=custody, key_id="merchant-key"))
    app.include_router(
        create_ucp_checkout_router(
            checkout_service,
            verifier=Rfc9421Verifier(SqliteTrustedAgentRegistry(runtime.engine)),
        )
    )


def create_app(
    *,
    database_path: Path | None = None,
    clock: Callable[[], datetime] = _now,
    custody: KeyCustodyService | None = None,
) -> FastAPI:
    """Build the whole system: authorization surfaces plus protocol ingress.

    `custody` is accepted so a caller can restart against the same database and keep the
    keys it published — a verifier that trusted a key yesterday must still find it today.
    """
    runtime = build_runtime(
        database_path=database_path or Path(".aval") / "runtime.sqlite3",
        now_provider=clock,
        custody=custody,
        extra_key_ids=PROTOCOL_KEY_IDS,
    )
    app = create_authorization_app(runtime)
    _seed_protocol_fixtures(runtime, clock)
    _mount_protocol_lane(app, runtime, clock)
    return app


_runtime = build_runtime(database_path=database_path(), extra_key_ids=PROTOCOL_KEY_IDS)
app = create_authorization_app(_runtime)
_seed_protocol_fixtures(_runtime, _runtime.clock.now)
_mount_protocol_lane(app, _runtime, _runtime.clock.now)

if not os.environ.get("AVAL_OPERATOR_TOKEN", "").strip():
    print(f"[aval] operator token for this process: {_runtime.operator_token}")
