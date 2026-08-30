"""Signed offers and the terms hash they are bound by.

`terms_hash` is the SHA-256 of the RFC 8785 canonical form of the offer. Canonical
serialisation is what lets the merchant and AVAL agree byte for byte on *what was
sold* without exchanging the object again: two parties that serialise the same offer
land on the same hash, and any edit lands somewhere else.
"""

from __future__ import annotations

import base64
import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from aval.merchant.catalog import CATALOG, MERCHANTS, CatalogItem
from aval.security.jcs import canonicalize
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService

OFFER_VALIDITY = timedelta(minutes=10)


def terms_hash_of(payload: dict[str, Any]) -> str:
    digest = hashlib.sha256(canonicalize(payload)).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")


class MerchantOfferService:
    def __init__(self, *, clock: Callable[[], datetime], custody: KeyCustodyService) -> None:
        self._clock = clock
        self._custody = custody

    def public_jwks(self) -> dict[str, Any]:
        """Every seller's key, so any offer in the catalogue verifies offline."""
        return {"keys": [self._custody.public_jwk(kid) for kid in MERCHANTS.values()]}

    def _offer_payload(self, item: CatalogItem) -> dict[str, Any]:
        not_after = self._clock() + OFFER_VALIDITY
        return {
            "offer_id": f"off_{uuid4().hex[:12]}",
            "merchant_id": item.merchant_id,
            # The attributes are inside the payload, and the payload is what is hashed:
            # whatever the agent decides on, the seller signed.
            "item": {
                "sku": item.sku,
                "title": item.title,
                "category": item.category,
                **item.attributes(),
            },
            "total": {
                "minor_units": item.minor_units,
                "currency": item.currency,
                "scale": item.scale,
            },
            "not_after": not_after.isoformat(),
            # One nonce per offer, so an offer is a thing that can be spent once.
            "nonce": f"ofn_{uuid4().hex[:12]}",
        }

    def offer_for(self, item: CatalogItem) -> dict[str, Any]:
        payload = self._offer_payload(item)
        return {
            **payload,
            "terms_hash": terms_hash_of(payload),
            "merchant_authorization": sign_compact_jws(
                payload, self._custody, MERCHANTS[item.merchant_id]
            ),
        }

    def catalog(self) -> list[dict[str, Any]]:
        return [self.offer_for(item) for item in CATALOG]
