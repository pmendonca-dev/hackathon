from __future__ import annotations

from datetime import UTC, datetime

from aval.application.authorization_core import AuthorizationCore, CaptureCommand
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.idempotency_repository import SqliteIdempotencyRepository


def test_capture_fails_closed_when_idempotency_storage_is_unavailable(monkeypatch):
    mandate = Mandate(
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), frozenset({"travel"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}, frozenset({"mandate"})),),
    )
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC))
    core.register_mandate(mandate)
    monkeypatch.setattr(SqliteIdempotencyRepository, "get_or_claim", lambda *_args: (_ for _ in ()).throw(OSError("down")))

    result = core.capture(CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "travel", "idem"))

    assert result.approved is False
    assert result.reason_code == "idempotency_unavailable"
