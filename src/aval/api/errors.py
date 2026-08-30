"""One error shape for the whole surface.

`reason_code` is stable and machine-readable; `human_summary` is the sentence that
reaches a screen or a chat. Both come from the core whenever the core produced them.
"""

from __future__ import annotations

from fastapi import Request
from fastapi.responses import JSONResponse


class ApiError(Exception):
    def __init__(self, status_code: int, reason_code: str, human_summary: str) -> None:
        super().__init__(reason_code)
        self.status_code = status_code
        self.reason_code = reason_code
        self.human_summary = human_summary


def api_error_response(_: Request, error: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=error.status_code,
        content={"reason_code": error.reason_code, "human_summary": error.human_summary},
    )
