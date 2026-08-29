from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select

from aval.application.authorization_core import AuthorizationCore, CaptureCommand
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import audit_events, metadata


def test_capture_appends_an_audit_event_in_the_core(tmp_path):
    engine = create_sqlite_engine(tmp_path / "audit.db")
    metadata.create_all(engine)
    mandate = Mandate(
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}, frozenset({"mandate"})),),
    )
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC), engine=engine)
    core.register_mandate(mandate)

    core.capture(CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "idem"))

    with engine.connect() as connection:
        events = connection.execute(select(audit_events)).mappings().all()
    assert [(event["mandate_id"], event["event_type"]) for event in events] == [("m1", "capture.committed")]
