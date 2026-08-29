from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aval.application.authorization_core import AuthorizationCommand, AuthorizationCore
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import AuthorizationDecision, RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def make_mandate(public_jwk: dict[str, str], *, limit: int = 1_000) -> Mandate:
    return Mandate(
        id="mandate_persisted",
        principal=Principal(id="principal_1", display_name="Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}),
        limit=Money(limit, "BRL", 2),
        expires_at=datetime(2026, 8, 30, tzinfo=UTC),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(
            RevocationAuthority(
                id="authority_1",
                kid="holder-key",
                role=RevocationRole.HOLDER,
                public_jwk=public_jwk,
                allowed_scopes=frozenset({"mandate"}),
            ),
        ),
    )


def command(amount: int = 500) -> AuthorizationCommand:
    return AuthorizationCommand(
        mandate_id="mandate_persisted",
        checkout_id="checkout_1",
        merchant_id="merchant_1",
        total=Money(amount, "BRL", 2),
    )


def test_core_persists_mandates_live_policy_and_signed_revocations(tmp_path):
    engine = create_sqlite_engine(tmp_path / "aval.db")
    metadata.create_all(engine)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    core = AuthorizationCore(clock=lambda: now, engine=engine)
    core.register_mandate(make_mandate(custody.public_jwk("holder-key")))

    reloaded_core = AuthorizationCore(clock=lambda: now, engine=engine)
    assert reloaded_core.evaluate(command()).decision is AuthorizationDecision.AUTHORIZED

    reloaded_core.replace_live_limit("mandate_persisted", Money(400, "BRL", 2))
    assert reloaded_core.evaluate(command()).reason_code == "budget_exceeded"

    revocation = sign_compact_jws(
        {"mandate_id": "mandate_persisted", "scope": "mandate", "reason": "holder_request", "epoch": 2},
        custody,
        "holder-key",
    )
    reloaded_core.submit_signed_revocation(revocation)

    final_core = AuthorizationCore(clock=lambda: now + timedelta(seconds=1), engine=engine)
    result = final_core.evaluate(command())
    assert result.decision is AuthorizationDecision.REJECTED
    assert result.reason_code == "mandate_revoked"
