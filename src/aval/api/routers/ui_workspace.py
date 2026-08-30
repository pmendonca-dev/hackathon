from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Response
from pydantic import BaseModel, ConfigDict

from aval.api.routers.ui_sessions import ui_csrf_dependency, ui_principal_dependency
from aval.application.services.ui_operator_revocation import UiOperatorRevocationService
from aval.application.services.ui_projections import UiProjectionError, UiProjectionService
from aval.application.services.ui_sessions import UiPrincipal, UiSessionService


class OperatorRevocationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _raise_projection(error: UiProjectionError) -> None:
    raise HTTPException(status_code=error.status_code, detail={"code": error.code}) from error


def _revocation_status(reason_code: str) -> int:
    if reason_code in {"idempotency_unavailable", "revocation_unavailable"}:
        return 503
    if reason_code == "idempotency_in_flight":
        return 409
    if reason_code == "mandate_not_found":
        return 404
    return 422


def create_ui_workspace_router(
    *,
    sessions: UiSessionService,
    projections: UiProjectionService,
    operator_revocations: UiOperatorRevocationService,
) -> APIRouter:
    router = APIRouter(prefix="/ui-api/v1")
    require_principal = ui_principal_dependency(sessions)
    require_csrf = ui_csrf_dependency(sessions, require_principal)

    @router.get("/workspace")
    def workspace(principal: UiPrincipal = Depends(require_principal)) -> dict[str, object]:
        return projections.workspace(principal)

    @router.get("/mandates/{mandate_id}/audit")
    def audit(mandate_id: str, principal: UiPrincipal = Depends(require_principal)) -> dict[str, object]:
        try:
            return projections.audit(principal, mandate_id)
        except UiProjectionError as error:
            _raise_projection(error)

    @router.get("/mandates/{mandate_id}/dispute")
    def dispute(mandate_id: str, principal: UiPrincipal = Depends(require_principal)) -> dict[str, object]:
        try:
            return projections.dispute(principal, mandate_id)
        except UiProjectionError as error:
            _raise_projection(error)

    @router.post("/mandates/{mandate_id}/revocations", status_code=202)
    def revoke(
        mandate_id: str,
        _: OperatorRevocationInput,
        response: Response,
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
        principal: UiPrincipal = Depends(require_csrf),
    ) -> dict[str, str]:
        if not idempotency_key or not idempotency_key.strip():
            raise HTTPException(status_code=400, detail={"code": "idempotency_key_required"})
        try:
            result = operator_revocations.revoke(principal, mandate_id, idempotency_key)
        except UiProjectionError as error:
            _raise_projection(error)
        if result.reason_code is not None:
            raise HTTPException(
                status_code=_revocation_status(result.reason_code),
                detail={"code": result.reason_code},
            )
        assert result.mandate_id is not None
        if result.replayed:
            response.headers["Idempotent-Replayed"] = "true"
        return {"mandate_id": result.mandate_id, "status": "revoked"}

    return router
