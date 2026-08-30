from __future__ import annotations

from fastapi import Request

from aval.runtime import AvalRuntime


def runtime_of(request: Request) -> AvalRuntime:
    return request.app.state.runtime
