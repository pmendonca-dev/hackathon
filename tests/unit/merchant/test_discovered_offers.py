"""Turning a page on the web into something the core is willing to read.

The core only ever evaluates a signed offer. A discovered candidate is not one — nobody
signed it, and the shop it came from has never heard of AVAL. So Computer B re-issues it
under a marketplace key of its own, and these tests pin down exactly what that signature
does and does not claim.

It claims: *AVAL found this title at this price at this URL, and nothing has edited it
since.* It does not claim the seller agreed to anything, which is why the demo copy has
to keep saying so out loud.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from aval.discovery.models import DiscoveredOffer
from aval.merchant.catalog import TEST_MARKETPLACE_ID, TEST_MARKETPLACE_KID
from aval.merchant.discovered_offers import SHOPPING_CATEGORY, DiscoveredOfferIssuer
from aval.merchant.offers import terms_hash_of
from aval.security.jws import verify_compact_jws
from aval.security.key_custody import KeyCustodyService

NOW = datetime(2026, 8, 30, 12, 0, 0, tzinfo=UTC)


def candidate(**overrides: object) -> DiscoveredOffer:
    base = {
        "title": "Nintendo Switch OLED",
        "source_merchant": "shop.example",
        "source_url": "https://shop.example/switch",
        "amount_minor_units": 180000,
        "currency": "BRL",
        "evidence": "Preço anunciado na página do produto.",
    }
    return DiscoveredOffer(**{**base, **overrides})  # type: ignore[arg-type]


@pytest.fixture
def custody() -> KeyCustodyService:
    keys = KeyCustodyService()
    keys.generate_es256(TEST_MARKETPLACE_KID)
    return keys


@pytest.fixture
def issuer(custody: KeyCustodyService) -> DiscoveredOfferIssuer:
    return DiscoveredOfferIssuer(clock=lambda: NOW, custody=custody)


def test_discovered_offer_is_signed_as_the_test_marketplace(
    issuer: DiscoveredOfferIssuer, custody: KeyCustodyService
) -> None:
    offer = issuer.issue(candidate())
    assert offer["merchant_id"] == TEST_MARKETPLACE_ID
    assert offer["item"]["source_url"] == "https://shop.example/switch"
    assert offer["merchant_authorization"]
    claims = verify_compact_jws(
        offer["merchant_authorization"], custody.verifying_key(TEST_MARKETPLACE_KID)
    )
    assert claims["merchant_id"] == TEST_MARKETPLACE_ID


def test_the_signature_covers_the_price_and_the_link(
    issuer: DiscoveredOfferIssuer, custody: KeyCustodyService
) -> None:
    """Editing either after issue must break the signature, or the offer proves nothing."""
    offer = issuer.issue(candidate())
    claims = verify_compact_jws(
        offer["merchant_authorization"], custody.verifying_key(TEST_MARKETPLACE_KID)
    )
    assert claims["total"]["minor_units"] == 180000
    assert claims["item"]["source_url"] == "https://shop.example/switch"
    assert claims["item"]["evidence"]
    assert claims["item"]["source_merchant"] == "shop.example"


def test_the_terms_hash_is_the_hash_of_what_was_signed(issuer: DiscoveredOfferIssuer) -> None:
    offer = issuer.issue(candidate())
    payload = {key: value for key, value in offer.items() if key not in ("terms_hash", "merchant_authorization")}
    assert offer["terms_hash"] == terms_hash_of(payload)


def test_the_amount_is_copied_and_never_recomputed(issuer: DiscoveredOfferIssuer) -> None:
    offer = issuer.issue(candidate(amount_minor_units=199999))
    assert offer["total"] == {"minor_units": 199999, "currency": "BRL", "scale": 2}


def test_every_discovered_offer_is_shopping(issuer: DiscoveredOfferIssuer) -> None:
    """The MVP buys one kind of thing, and the mandate's scope is what allows it."""
    assert issuer.issue(candidate())["item"]["category"] == SHOPPING_CATEGORY


def test_an_offer_can_only_be_spent_once(issuer: DiscoveredOfferIssuer) -> None:
    first, second = issuer.issue(candidate()), issuer.issue(candidate())
    assert first["nonce"] != second["nonce"]
    assert first["offer_id"] != second["offer_id"]


def test_an_offer_does_not_outlive_the_tick_that_found_it(issuer: DiscoveredOfferIssuer) -> None:
    """A price read off a page an hour ago is not a price."""
    not_after = datetime.fromisoformat(issuer.issue(candidate())["not_after"])
    assert NOW < not_after <= NOW + timedelta(minutes=15)


def test_the_same_page_keeps_the_same_sku(issuer: DiscoveredOfferIssuer) -> None:
    """Two ticks that find one page must not read as two different products."""
    assert issuer.issue(candidate())["item"]["sku"] == issuer.issue(candidate())["item"]["sku"]
    assert issuer.issue(candidate())["item"]["sku"] != issuer.issue(
        candidate(source_url="https://shop.example/other")
    )["item"]["sku"]


def test_the_issuer_carries_nothing_the_normalizer_did_not_approve(
    issuer: DiscoveredOfferIssuer,
) -> None:
    """Only the fields on the dataclass reach the payload. A model that smuggled an
    extra key into the answer has nowhere to put it — normalization dropped it long
    before here, and this is the second wall behind that."""
    item = issuer.issue(candidate())["item"]
    assert set(item) == {"sku", "title", "category", "source_merchant", "source_url", "evidence"}
