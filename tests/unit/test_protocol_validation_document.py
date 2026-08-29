from __future__ import annotations

from pathlib import Path


def test_protocol_validation_record_covers_required_external_contracts():
    document = Path("docs/protocol-validation.md").read_text(encoding="utf-8")

    for required_reference in (
        "UCP",
        "AP2",
        "ACP",
        "x402",
        "RFC 9421",
        "RFC 9530",
        "RFC 8785",
        "RFC 7515",
        "RFC 7518",
        "RFC 8941",
    ):
        assert required_reference in document
