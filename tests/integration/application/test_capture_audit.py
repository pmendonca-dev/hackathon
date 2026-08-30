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
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), frozenset({"travel"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, {"kty": "EC", "crv": "P-256", "x": "x", "y": "y"}, frozenset({"mandate"})),),
    )
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC), engine=engine)
    core.register_mandate(mandate)

    core.capture(CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "travel", "idem"))

    with engine.connect() as connection:
        events = connection.execute(select(audit_events)).mappings().all()
    # The trail is now a chain that opens when the mandate is registered, so the capture
    # is the last link rather than the only one. What this test guards is unchanged: the
    # core writes it, in the same transaction, and nobody has to trust the edge for it.
    recorded = [(event["mandate_id"], event["event_type"]) for event in events]
    assert recorded[-1] == ("m1", "purchase_settled")
    assert [event["mandate_id"] for event in events] == ["m1"] * len(events)
    settlement = [event for event in events if event["event_type"] == "purchase_settled"]
    assert len(settlement) == 1
