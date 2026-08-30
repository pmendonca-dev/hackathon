from __future__ import annotations

from fastapi import APIRouter

from aval.security.key_custody import KeyCustodyService


UCP_VERSION = "2026-08-25"
UCP_CAPABILITIES = (
    "dev.ucp.shopping.checkout",
    "dev.ucp.common.payment.ap2_mandate",
)


def create_ucp_discovery_router(*, custody: KeyCustodyService, key_id: str) -> APIRouter:
    router = APIRouter()

    @router.get("/.well-known/ucp")
    async def discovery() -> dict[str, object]:
        return {
            "ucp": {"version": UCP_VERSION},
            "capabilities": list(UCP_CAPABILITIES),
            "keys": [custody.public_jwk(key_id)],
        }

    return router
