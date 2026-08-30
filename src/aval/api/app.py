"""The HTTP surface.

Two rules hold everywhere below: the edge validates form and authenticity, and the
core decides authority. If a rule about money or revocation ever appears in this
package, it is in the wrong place.
"""

from __future__ import annotations

import os
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from aval.api.dependencies import runtime_of
from aval.api.errors import ApiError, api_error_response
from aval.api.routes import (
    agent,
    agents,
    authorization,
    escalations,
    ledger,
    mandates,
    merchant,
    operations,
    telegram_chats,
)
from aval.api.routes.demo_tamper import create_demo_tamper_router, tampering_enabled
from aval.domain.errors import DomainError
from aval.infrastructure.psp import PspUnreachable
from aval.runtime import AvalRuntime, build_runtime


DEFAULT_ORIGINS = (
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
)


def allowed_origins() -> list[str]:
    """Vite and Next defaults, plus whatever `AVAL_ALLOWED_ORIGINS` names."""
    configured = os.environ.get("AVAL_ALLOWED_ORIGINS", "").strip()
    extra = [origin.strip() for origin in configured.split(",") if origin.strip()]
    return [*DEFAULT_ORIGINS, *extra]


def create_app(runtime: AvalRuntime | None = None, *, lifespan=None) -> FastAPI:
    """Build the authorization surfaces.

    `lifespan` is accepted so the composition root can attach background work — the
    standing-order scheduler — without this module learning what that work is. It has to
    arrive at construction: FastAPI reads it when the app is built, not afterwards.
    """
    app = FastAPI(title="AVAL", lifespan=lifespan)
    app.state.runtime = runtime if runtime is not None else build_runtime()

    # The bot and the operator console are served from other origins during the demo,
    # so cross-origin requests are allowed — but from named origins only. A wildcard
    # would let any page the operator happens to have open drive this API, and several
    # routes here change what an agent is allowed to spend.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=allowed_origins(),
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.middleware("http")
    async def time_decisions(request: Request, call_next):
        """Time the two routes that decide, and leave every other path alone.

        Wall clock and not the demo clock: this measures how long the code took, which
        a judge advancing the mandate's validity must not be able to change.
        """
        started = perf_counter()
        try:
            return await call_next(request)
        finally:
            app.state.runtime.metrics.timed(
                request.url.path, (perf_counter() - started) * 1000
            )

    app.add_exception_handler(ApiError, api_error_response)

    @app.exception_handler(RequestValidationError)
    def malformed_request(_: Request, __: RequestValidationError) -> JSONResponse:
        """Expose the same narrow, stable malformed-request envelope everywhere."""
        return JSONResponse(status_code=422, content={"detail": {"code": "request_invalid"}})

    @app.exception_handler(DomainError)
    def domain_error(_: Request, error: DomainError) -> JSONResponse:
        """A broken invariant is a malformed request, not a server fault."""
        return JSONResponse(
            status_code=422,
            content={"reason_code": "domain_invariant_violated", "human_summary": str(error)},
        )

    @app.exception_handler(PspUnreachable)
    def settlement_unreachable(_: Request, error: PspUnreachable) -> JSONResponse:
        """Unknown, not refused. The reservation stays committed and the budget stays
        held; `POST /reconcile` is what closes it once the processor answers again."""
        return JSONResponse(
            status_code=502,
            content={
                "reason_code": "settlement_unreachable",
                "human_summary": "O processador não respondeu; a compra ficou em dúvida.",
            },
        )

    @app.get("/health", tags=["ops"])
    def health(request: Request) -> dict[str, str]:
        """Alive, and the instant this instance reads validity against.

        The clock is published because a page that computes `expires_at` from the
        browser's wall clock creates an already-expired mandate the moment a judge
        advances the demo clock — and then every creation is a 422 nobody asked for.
        It is not a disclosure: the offset is already on the trial-by-fire console,
        and only an operator can move it.
        """
        return {"status": "ok", "now": runtime_of(request).clock.now().isoformat()}

    app.include_router(agent.router)
    app.include_router(agents.router)
    app.include_router(mandates.router)
    app.include_router(authorization.router)
    app.include_router(escalations.router)
    app.include_router(ledger.router)
    app.include_router(merchant.router)
    app.include_router(operations.router)
    app.include_router(telegram_chats.router)
    # Mounted only when explicitly enabled. A route that corrupts the audit log is
    # not something a deployment should have to remember to lock down: without the
    # flag it does not exist, and does not appear in the OpenAPI document either.
    if tampering_enabled():
        app.include_router(create_demo_tamper_router())
    return app
