from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import TextIO

from .models import RailSelectionRequest, RailSelectionResult
from .selector import select_rail


_REQUEST_FIELDS = frozenset(
    {
        "operation_type",
        "mandate_allowed_rails",
        "amount",
        "checkout_context",
        "feature_flags",
    }
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the deterministic, non-integrated rail selector."
    )
    parser.add_argument(
        "input",
        nargs="?",
        default="-",
        help="JSON request file, or '-' to read stdin (default).",
    )
    args = parser.parse_args(argv)

    result = _run(args.input, sys.stdin)
    sys.stdout.write(result.to_json() + "\n")
    return 0 if result.status == "selected" else 2


def _run(input_path: str, stdin: TextIO) -> RailSelectionResult:
    try:
        raw = stdin.read() if input_path == "-" else Path(input_path).read_text("utf-8")
        payload = json.loads(raw)
    except (OSError, UnicodeError, json.JSONDecodeError):
        return RailSelectionResult.rejected("INVALID_REQUEST")

    request = _request_from_payload(payload)
    if request is None:
        return RailSelectionResult.rejected("INVALID_REQUEST")
    return select_rail(request)


def _request_from_payload(payload: object) -> RailSelectionRequest | None:
    if not isinstance(payload, dict) or set(payload) != _REQUEST_FIELDS:
        return None
    return RailSelectionRequest(
        operation_type=payload["operation_type"],
        mandate_allowed_rails=payload["mandate_allowed_rails"],
        amount=payload["amount"],
        checkout_context=payload["checkout_context"],
        feature_flags=payload["feature_flags"],
    )
