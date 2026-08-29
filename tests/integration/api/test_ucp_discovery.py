from __future__ import annotations

import asyncio

from aval.api.routers.ucp_discovery import create_ucp_discovery_router
from aval.security.key_custody import KeyCustodyService


def test_discovery_publishes_validated_ucp_capabilities_and_local_es256_key() -> None:
    """Catches a discovery payload that omits AP2 or publishes a non-local signing key."""
    custody = KeyCustodyService()
    custody.generate_es256("merchant-key")

    router = create_ucp_discovery_router(custody=custody, key_id="merchant-key")
    route = next(route for route in router.routes if route.path == "/.well-known/ucp")
    document = asyncio.run(route.endpoint())

    assert document["ucp"] == {"version": "2026-08-25"}
    assert document["capabilities"] == [
        "dev.ucp.shopping.checkout",
        "dev.ucp.common.payment.ap2_mandate",
    ]
    assert document["keys"] == [custody.public_jwk("merchant-key")]
