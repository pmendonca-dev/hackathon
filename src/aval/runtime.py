"""Composition root.

Every collaborator the running system needs is built here, once, and handed to
the HTTP layer. Nothing below this line reaches for a global.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from sqlalchemy import Engine, create_engine
from sqlalchemy.pool import StaticPool

from aval.application.authorization_core import AuthorizationCore
from aval.domain.entities import AgentIdentity
from aval.infrastructure.psp import DemoPspAdapter, PspControl
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository
from aval.infrastructure.sqlite.models import metadata
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.merchant.catalog import MERCHANTS
from aval.merchant.offers import MerchantOfferService
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.clock import ClockService
from aval.security.http_signature import ReplayGuard
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService

PROOF_KID = "aval-proof-k1"
DEMO_AGENT_ID = "agent_aval_demo"
DEMO_AGENT_KID = "agent-demo-k1"
DEMO_AGENT_PROFILE_URL = "https://agents.aval.local/agent_aval_demo"


def resolve_operator_token() -> str:
    """Return only an explicit local operator token; missing configuration is closed."""
    return os.environ.get("AVAL_OPERATOR_TOKEN", "").strip()


@dataclass(frozen=True)
class AvalRuntime:
    engine: Engine
    clock: ClockService
    custody: KeyCustodyService
    proofs: AuthorizationProofService
    psp: DemoPspAdapter
    psp_control: PspControl
    core: AuthorizationCore
    replay_guard: ReplayGuard
    merchant_custody: KeyCustodyService
    offers: MerchantOfferService
    spent_offer_nonces: ReplayGuard
    agent_custody: KeyCustodyService
    agent_kid: str
    operator_token: str


def build_runtime(
    *,
    database_path: Path | None = None,
    now_provider: Callable[[], datetime] | None = None,
    operator_token: str | None = None,
    custody: KeyCustodyService | None = None,
    extra_key_ids: tuple[str, ...] = (),
) -> AvalRuntime:
    """Wire the system. Without a path the database is in memory, which is what the
    tests want and what a judge resetting the demo gets."""
    clock = ClockService(now_provider=now_provider)
    engine = (
        create_sqlite_engine(database_path)
        if database_path is not None
        else create_engine(
            "sqlite+pysqlite://",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
    )
    # A caller may hand in custody it already published: a verifier that trusted a
    # key yesterday must still find that key after a restart.
    # The core refuses to create a schema on an engine it was handed: migrations own the
    # database, not the application. The composition root is where that schema is put in
    # place, which is what main's own entrypoint did before this was factored out.
    metadata.create_all(engine)
    custody = custody or KeyCustodyService()
    for key_id in (PROOF_KID, *extra_key_ids):
        if not custody.has(key_id):
            custody.generate_es256(key_id)
    # One-use proofs, remembered in the database rather than in this process: a proof
    # spent before a restart must still be spent after one.
    def consume_proof_jti(jti: str) -> bool:
        return run_in_write_transaction(
            engine,
            lambda connection: SqliteIdempotencyRepository(connection).consume_once(
                "authorization_proof", jti
            ),
        )

    proofs = AuthorizationProofService(
        clock=clock.now, custody=custody, kid=PROOF_KID, consume_jti=consume_proof_jti
    )
    # Kept in its own custody: the seller signs offers, AVAL signs authorizations,
    # and neither can produce the other side of the exchange.
    merchant_custody = KeyCustodyService()
    for merchant_kid in MERCHANTS.values():
        merchant_custody.generate_es256(merchant_kid)
    psp_control = PspControl()

    def verify_proof_for_settlement(proof: str, reservation) -> None:
        """Check the proof the core issued, without spending it.

        Consumption belongs to the merchant, which presents the token once to claim the
        goods. A processor that burned the jti here would settle the payment and leave
        the merchant unable to verify the very sale it just took part in.
        """
        claims = verify_compact_jws(proof, custody.verifying_key(PROOF_KID))
        if (
            claims.get("reservation_id") != reservation.id
            or claims.get("transaction_hash") != reservation.transaction_hash
        ):
            raise ValueError("authorization proof does not bind this reservation")

    psp = DemoPspAdapter(
        lambda: psp_control.mode, proof_verifier=verify_proof_for_settlement
    )
    core = AuthorizationCore(
        clock=clock.now,
        engine=engine,
        settlement_adapter=psp,
        authorization_proof_issuer=proofs,
    )
    # The agent gets a key of its own. Agent identity and human identity are separate
    # things in this system, and this is where that separation starts.
    agent_custody = KeyCustodyService()
    agent_custody.generate_es256(DEMO_AGENT_KID)
    core.register_agent(
        AgentIdentity(
            id=DEMO_AGENT_ID,
            profile_url=DEMO_AGENT_PROFILE_URL,
            public_jwk=agent_custody.public_jwk(DEMO_AGENT_KID),
            trusted=True,
        )
    )
    return AvalRuntime(
        engine=engine,
        clock=clock,
        custody=custody,
        proofs=proofs,
        psp=psp,
        psp_control=psp_control,
        core=core,
        replay_guard=ReplayGuard(),
        merchant_custody=merchant_custody,
        offers=MerchantOfferService(clock=clock.now, custody=merchant_custody),
        spent_offer_nonces=ReplayGuard(retain_seconds=24 * 3600),
        agent_custody=agent_custody,
        agent_kid=DEMO_AGENT_KID,
        operator_token=operator_token or resolve_operator_token(),
    )
