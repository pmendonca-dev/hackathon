"""Binding a purchase to the offer it claims to be buying.

This is edge work, not core work: it establishes that the thing being bought is the
thing the seller actually put up for sale, at that price, within its validity, once.
What the mandate then permits is decided afterwards and elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime

from aval.api.errors import ApiError
from aval.merchant.catalog import MERCHANTS
from aval.merchant.offers import terms_hash_of
from aval.security.jcs import canonicalize
from aval.security.jws import verify_compact_jws
from aval.runtime import AvalRuntime


@dataclass(frozen=True)
class BoundOffer:
    terms_hash: str
    canonical_payload: str
    nonce: str


def bind_offer(
    runtime: AvalRuntime,
    *,
    token: str,
    merchant_id: str,
    category: str,
    minor_units: int,
    currency: str,
    scale: int,
    spend_nonce: bool,
) -> BoundOffer:
    claims = _verified_offer(token, runtime)

    now = runtime.clock.now()
    try:
        not_after = datetime.fromisoformat(str(claims["not_after"]))
        offered = claims["total"]
        item = claims["item"]
        nonce = str(claims["nonce"])
    except (KeyError, TypeError, ValueError) as error:
        raise ApiError(409, "offer_malformed", "Oferta incompleta.") from error
    if now >= not_after:
        raise ApiError(409, "offer_expired", "Oferta fora da validade.")

    # Everything the buyer told us must be what the seller signed. Anything else and
    # the signature is decorating a different purchase.
    matches = (
        claims.get("merchant_id") == merchant_id
        and item.get("category") == category
        and offered.get("minor_units") == minor_units
        and offered.get("currency") == currency
        and offered.get("scale") == scale
    )
    if not matches:
        raise ApiError(409, "offer_mismatch", "A compra não corresponde à oferta assinada.")

    if spend_nonce and not runtime.spent_offer_nonces.remember(
        "offer", nonce, int(now.timestamp())
    ):
        raise ApiError(409, "offer_replayed", "Esta oferta já foi utilizada.")

    canonical = canonicalize(claims)
    return BoundOffer(
        terms_hash=terms_hash_of(claims),
        canonical_payload=canonical.decode("utf-8"),
        nonce=nonce,
    )


def offer_claims(token: str, runtime: AvalRuntime) -> dict:
    """Read a merchant offer for verification purposes only."""
    return _verified_offer(token, runtime)


def _verified_offer(token: str, runtime: AvalRuntime) -> dict:
    """Verify an offer against the key of the seller it says it comes from.

    The merchant named in the unverified header only *selects* a candidate key; it
    never grants anything. An offer that claims one seller and was signed by another
    fails here, which is the same check as before with more than one seller in the room.
    """
    named = unverified_offer_claims(token) or {}
    kid = MERCHANTS.get(str(named.get("merchant_id", "")))
    if kid is None:
        raise ApiError(401, "offer_signature_invalid", "Oferta de vendedor desconhecido.")
    try:
        return verify_compact_jws(token, runtime.merchant_custody.verifying_key(kid))
    except ValueError as error:
        raise ApiError(401, "offer_signature_invalid", "Oferta não assinada pelo merchant.") from error


def unverified_proof_claims(token: str) -> dict | None:
    """Read a proof's claims without trusting them, only to find what it names.

    Everything that matters is verified straight after, against the record AVAL kept.
    """
    return unverified_offer_claims(token)


def unverified_offer_claims(token: str) -> dict | None:
    import base64

    try:
        encoded = token.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (IndexError, ValueError, json.JSONDecodeError):
        return None
    return claims if isinstance(claims, dict) else None
