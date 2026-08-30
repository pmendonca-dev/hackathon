"""Same-origin delivery of the already-built browser application.

This module deliberately has no knowledge of browser sessions, Core state, or
agent authentication. It serves immutable build bytes only after every API
route has been mounted, so a catch-all navigation cannot become an API proxy.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response


_HASHED_ASSET_NAME = re.compile(r"-[A-Za-z0-9_-]{8,}\.[A-Za-z0-9]+$")
_BROWSER_METHODS = ("GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS")


def configured_web_dist_path() -> Path:
    """Return the explicit build directory or the repository's Vite output."""
    configured = os.environ.get("AVAL_WEB_DIST_PATH", "").strip()
    if configured:
        return Path(configured)
    return Path(__file__).resolve().parents[3] / "web" / "dist"


def _api_prefixes(app: FastAPI) -> frozenset[str]:
    """Reserve every documented API root before adding the SPA fallback.

    FastAPI keeps included routers as wrapper objects in ``app.routes``. Its
    public OpenAPI paths are the stable flattened view, so they include every
    BFF and agent endpoint without depending on that private implementation.
    """
    prefixes: set[str] = set()
    for path in app.openapi().get("paths", {}):
        segments = path.split("/")
        if len(segments) > 1 and segments[1]:
            prefixes.add(f"/{segments[1]}")
    return frozenset(prefixes)


class BrowserBuildDelivery:
    """Serve a Vite build while failing closed when it is unavailable."""

    def __init__(self, build_directory: Path, *, api_prefixes: frozenset[str]) -> None:
        self._build_directory = build_directory.resolve()
        self._index = self._build_directory / "index.html"
        self._api_prefixes = api_prefixes

    def _build_available(self) -> bool:
        return self._build_directory.is_dir() and self._index.is_file()

    def _is_api_path(self, request_path: str) -> bool:
        normalized = f"/{request_path.lstrip('/')}"
        return any(normalized == prefix or normalized.startswith(f"{prefix}/") for prefix in self._api_prefixes)

    def _candidate(self, request_path: str) -> Path | None:
        candidate = (self._build_directory / request_path).resolve()
        try:
            candidate.relative_to(self._build_directory)
        except ValueError:
            return None
        return candidate

    @staticmethod
    def _api_not_found() -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @staticmethod
    def _build_unavailable() -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": {"code": "ui_build_unavailable"}})

    @staticmethod
    def _static_not_found() -> JSONResponse:
        return JSONResponse(status_code=404, content={"detail": "Not Found"})

    @staticmethod
    def _file_response(path: Path) -> FileResponse:
        cache_control = "no-cache"
        if path.parent.name == "assets" and _HASHED_ASSET_NAME.search(path.name):
            cache_control = "public, max-age=31536000, immutable"
        return FileResponse(path, headers={"Cache-Control": cache_control})

    def response_for(self, request: Request, request_path: str) -> Response:
        if self._is_api_path(request_path):
            return self._api_not_found()
        if not self._build_available():
            return self._build_unavailable()
        if request.method not in {"GET", "HEAD"}:
            return self._static_not_found()

        candidate = self._candidate(request_path)
        if candidate is not None and candidate.is_file():
            return self._file_response(candidate)
        if request_path.lstrip("/").startswith("assets/"):
            return self._static_not_found()
        return self._file_response(self._index)


def mount_browser_build(app: FastAPI, *, build_directory: Path) -> None:
    """Mount the final navigation fallback after all protocol and BFF routers."""
    delivery = BrowserBuildDelivery(build_directory, api_prefixes=_api_prefixes(app))
    app.state.browser_build_delivery = delivery

    @app.api_route("/", methods=_BROWSER_METHODS, include_in_schema=False)
    async def browser_root(request: Request) -> Response:
        return delivery.response_for(request, "")

    @app.api_route("/{browser_path:path}", methods=_BROWSER_METHODS, include_in_schema=False)
    async def browser_fallback(request: Request, browser_path: str) -> Response:
        return delivery.response_for(request, browser_path)
