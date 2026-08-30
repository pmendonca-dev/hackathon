from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from aval.application.authorization_core import AuthorizationCore
from aval.application.services.ui_projections import UiProjectionError
from aval.application.services.ui_sessions import UiPrincipal
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


OPERATOR_REVOCATION_KID = "operator-key"
OPERATOR_REVOCATION_SCOPE = "browser_operator_mandate_revocation"


@dataclass(frozen=True)
class UiOperatorRevocationResult:
    mandate_id: str | None
    reason_code: str | None
    replayed: bool


class UiOperatorRevocationService:
    def __init__(self, *, core: AuthorizationCore, custody: KeyCustodyService) -> None:
        self._core = core
        self._custody = custody

    def revoke(
        self, principal: UiPrincipal, mandate_id: str, idempotency_key: str
    ) -> UiOperatorRevocationResult:
        if principal.role != "operator":
            raise UiProjectionError(403, "ui_role_not_authorized")
        if not self._custody.has(OPERATOR_REVOCATION_KID):
            return UiOperatorRevocationResult(None, "revocation_unavailable", False)
        mandate = self._core.mandate(mandate_id)
        if mandate is None:
            return UiOperatorRevocationResult(None, "mandate_not_found", False)
        payload = {
            "mandate_id": mandate.id,
            "scope": "mandate",
            "reason": "operator_browser_request",
            "epoch": int(mandate.revocation_metadata.get("epoch", 0)) + 1,
        }
        token = sign_compact_jws(payload, self._custody, OPERATOR_REVOCATION_KID)
        fingerprint = hashlib.sha256(
            json.dumps({"mandate_id": mandate_id, "action": "operator_revocation"}, sort_keys=True).encode()
        ).hexdigest()
        result = self._core.submit_signed_revocation_idempotent(
            mandate_id=mandate_id,
            token=token,
            idempotency_key=idempotency_key,
            authenticated_kid=OPERATOR_REVOCATION_KID,
            idempotency_scope=OPERATOR_REVOCATION_SCOPE,
            idempotency_fingerprint=fingerprint,
        )
        return UiOperatorRevocationResult(result.mandate_id, result.reason_code, result.replayed)
