"""VuelaYa: the demo travel merchant.

A real merchant is another company behind another API. Here it is a module with its
own signing key, kept apart from the authorization key on purpose: the offer is signed
by the seller, the authorization by AVAL, and the merchant verification path only ever
uses public keys. Swapping this for an HTTP client changes nothing above it.

The catalogue is deliberately shaped for the hard cases: a flight inside the mandate,
one above the per-purchase limit, one above the ceiling that no approval can reach,
and a hotel that is outside a travel-only scope.
"""

from __future__ import annotations

from dataclasses import dataclass

MERCHANT_ID = "vuelaya"
MERCHANT_KID = "vuelaya-k1"


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    title: str
    category: str
    minor_units: int
    currency: str = "USD"
    scale: int = 2


CATALOG: tuple[CatalogItem, ...] = (
    CatalogItem("FL-SAO-COR-0917", "São Paulo → Córdoba, 17 set", "travel", 13000),
    CatalogItem("FL-SAO-BUE-1020", "São Paulo → Buenos Aires, 20 out", "travel", 18500),
    CatalogItem("FL-SAO-COR-EXEC", "São Paulo → Córdoba, executiva", "travel", 90000),
    CatalogItem("FL-SAO-SCL-1105", "São Paulo → Santiago, 5 nov", "travel", 30000),
    CatalogItem("HT-COR-CENTRO", "Hotel Córdoba Centro, 3 noites", "lodging", 22000),
)
