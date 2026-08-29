from __future__ import annotations

from datetime import UTC, datetime

from aval.application.authorization_core import AuthorizationCommand, AuthorizationCore
from aval.application.authorization_core import CaptureCommand
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import AuthorizationDecision, RevocationRole
from aval.domain.money import Money
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def test_budget_zero_revocation_blocks_spend_without_revoking_the_mandate():
    custody = KeyCustodyService()
    custody.generate_es256("holder")
    mandate = Mandate(
        "m1", Principal("p1", "Marta"), frozenset({"merchant"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, custody.public_jwk("holder"), frozenset({"budget:zero", "mandate"})),),
    )
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC))
    core.register_mandate(mandate)
    core.submit_signed_revocation(sign_compact_jws(
        {"mandate_id": "m1", "scope": "budget:zero", "reason": "holder", "epoch": 1}, custody, "holder"
    ))

    result = core.evaluate(AuthorizationCommand("m1", "checkout", "merchant", Money(1, "BRL", 2)))

    assert result.decision is AuthorizationDecision.AWAITING_HUMAN
    assert result.reason_code == "budget_revoked"


def test_instrument_revocation_blocks_only_the_revoked_instrument():
    custody = KeyCustodyService()
    custody.generate_es256("holder")
    mandate = Mandate(
        "m2", Principal("p1", "Marta"), frozenset({"merchant"}), Money(1_000, "BRL", 2),
        datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r2", "epoch": 0},
        (RevocationAuthority("a1", "holder", RevocationRole.HOLDER, custody.public_jwk("holder"), frozenset({"instrument:vt_1", "mandate"})),),
    )
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC))
    core.register_mandate(mandate)
    core.submit_signed_revocation(sign_compact_jws(
        {"mandate_id": "m2", "scope": "instrument:vt_1", "reason": "holder", "epoch": 1}, custody, "holder"
    ))

    result = core.capture(CaptureCommand("m2", "checkout", "merchant", Money(1, "BRL", 2), "idem", "vt_1"))

    assert result.approved is False
    assert result.reason_code == "instrument_revoked"
