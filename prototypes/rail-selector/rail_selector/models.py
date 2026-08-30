from __future__ import annotations

from dataclasses import asdict, dataclass
import json
from typing import Mapping


@dataclass(frozen=True, slots=True)
class RailSelectionRequest:
    """Inputs required by the pure rail-selection interface.

    Values remain deliberately untrusted. ``select_rail`` validates them and
    returns a fail-closed result instead of relying on constructor exceptions.
    """

    operation_type: object
    mandate_allowed_rails: object
    amount: object
    checkout_context: object
    feature_flags: object


@dataclass(frozen=True, slots=True)
class RailSelectionResult:
    status: str
    checkout_rail: str | None
    credential_mode: str | None
    x402_status: str
    reason_code: str

    @classmethod
    def selected(
        cls,
        *,
        reason_code: str,
        credential_mode: str | None = None,
    ) -> RailSelectionResult:
        return cls(
            status="selected",
            checkout_rail="ucp_ap2",
            credential_mode=credential_mode,
            x402_status="x402_disabled",
            reason_code=reason_code,
        )

    @classmethod
    def rejected(cls, reason_code: str) -> RailSelectionResult:
        return cls(
            status="rejected",
            checkout_rail=None,
            credential_mode=None,
            x402_status="x402_disabled",
            reason_code=reason_code,
        )

    @classmethod
    def x402_disabled(cls) -> RailSelectionResult:
        return cls(
            status="disabled",
            checkout_rail=None,
            credential_mode=None,
            x402_status="x402_disabled",
            reason_code="X402_BLOCKED_TASK12_NOT_GREEN",
        )

    def to_mapping(self) -> Mapping[str, str | None]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_mapping(), sort_keys=True, separators=(",", ":"))
