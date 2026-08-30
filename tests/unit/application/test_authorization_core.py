from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta

from aval.application.authorization_core import (
    AuthorizationCommand,
    AuthorizationCore,
    CaptureCommand,
    SettlementResult,
)
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import AuthorizationDecision, MandateStatus, RevocationRole
from aval.domain.money import Money
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService
from aval.security.authorization_proof import AuthorizationProofService


class RecordingSettlementAdapter:
    def __init__(self) -> None:
        self.reservation_statuses: list[str] = []
        self.proofs: list[str] = []

    def authorize(self, reservation, proof):
        self.reservation_statuses.append(reservation.status.value)
        self.proofs.append(proof)
        return SettlementResult(approved=True, reference="psp_1")


def make_mandate(
    *,
    expires_at: datetime | None = None,
    public_jwk: dict[str, str] | None = None,
    allowed_categories: frozenset[str] | None = None,
    ceiling: Money | None = None,
) -> Mandate:
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
        allowed_categories=allowed_categories or frozenset({"travel"}),
        limit=Money(10_000, "BRL", 2),
        expires_at=expires_at or datetime.now(UTC) + timedelta(hours=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(authority,),
        ceiling=ceiling,
    )


def command(
    *, merchant_id: str = "merchant_1", amount: int = 500, category: str = "travel"
) -> AuthorizationCommand:
    return AuthorizationCommand(
        mandate_id="mandate_1",
        checkout_id="checkout_1",
        merchant_id=merchant_id,
        total=Money(amount, "BRL", 2),
        category=category,
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


def test_core_escalates_a_checkout_outside_the_allowed_categories():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(allowed_categories=frozenset({"travel"})))

    result = core.evaluate(command(category="lodging"))

    assert result.decision is AuthorizationDecision.AWAITING_HUMAN
    assert result.reason_code == "category_not_allowed"


def test_core_rejects_amounts_above_the_mandate_ceiling_without_escalating():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(ceiling=Money(50_000, "BRL", 2)))

    above = core.evaluate(command(amount=90_000))
    within_ceiling_over_budget = core.evaluate(command(amount=20_000))

    assert above.decision is AuthorizationDecision.REJECTED
    assert above.reason_code == "mandate_ceiling"
    assert within_ceiling_over_budget.decision is AuthorizationDecision.AWAITING_HUMAN
    assert within_ceiling_over_budget.reason_code == "budget_exceeded"


def test_a_live_limit_change_never_raises_the_mandate_ceiling():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(ceiling=Money(50_000, "BRL", 2)))

    core.replace_live_limit("mandate_1", Money(100_000, "BRL", 2))

    result = core.evaluate(command(amount=90_000))
    assert result.decision is AuthorizationDecision.REJECTED
    assert result.reason_code == "mandate_ceiling"


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


def test_capture_issues_a_signed_authorization_proof_only_after_commit():
    now = datetime(2026, 8, 29, tzinfo=UTC)
    custody = KeyCustodyService()
    custody.generate_es256("aval-proof")
    settlement = RecordingSettlementAdapter()
    proofs = AuthorizationProofService(clock=lambda: now, custody=custody, kid="aval-proof")
    core = AuthorizationCore(
        clock=lambda: now,
        settlement_adapter=settlement,
        authorization_proof_issuer=proofs,
    )
    core.register_mandate(make_mandate(expires_at=now + timedelta(hours=1)))

    result = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_with_proof"))

    assert result.approved
    assert settlement.reservation_statuses == ["COMMITTED"]
    assert settlement.proofs[0].count(".") == 2


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
    tampered_payload = ("A" if payload[0] != "A" else "B") + payload[1:]
    try:
        core.submit_signed_revocation(f"{header}.{tampered_payload}.{signature}")
    except ValueError:
        pass
    else:
        raise AssertionError("unsigned revocation was accepted")

    assert core.evaluate(command()).decision is AuthorizationDecision.AUTHORIZED


def test_the_first_live_limit_change_advances_the_policy_version():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate())

    core.replace_live_limit("mandate_1", Money(5_000, "BRL", 2))

    registered = core.mandate("mandate_1")
    assert registered is not None
    assert registered.policy_version == 2


def test_a_registered_mandate_starts_at_policy_version_one():
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate())

    registered = core.mandate("mandate_1")
    assert registered is not None
    assert registered.policy_version == 1


class DecliningSettlementAdapter:
    def authorize(self, reservation, proof):
        return SettlementResult(approved=False)


def test_a_declined_purchase_can_be_attempted_again():
    """A decline frees the purchase. Holding its transaction slot forever would mean a
    customer whose card was refused could never retry the very same basket."""
    core = AuthorizationCore(
        clock=lambda: datetime.now(UTC), settlement_adapter=DecliningSettlementAdapter()
    )
    core.register_mandate(make_mandate())

    declined = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_declined"))
    retried = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_retry"))

    assert not declined.approved
    assert retried.reason_code != "transaction_already_captured"


def test_a_settled_purchase_still_blocks_an_identical_second_charge():
    core = AuthorizationCore(
        clock=lambda: datetime.now(UTC), settlement_adapter=RecordingSettlementAdapter()
    )
    core.register_mandate(make_mandate())

    core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_first"))
    duplicate = core.capture(CaptureCommand(**command().__dict__, idempotency_key="idem_second"))

    assert duplicate.reason_code == "transaction_already_captured"


def make_second_mandate(public_jwk):
    """A second mandate for the same person, registering the same holder key."""
    return Mandate(
        id="mandate_2",
        principal=Principal(id="principal_1", display_name="Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}),
        allowed_categories=frozenset({"travel"}),
        limit=Money(10_000, "BRL", 2),
        expires_at=datetime.now(UTC) + timedelta(hours=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_2", "epoch": 0},
        authorities=(
            RevocationAuthority(
                id="authority_2",
                kid="holder-key",
                role=RevocationRole.HOLDER,
                public_jwk=public_jwk,
                allowed_scopes=frozenset({"mandate"}),
            ),
        ),
    )


def test_a_holder_can_revoke_the_second_mandate_that_shares_their_key():
    """One person, two mandates, one key. Revoking the newer one must work: a person
    who renews a mandate keeps the same phone and the same key."""
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    jwk = custody.public_jwk("holder-key")
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(public_jwk=jwk))
    core.register_mandate(make_second_mandate(jwk))

    core.submit_signed_revocation(
        sign_compact_jws(
            {"mandate_id": "mandate_2", "scope": "mandate", "reason": "holder", "epoch": 1},
            custody,
            "holder-key",
        )
    )

    second = core.mandate("mandate_2")
    first = core.mandate("mandate_1")
    assert second is not None and second.status is MandateStatus.REVOKED
    # And revoking one must never revoke the other.
    assert first is not None and first.status is MandateStatus.ACTIVE


def test_revoking_one_mandate_leaves_the_sibling_spendable():
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    jwk = custody.public_jwk("holder-key")
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    core.register_mandate(make_mandate(public_jwk=jwk))
    core.register_mandate(make_second_mandate(jwk))

    core.submit_signed_revocation(
        sign_compact_jws(
            {"mandate_id": "mandate_1", "scope": "mandate", "reason": "holder", "epoch": 1},
            custody,
            "holder-key",
        )
    )

    assert core.evaluate(command()).reason_code == "mandate_revoked"
    sibling = replace(command(), mandate_id="mandate_2")
    assert core.evaluate(sibling).decision is AuthorizationDecision.AUTHORIZED


def test_registering_an_existing_mandate_does_not_extend_its_validity():
    """Re-seeding on start must not keep a mandate alive forever."""
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    original = make_mandate(expires_at=datetime.now(UTC) + timedelta(hours=1))
    core.register_mandate(original)

    core.register_mandate(replace(original, expires_at=datetime.now(UTC) + timedelta(days=30)))

    stored = core.mandate("mandate_1")
    assert stored is not None
    assert stored.expires_at == original.expires_at


def test_registering_an_existing_mandate_cannot_undo_a_revocation():
    custody = KeyCustodyService()
    custody.generate_es256("holder-key")
    core = AuthorizationCore(clock=lambda: datetime.now(UTC))
    mandate = make_mandate(public_jwk=custody.public_jwk("holder-key"))
    core.register_mandate(mandate)
    core.submit_signed_revocation(
        sign_compact_jws(
            {"mandate_id": "mandate_1", "scope": "mandate", "reason": "holder", "epoch": 1},
            custody,
            "holder-key",
        )
    )

    core.register_mandate(mandate)

    assert core.evaluate(command()).reason_code == "mandate_revoked"
