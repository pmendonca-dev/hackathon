"""Re-issuing a page found on the web as an offer the core can evaluate.

The core never reads a URL, a search result or a model's answer. It reads a signed
offer: a merchant, a category, a total, a validity and a nonce, bound together by a
signature and a terms hash. That is the only vocabulary it has, and it is the reason a
hallucinated purchase cannot become a real one.

A discovered candidate has none of that. So Computer B mints one, under a marketplace
key of its own, and the exact wording of what that signature attests matters:

> AVAL found this title, at this price, at this URL, and nothing has edited it since.

It does **not** attest that the shop agreed to sell at that price, that the page is
still up, or that an order was placed. No external seller has heard of any of this. The
customer-facing copy has to keep saying so, because a signature invites the opposite
reading and the whole point of the MVP boundary is that we do not claim it.

Two properties make this safe to put in front of the core:

1. **It cannot inflate a price.** Every number is copied from the normalized candidate;
   nothing is recomputed, converted or defaulted. A candidate that survived the
   normalizer is already below the cap the person set.
2. **It cannot mint authority.** The key is a *merchant* key, in `merchant_custody`. It
   signs what is for sale. Whether it may be bought is decided afterwards by
   `AuthorizationCore`, which reads this offer and nothing else about where it came
   from.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Any
from uuid import uuid4

from aval.discovery.models import DiscoveredOffer
from aval.merchant.catalog import TEST_MARKETPLACE_ID, TEST_MARKETPLACE_KID
from aval.merchant.offers import terms_hash_of
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService

# The one category the real-offer MVP buys in. A mandate that does not name it refuses
# every discovered offer, which is the correct default for a person who only ever
# described a flight.
SHOPPING_CATEGORY = "shopping"

# Shorter than the catalogue's ten minutes. A price read off a live page goes stale in a
# way a seeded catalogue price does not, and an offer that outlives its tick is a number
# nobody can still see.
OFFER_VALIDITY = timedelta(minutes=5)


def sku_for(source_url: str) -> str:
    """A stable name for a page, so two ticks that find it do not read as two products."""
    return f"dsc_{hashlib.sha256(source_url.encode('utf-8')).hexdigest()[:16]}"


class DiscoveredOfferIssuer:
    """Signs discovered candidates as the test marketplace.

    Takes a clock and a custody rather than the runtime, so that `aval.merchant` stays
    importable without the composition root — the same shape `MerchantOfferService` uses,
    and the reason neither of them can reach the core.
    """

    def __init__(
        self, *, clock: Callable[[], datetime], custody: KeyCustodyService
    ) -> None:
        self._clock = clock
        self._custody = custody

    def issue(self, candidate: DiscoveredOffer) -> dict[str, Any]:
        payload = {
            "offer_id": f"off_{uuid4().hex[:12]}",
            "merchant_id": TEST_MARKETPLACE_ID,
            "item": {
                "sku": sku_for(candidate.source_url),
                "title": candidate.title,
                "category": SHOPPING_CATEGORY,
                # Where it was found travels *inside* the signed payload, so the link a
                # person is shown is the link the offer was hashed with. Display data
                # outside the signature is display data anyone can rewrite.
                "source_merchant": candidate.source_merchant,
                "source_url": candidate.source_url,
                "evidence": candidate.evidence,
            },
            "total": {
                "minor_units": candidate.amount_minor_units,
                "currency": candidate.currency,
                "scale": candidate.scale,
            },
            "not_after": (self._clock() + OFFER_VALIDITY).isoformat(),
            "nonce": f"ofn_{uuid4().hex[:12]}",
        }
        return {
            **payload,
            "terms_hash": terms_hash_of(payload),
            "merchant_authorization": sign_compact_jws(
                payload, self._custody, TEST_MARKETPLACE_KID
            ),
        }
