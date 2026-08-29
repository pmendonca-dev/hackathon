from __future__ import annotations

from datetime import UTC, datetime

from aval.application.authorization_core import CaptureCommand
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.application.authorization_core import AuthorizationCore, SettlementResult
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.security.key_custody import KeyCustodyService


class CountingSettlement:
    def __init__(self) -> None:
        self.calls = 0

    def authorize(self, reservation, proof):
        assert reservation.status.value == "COMMITTED"
        assert proof
        self.calls += 1
        return SettlementResult(True, "psp_1")


def make_mandate(public_jwk: dict[str, str]) -> Mandate:
    return Mandate(
        id="mandate_persisted", principal=Principal("principal_1", "Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}), allowed_categories=frozenset({"travel"}),
        limit=Money(1_000, "BRL", 2),
        expires_at=datetime(2026, 8, 30, tzinfo=UTC), policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(RevocationAuthority("authority_1", "holder-key", RevocationRole.HOLDER, public_jwk, frozenset({"mandate"})),),
    )


def capture_command(*, key: str, amount: int = 500) -> CaptureCommand:
    return CaptureCommand("mandate_persisted", "checkout_1", "merchant_1", Money(amount, "BRL", 2), "travel", key)


def test_capture_idempotency_is_durable_and_rejects_changed_bodies(tmp_path):
    engine = create_sqlite_engine(tmp_path / "aval.db")
    metadata.create_all(engine)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    settlement = CountingSettlement()
    issuer = AuthorizationCore(clock=lambda: now, engine=engine)
    issuer.register_mandate(make_mandate(custody.public_jwk("holder-key")))

    first_core = AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement)
    first = first_core.capture(capture_command(key="idem_1"))
    replay = AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement).capture(capture_command(key="idem_1"))
    changed_body = AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement).capture(capture_command(key="idem_1", amount=600))

    assert first.approved
    assert replay == first
    assert changed_body.reason_code == "idempotency_key_reused"
    assert settlement.calls == 1
