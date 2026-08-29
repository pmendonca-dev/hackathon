from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from threading import Barrier

from aval.application.authorization_core import AuthorizationCore, CaptureCommand, SettlementResult
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.security.key_custody import KeyCustodyService


class Settlement:
    def __init__(self) -> None:
        self.calls = 0

    def authorize(self, reservation, proof):
        self.calls += 1
        return SettlementResult(True, "psp_1")


def mandate(jwk: dict[str, str]) -> Mandate:
    return Mandate("m1", Principal("p1", "Marta"), frozenset({"merchant"}), Money(1_000, "BRL", 2), datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0}, (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, jwk, frozenset({"mandate"})),))


def command(key: str) -> CaptureCommand:
    return CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), key)


def test_two_concurrent_captures_have_exactly_one_settlement(tmp_path):
    engine = create_sqlite_engine(tmp_path / "aval.db")
    metadata.create_all(engine)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService(); custody.generate_es256("holder")
    AuthorizationCore(clock=lambda: now, engine=engine).register_mandate(mandate(custody.public_jwk("holder")))
    settlement = Settlement()
    barrier = Barrier(2)

    def capture(key: str):
        barrier.wait()
        return AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement).capture(command(key))

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = list(executor.map(capture, ("one", "two")))

    assert sum(result.approved for result in outcomes) == 1
    assert settlement.calls == 1
