from __future__ import annotations

import os
from collections.abc import Callable

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, ConfigDict

from aval.application.services.ui_sessions import (
    IssuedUiSession,
    UiPrincipal,
    UiSessionError,
    UiSessionService,
)


SESSION_COOKIE_NAME = "aval_ui_session"
CSRF_HEADER_NAME = "X-AVAL-CSRF"


class LoginInput(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    credential: str


def ui_local_http_enabled() -> bool:
    """The sole opt-out for a localhost-only HTTP demonstration."""
    return os.environ.get("AVAL_UI_LOCAL_HTTP", "").strip().lower() == "true"


def ui_principal_dependency(service: UiSessionService) -> Callable[[Request], UiPrincipal]:
    def require_session(request: Request) -> UiPrincipal:
        try:
            return service.authenticate(request.cookies.get(SESSION_COOKIE_NAME))
        except UiSessionError as error:
            raise HTTPException(status_code=401, detail={"code": error.code}) from error

    return require_session


def ui_csrf_dependency(
    service: UiSessionService, principal_dependency: Callable[[Request], UiPrincipal]
) -> Callable[..., UiPrincipal]:
    def require_csrf(
        csrf_value: str | None = Header(default=None, alias=CSRF_HEADER_NAME),
        principal: UiPrincipal = Depends(principal_dependency),
    ) -> UiPrincipal:
        try:
            service.validate_csrf(principal, csrf_value)
        except UiSessionError as error:
            raise HTTPException(status_code=403, detail={"code": error.code}) from error
        return principal

    return require_csrf


def create_ui_session_router(
    service: UiSessionService, *, secure_cookie: bool | None = None
) -> APIRouter:
    router = APIRouter(prefix="/ui-api/v1")
    secure = not ui_local_http_enabled() if secure_cookie is None else secure_cookie
    require_principal = ui_principal_dependency(service)
    require_csrf = ui_csrf_dependency(service, require_principal)

    @router.post("/session/login")
    def login(request: LoginInput, response: Response) -> dict[str, object]:
        try:
            issued: IssuedUiSession = service.login(request.role, request.credential)
        except UiSessionError as error:
            raise HTTPException(status_code=401, detail={"code": error.code}) from error
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=issued.cookie_value,
            max_age=service.ttl_seconds,
            httponly=True,
            samesite="strict",
            secure=secure,
            path="/",
        )
        return {
            "role": issued.role,
            "csrf_token": issued.csrf_token,
            "expires_at": issued.expires_at.isoformat(),
        }

    @router.post("/session/logout", status_code=204)
    def logout(
        response: Response,
        principal: UiPrincipal = Depends(require_csrf),
    ) -> None:
        service.logout(principal)
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            httponly=True,
            samesite="strict",
            secure=secure,
            path="/",
        )

    return router
