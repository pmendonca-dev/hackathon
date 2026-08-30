from __future__ import annotations

from test_audit_timeline import _build_service


def test_unknown_payment_receipt_reference_is_inconclusive() -> None:
    service, _ = _build_service(unknown_payment_reference=True)

    verdict = service.reconstruct("mandate_1")

    assert verdict.status == "INCONCLUSIVE"
    assert verdict.reason_code == "payment_receipt_reference_unknown"
    assert "não corresponde" in verdict.human_summary
