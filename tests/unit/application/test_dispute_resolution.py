from __future__ import annotations

from datetime import UTC, datetime, timedelta

from aval.application.authorization_core import (
    AuthorizationCore,
    CaptureCommand,
    SettlementResult,
)
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import DisputeStatus, RevocationRole
from aval.domain.money import Money
from aval.security.authorization_proof import AuthorizationProofService
from aval.security.key_custody import KeyCustodyService


NOW = datetime(2026, 8, 29, tzinfo=UTC)


class ApprovingSettlementAdapter:
    def authorize(self, reservation, proof):
        return SettlementResult(approved=True, reference="psp_1")


def mandate() -> Mandate:
    return Mandate(
        id="mandate_1",
        principal=Principal(id="principal_1", display_name="Marta"),
        allowed_merchant_ids=frozenset({"merchant_1"}),
        allowed_categories=frozenset({"travel"}),
        limit=Money(10_000, "BRL", 2),
        expires_at=NOW + timedelta(hours=1),
        policy_version=1,
        revocation_metadata={"revocation_id": "rev_1", "epoch": 0},
        authorities=(
            RevocationAuthority(
                id="authority_1",
                kid="holder-key",
                role=RevocationRole.HOLDER,
                public_jwk={"kty": "EC", "crv": "P-256", "kid": "holder-key"},
                allowed_scopes=frozenset({"mandate"}),
            ),
        ),
    )


def capture_command(*, key: str, terms_hash: str | None = None) -> CaptureCommand:
    return CaptureCommand(
        mandate_id="mandate_1",
        checkout_id="checkout_1",
        merchant_id="merchant_1",
        total=Money(500, "BRL", 2),
        category="travel",
        idempotency_key=key,
        terms_hash=terms_hash,
    )


def test_a_disputed_purchase_backed_by_a_proof_resolves_against_the_claim():
    custody = KeyCustodyService()
    custody.generate_es256("aval-proof")
    core = AuthorizationCore(
        clock=lambda: NOW,
        settlement_adapter=ApprovingSettlementAdapter(),
        authorization_proof_issuer=AuthorizationProofService(
            clock=lambda: NOW, custody=custody, kid="aval-proof"
        ),
    )
    core.register_mandate(mandate())
    capture = core.capture(capture_command(key="idem_dispute", terms_hash="terms_1"))

    dispute = core.open_dispute(
        reservation_id=capture.reservation.id, reason="I never authorized this"
    )
    resolved = core.resolve_dispute(dispute.id)

    assert dispute.status is DisputeStatus.OPEN
    assert resolved.status is DisputeStatus.MANDATE_HELD
    assert "terms_1" in resolved.resolution


def test_a_disputed_purchase_without_a_proof_resolves_for_the_claimant():
    core = AuthorizationCore(clock=lambda: NOW, settlement_adapter=ApprovingSettlementAdapter())
    core.register_mandate(mandate())
    capture = core.capture(capture_command(key="idem_no_proof"))

    opened = core.open_dispute(
        reservation_id=capture.reservation.id, reason="unrecognised charge"
    )
    resolved = core.resolve_dispute(opened.id)

    assert resolved.status is DisputeStatus.MANDATE_FAILED
    assert opened.mandate_id == "mandate_1"
