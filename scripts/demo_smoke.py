"""Run the public, authenticated non-x402 demo smoke scenarios."""

from __future__ import annotations

import sys

import pytest


SCENARIOS = (
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
    print("AVAL live HTTP demo smoke (x402 intentionally excluded)")
    result = pytest.main([*SCENARIOS, "-q"])
    if result == pytest.ExitCode.OK:
        print("PASS: authenticated HTTP purchase, denial, evidence, and revocation smoke")
    else:
        print("FAIL: at least one real runtime API scenario did not satisfy its contract")
    return int(result)


if __name__ == "__main__":
    sys.exit(main())
