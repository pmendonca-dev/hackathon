"""The claims a holder signs to bring a mandate into existence.

The core verifies these field by field against the mandate being registered, the same
way it verifies a limit change. This builder exists so the in-repo clients — the bot and
the smoke — cannot drift from that shape by accident; it is a convenience for callers,
never an authority. Nothing here decides anything, and a claim built by this function
still has to survive `AuthorizationCore._verified_creation`.

`creation_nonce` is what makes the proof single-use. A revocation is irreversible, so
replaying one changes nothing; a creation is *additive*, so a replayed one would mint a
second mandate carrying the same terms and double what an agent may spend without the
holder ever signing twice.
"""

from __future__ import annotations

import secrets
from typing import Any


def mandate_creation_claims(payload: dict[str, Any], *, nonce: str | None = None) -> dict[str, Any]:
    """Claims for the mandate described by `payload`, in the shape the core checks."""
    ceiling = payload.get("ceiling")
    usage_limit = payload.get("usage_limit")
    return {
        "purpose": "mandate_creation",
        "principal_id": payload["principal"]["id"],
        "allowed_merchant_ids": sorted(payload["allowed_merchant_ids"]),
        "allowed_categories": sorted(payload["allowed_categories"]),
        "limit_minor_units": payload["limit"]["minor_units"],
        "currency": payload["limit"]["currency"],
        "scale": payload["limit"]["scale"],
        "ceiling_minor_units": None if ceiling is None else ceiling["minor_units"],
        "max_uses": None if usage_limit is None else usage_limit["max_uses"],
        "usage_window_seconds": None if usage_limit is None else usage_limit["window_seconds"],
        "expires_at": payload["expires_at"],
        "creation_nonce": nonce or f"mcn_{secrets.token_hex(8)}",
    }
