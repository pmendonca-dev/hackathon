from __future__ import annotations

from datetime import UTC, datetime
from threading import Event, Thread

from aval.application.authorization_core import AuthorizationCore, CaptureCommand, SettlementResult
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import metadata
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


class BlockingSettlement:
    def __init__(self) -> None:
        self.committed = Event(); self.release = Event(); self.calls = 0

    def authorize(self, reservation, proof):
        assert reservation.status.value == "COMMITTED"
        self.calls += 1; self.committed.set(); self.release.wait(timeout=5)
        return SettlementResult(True, "psp_1")


def test_revocation_after_commit_does_not_cancel_inflight_settlement_but_blocks_next_attempt(tmp_path):
    engine = create_sqlite_engine(tmp_path / "aval.db")
    metadata.create_all(engine)
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService(); custody.generate_es256("holder")
    mandate = Mandate("m1", Principal("p1", "Marta"), frozenset({"merchant"}), frozenset({"travel"}), Money(1_000, "BRL", 2), datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0}, (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, custody.public_jwk("holder"), frozenset({"mandate"})),))
    AuthorizationCore(clock=lambda: now, engine=engine).register_mandate(mandate)
    settlement = BlockingSettlement()
    capture_core = AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement)
    capture = CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "travel", "first")
    thread = Thread(target=capture_core.capture, args=(capture,)); thread.start()
    assert settlement.committed.wait(timeout=5)
    revocation = sign_compact_jws({"mandate_id": "m1", "scope": "mandate", "reason": "holder", "epoch": 1}, custody, "holder")
    AuthorizationCore(clock=lambda: now, engine=engine).submit_signed_revocation(revocation)
    settlement.release.set(); thread.join(timeout=5)

    next_result = AuthorizationCore(clock=lambda: now, engine=engine, settlement_adapter=settlement).capture(CaptureCommand("m1", "checkout_2", "merchant", Money(100, "BRL", 2), "travel", "next"))
    assert settlement.calls == 1
    assert next_result.reason_code == "mandate_revoked"
