"""Run the public, authenticated non-x402 demo smoke scenarios."""

from __future__ import annotations

import sys

import pytest


SCENARIOS = (
    "tests/integration/e2e/test_browser_safe_bff.py::"
    "test_ui_audit_requires_session_but_agent_audit_still_requires_rfc9421",
    "tests/integration/e2e/test_browser_safe_bff.py::"
    "test_ui_operator_revocation_requires_csrf_and_creates_audit_event",
    "tests/integration/e2e/test_browser_safe_bff.py::"
    "test_browser_projection_redacts_pan_token_proof_and_raw_jws",
    "tests/integration/e2e/test_browser_safe_bff.py::"
    "test_unsigned_browser_request_cannot_operate_an_agent_endpoint",
    "tests/integration/e2e/test_task_12_live_runtime.py::"
    "test_delegation_and_capture_without_rfc9421_are_rejected",
    "tests/integration/e2e/test_task_12_live_runtime.py::"
    "test_out_of_scope_merchant_and_total_escalate_without_a_token",
    "tests/integration/e2e/test_task_12_live_runtime.py::"
    "test_impostor_invalid_signature_and_raw_body_tampering_are_rejected",
    "tests/integration/e2e/test_task_12_live_runtime.py::"
    "test_valid_purchase_exposes_receipts_audit_and_dispute_without_secrets",
    "tests/integration/e2e/test_task_12_live_runtime.py::"
    "test_post_commit_revocation_blocks_future_purchase_without_rewriting_settlement",
)


def main() -> int:
    print("AVAL browser BFF and live HTTP demo smoke (x402 intentionally excluded)")
    result = pytest.main([*SCENARIOS, "-q"])
    if result == pytest.ExitCode.OK:
        print("PASS: browser BFF, authenticated purchase, denial, evidence, and revocation smoke")
    else:
        print("FAIL: at least one real runtime API scenario did not satisfy its contract")
    return int(result)


if __name__ == "__main__":
    sys.exit(main())
