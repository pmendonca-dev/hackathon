from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from aval.application.authorization_core import AuthorizationCore, CaptureCommand
from aval.domain.entities import Mandate, PaymentInstrument, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import mandate_locks, metadata
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def test_capture_and_signed_revocation_touch_the_same_durable_mandate_lock(tmp_path):
    """Removing either lock acquisition splits the pre-commit race boundary."""
    now = datetime(2026, 8, 29, tzinfo=UTC)
    engine = create_sqlite_engine(tmp_path / "mandate-lock.db")
    metadata.create_all(engine)
    custody = KeyCustodyService()
    custody.generate_es256("holder")
    mandate = Mandate(
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), frozenset({"travel"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, custody.public_jwk("holder"), frozenset({"mandate"})),), instrument=PaymentInstrument("vt_test_instrument", "•••• 4242"),
    )
    capture_core = AuthorizationCore(clock=lambda: now, engine=engine)
    capture_core.register_mandate(mandate)

    assert capture_core.capture(CaptureCommand("m1", "checkout", "merchant", Money(500, "BRL", 2), "travel", "first", instrument_id="vt_test_instrument")).approved

    later = now + timedelta(seconds=1)
    token = sign_compact_jws(
        {"mandate_id": "m1", "scope": "mandate", "reason": "holder", "epoch": 1}, custody, "holder"
    )
    AuthorizationCore(clock=lambda: later, engine=engine).submit_signed_revocation(token)

    with engine.connect() as connection:
        touched_at = connection.execute(
            select(mandate_locks.c.touched_at).where(mandate_locks.c.mandate_id == "m1")
        ).scalar_one()

    assert touched_at.replace(tzinfo=UTC) == later
