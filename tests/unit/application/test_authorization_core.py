from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aval.application.authorization_core import (
    AuthorizationCommand,
    AuthorizationCore,
    CaptureCommand,
    SettlementResult,
)
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import AuthorizationDecision, RevocationRole
from aval.domain.money import Money
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


class RecordingSettlementAdapter:
    def __init__(self) -> None:
        self.reservation_statuses: list[str] = []

    def authorize(self, reservation, _proof):
        self.reservation_statuses.append(reservation.status.value)
        return SettlementResult(approved=True, reference="psp_1")


def make_mandate(*, expires_at: datetime | None = None, public_jwk: dict[str, str] | None = None) -> Mandate:
    authority = RevocationAuthority(
        id="authority_1",
        kid="holder-key",
        role=RevocationRole.HOLDER,
        public_jwk=public_jwk or {"kty": "EC", "crv": "P-256", "kid": "holder-key"},
        allowed_scopes=frozenset({"mandate"}),
    )
    return Mandate(
        id="mandate_1",
        principal=Principal(id="principal_1", display_name="Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}),
        limit=Money(10_000, "BRL", 2),
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(authority,),
    )


def command(*, merchant_id: str = "merchant_1", amount: int = 500) -> AuthorizationCommand:
    return AuthorizationCommand(
        mandate_id="mandate_1",
        checkout_id="checkout_1",
        merchant_id=merchant_id,
        total=Money(amount, "BRL", 2),
    )


def test_core_authorizes_an_in_scope_checkout():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate())

    result = core.evaluate(command())

    assert result.decision is AuthorizationDecision.AUTHORIZED


def test_core_escalates_a_checkout_for_a_non_allowed_merchant():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate())

    result = core.evaluate(command(merchant_id="merchant_other"))

    assert result.decision is AuthorizationDecision.AWAITING_HUMAN
    assert result.reason_code == "merchant_out_of_scope"


def test_core_rejects_expired_mandates():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(expires_at=datetime.now(UTC) - timedelta(seconds=1)))
    assert core.evaluate(command()).reason_code == "mandate_expired"


def test_capture_commits_before_calling_settlement_and_replays_idempotently():
    settlement = RecordingSettlementAdapter()
    core = AuthorizationCore(clock=lambda: datetime.now(UTC), settlement_adapter=settlement)
    core.register_mandate(make_mandate())

    first = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_1"))
    replay = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_1"))

    assert first.approved
    assert replay == first
    assert settlement.reservation_statuses == ["COMMITTED"]


def test_revocation_before_capture_blocks_settlement():
    settlement = RecordingSettlementAdapter()
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    core = AuthorizationCore(clock=lambda: datetime.now(UTC), settlement_adapter=settlement)
    core.register_mandate(make_mandate(public_jwk=custody.public_jwk("holder-key")))
    revocation = sign_compact_jws(
        {
            "mandate_id": "mandate_1",
            "scope": "mandate",
            "reason": "holder_request",
            "epoch": 1,
        },
        custody,
        "holder-key",
    )
    core.submit_signed_revocation(revocation)

    result = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_1"))

    assert not result.approved
    assert result.reason_code == "mandate_revoked"
    assert settlement.reservation_statuses == []


def test_revocation_with_an_invalid_signature_is_rejected():
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(public_jwk=custody.public_jwk("holder-key")))
    revocation = sign_compact_jws(
        {"mandate_id": "mandate_1", "scope": "mandate", "reason": "holder_request", "epoch": 1},
        custody,
        "holder-key",
    )

    header, payload, signature = revocation.split(".")
    try:
        core.submit_signed_revocation(f"{header}.{payload}.{signature[:-1]}A")
    except ValueError:
        pass
    else:
        raise AssertionError("unsigned revocation was accepted")

    assert core.evaluate(command()).decision is AuthorizationDecision.AUTHORIZED
