from __future__ import annotations

import json
from pathlib import Path
import subprocess
import sys


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def run_cli(payload: object) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "rail_selector"],
        cwd=PROJECT_ROOT,
        input=json.dumps(payload),
        text=True,
        capture_output=True,
        check=False,
    )


def valid_payload(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "operation_type": "checkout",
        "mandate_allowed_rails": ["ucp_ap2"],
        "amount": "49.90",
        "checkout_context": {
            "checkout_id": "checkout-cli",
            "merchant_id": "merchant-cli",
            "currency": "BRL",
            "ap2_version": "0.2",
        },
        "feature_flags": {"ucp_ap2_enabled": True},
    }
    payload.update(overrides)
    return payload


def test_cli_reads_json_from_stdin_and_emits_selected_result() -> None:
    completed = run_cli(valid_payload())

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert json.loads(completed.stdout) == {
        "checkout_rail": "ucp_ap2",
        "credential_mode": None,
        "reason_code": "UCP_AP2_SELECTED",
        "status": "selected",
        "x402_status": "x402_disabled",
    }


def test_cli_emits_disabled_result_and_nonzero_exit_for_x402() -> None:
    completed = run_cli(
        valid_payload(
            operation_type="x402",
            mandate_allowed_rails=["x402"],
            feature_flags={"x402_enabled": True, "task_12_e2e_green": True},
        )
    )

    assert completed.returncode == 2
    output = json.loads(completed.stdout)
    assert output["reason_code"] == "X402_BLOCKED_TASK12_NOT_GREEN"
    assert output["x402_status"] == "x402_disabled"


def test_cli_malformed_json_fails_closed_without_traceback() -> None:
    completed = subprocess.run(
        [sys.executable, "-m", "rail_selector"],
        cwd=PROJECT_ROOT,
        input="{not-json",
        text=True,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stderr == ""
    output = json.loads(completed.stdout)
    assert output["status"] == "rejected"
    assert output["reason_code"] == "INVALID_REQUEST"


def test_cli_non_object_json_fails_closed() -> None:
    completed = run_cli(["not", "an", "object"])

    assert completed.returncode == 2
    output = json.loads(completed.stdout)
    assert output["reason_code"] == "INVALID_REQUEST"
