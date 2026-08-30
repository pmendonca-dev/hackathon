"""VuelaYa and the two sellers next to it: the supply side of the demo.

A real merchant is another company behind another API. Here each one is a row in a
table with a signing key of its own, kept apart from the authorization key on purpose:
the offer is signed by the seller, the authorization by AVAL, and the merchant
verification path only ever uses public keys. Swapping this for an HTTP client changes
nothing above it.

Three sellers, not one, because *which merchant* is a mandate constraint and a catalogue
with a single seller can never exercise it. AndesAir and Posadas sit outside the demo
mandate's scope on purpose — an agent shopping for the cheapest fare will find them.

The catalogue is shaped for a decision that is not `min(price)`. Almost every route has
a cheap-but-punishing option and a dearer-but-civilised one, and the attributes that
separate them travel *inside the signed offer* — an attribute the seller did not sign is
an attribute anyone can forge, and deciding on it would be deciding on nothing.

It is also shaped for the hard cases: fares inside the mandate, one above the accumulated
budget, one above the ceiling that no approval can reach, a category that is out of scope,
and a merchant that is out of scope.
"""

from __future__ import annotations

from dataclasses import dataclass

MERCHANT_ID = "vuelaya"
MERCHANT_KID = "vuelaya-k1"

# The one seller that is not a seller: AVAL's own test marketplace, under which a page
# discovered on the open web is re-issued as a signed offer. It has no catalogue rows —
# every offer it makes is minted from something a search just found.
#
# Its key lives in `merchant_custody` beside the real sellers', and deliberately **not**
# in the authorization custody. AVAL signing the offer *and* the authorization with one
# key would collapse the separation the rest of this file exists to maintain: the seller
# says what is for sale, AVAL says whether it may be bought, and neither can produce the
# other half of the exchange.
TEST_MARKETPLACE_ID = "aval_test_marketplace"
TEST_MARKETPLACE_KID = "aval-test-marketplace-k1"

# Each seller signs with its own key. The verifier picks the key by the merchant the
# offer claims to be from, and a lie there simply fails the signature check.
MERCHANTS: dict[str, str] = {
    "vuelaya": MERCHANT_KID,
    "andesair": "andesair-k1",
    "posadas": "posadas-k1",
    TEST_MARKETPLACE_ID: TEST_MARKETPLACE_KID,
}


@dataclass(frozen=True)
class CatalogItem:
    sku: str
    title: str
    category: str
    minor_units: int
    merchant_id: str = MERCHANT_ID
    currency: str = "USD"
    scale: int = 2
    # What makes one offer better than another cheaper one. Only what is set is
    # published, and everything published is signed.
    stops: int | None = None
    duration_minutes: int | None = None
    departs: str | None = None
    refundable: bool | None = None
    checked_bag: bool | None = None
    nights: int | None = None

    def attributes(self) -> dict[str, object]:
        named = {
            "stops": self.stops,
            "duration_minutes": self.duration_minutes,
            "departs": self.departs,
            "refundable": self.refundable,
            "checked_bag": self.checked_bag,
            "nights": self.nights,
        }
        return {key: value for key, value in named.items() if value is not None}


def _flight(
    sku: str,
    title: str,
    minor_units: int,
    *,
    merchant_id: str = MERCHANT_ID,
    stops: int,
    duration_minutes: int,
    departs: str,
    refundable: bool = False,
    checked_bag: bool = False,
) -> CatalogItem:
    return CatalogItem(
        sku,
        title,
        "travel",
        minor_units,
        merchant_id=merchant_id,
        stops=stops,
        duration_minutes=duration_minutes,
        departs=departs,
        refundable=refundable,
        checked_bag=checked_bag,
    )


def _stay(
    sku: str, title: str, minor_units: int, *, merchant_id: str = MERCHANT_ID, nights: int
) -> CatalogItem:
    return CatalogItem(
        sku, title, "lodging", minor_units, merchant_id=merchant_id, nights=nights
    )


CATALOG: tuple[CatalogItem, ...] = (
    # ── Córdoba: the route the case names, and where the trade-off lives. The cheapest
    # fare costs nineteen hours and a connection; the next one leaves at dawn; the third
    # is the one a person would actually want. No rule picks between them for you.
    _flight(
        "FL-SAO-COR-0918", "São Paulo → Córdoba, 18 set · 2 escalas, 19h", 11800,
        stops=2, duration_minutes=1140, departs="06:10",
    ),
    _flight(
        "FL-SAO-COR-0917N", "São Paulo → Córdoba, 17 set · direto, madrugada", 11900,
        stops=0, duration_minutes=185, departs="04:20",
    ),
    _flight(
        "FL-SAO-COR-1002", "São Paulo → Córdoba, 2 out · 1 escala, 8h40", 12400,
        stops=1, duration_minutes=520, departs="09:35",
    ),
    _flight(
        "FL-SAO-COR-0917", "São Paulo → Córdoba, 17 set · direto, 3h05", 13000,
        stops=0, duration_minutes=185, departs="10:45", checked_bag=True,
    ),
    _flight(
        "FL-SAO-COR-0917L", "São Paulo → Córdoba, 17 set · direto, bagagem e assento", 14600,
        stops=0, duration_minutes=185, departs="14:15", checked_bag=True,
    ),
    _flight(
        "FL-SAO-COR-0917R", "São Paulo → Córdoba, 17 set · direto, reembolsável", 15200,
        stops=0, duration_minutes=185, departs="10:45", refundable=True, checked_bag=True,
    ),
    # Above any ceiling a sane mandate carries. It exists to be refused, not approved.
    _flight(
        "FL-SAO-COR-EXEC", "São Paulo → Córdoba, executiva", 90000,
        stops=0, duration_minutes=185, departs="10:45", refundable=True, checked_bag=True,
    ),
    # ── Buenos Aires
    _flight(
        "FL-SAO-BUE-0905", "São Paulo → Buenos Aires, 5 set · 1 escala, 7h20", 16200,
        stops=1, duration_minutes=440, departs="07:00",
    ),
    _flight(
        "FL-SAO-BUE-1020", "São Paulo → Buenos Aires, 20 out · direto, 2h55", 18500,
        stops=0, duration_minutes=175, departs="11:30", checked_bag=True,
    ),
    _flight(
        "FL-SAO-BUE-PRIME", "São Paulo → Buenos Aires, primeira classe", 120000,
        stops=0, duration_minutes=175, departs="11:30", refundable=True, checked_bag=True,
    ),
    # ── Santiago: here the cheapest seat belongs to a merchant the mandate never named.
    _flight(
        "FL-SAO-SCL-1120", "São Paulo → Santiago, 20 nov · direto, madrugada", 22800,
        stops=0, duration_minutes=245, departs="03:50",
    ),
    _flight(
        "FL-SAO-SCL-1112", "São Paulo → Santiago, 12 nov · 1 escala, 9h", 24500,
        stops=1, duration_minutes=540, departs="08:20",
    ),
    _flight(
        "FL-SAO-SCL-1105", "São Paulo → Santiago, 5 nov · direto, 4h05", 30000,
        stops=0, duration_minutes=245, departs="13:10", checked_bag=True,
    ),
    # ── Montevidéu, Mendoza, Assunção
    _flight(
        "FL-SAO-ASU-0910", "São Paulo → Assunção, 10 set · direto, 2h20", 10900,
        stops=0, duration_minutes=140, departs="16:40",
    ),
    _flight(
        "FL-SAO-MVD-1015", "São Paulo → Montevidéu, 15 out · 1 escala, 6h30", 12900,
        stops=1, duration_minutes=390, departs="06:45",
    ),
    _flight(
        "FL-SAO-MDZ-0921", "São Paulo → Mendoza, 21 set · 1 escala, 9h", 13800,
        stops=1, duration_minutes=540, departs="05:30",
    ),
    _flight(
        "FL-SAO-MVD-1101", "São Paulo → Montevidéu, 1 nov · direto, 2h40", 15400,
        stops=0, duration_minutes=160, departs="12:05", checked_bag=True,
    ),
    _flight(
        "FL-SAO-MDZ-1005", "São Paulo → Mendoza, 5 out · direto, 3h50", 15900,
        stops=0, duration_minutes=230, departs="09:10", checked_bag=True,
    ),
    # ── Longer hauls: inside the ceiling, past the budget. The refusal a judge can reach
    # without touching a limit.
    _flight(
        "FL-SAO-LIM-1120", "São Paulo → Lima, 20 nov · 1 escala, 11h", 28900,
        stops=1, duration_minutes=660, departs="07:55",
    ),
    _flight(
        "FL-SAO-LIM-1103", "São Paulo → Lima, 3 nov · direto, 5h50", 34000,
        stops=0, duration_minutes=350, departs="10:20", checked_bag=True,
    ),
    _flight(
        "FL-SAO-BOG-1118", "São Paulo → Bogotá, 18 nov · 1 escala, 12h", 41000,
        stops=1, duration_minutes=720, departs="06:00",
    ),
    _flight(
        "FL-SAO-BOG-1125", "São Paulo → Bogotá, 25 nov · direto, 6h20", 46000,
        stops=0, duration_minutes=380, departs="15:45", checked_bag=True,
    ),
    # ── Out of category: lodging under a travel-only mandate.
    _stay("HT-COR-CENTRO", "Hotel Córdoba Centro, 3 noites", 22000, nights=3),
    _stay("HT-COR-NORTE", "Hotel Córdoba Norte, 3 noites", 25500, nights=3),
    _stay("HT-SCL-CENTRO", "Hotel Santiago Centro, 3 noites", 27000, nights=3),
    _stay("HT-BUE-PALERMO", "Hotel Buenos Aires Palermo, 4 noites", 33000, nights=4),
    # ── A category that reads as travel and is not: the bundle. A model asked for a trip
    # will reach for it, and the mandate says travel — not travel-and-a-hotel.
    CatalogItem("PK-COR-3N", "Pacote Córdoba: voo + 3 noites", "package", 29500, nights=3),
    CatalogItem("PK-BUE-4N", "Pacote Buenos Aires: voo + 4 noites", "package", 38000, nights=4),
    CatalogItem("PK-SCL-5N", "Pacote Santiago: voo + 5 noites, esqui", "package", 62000, nights=5),
    # ── AndesAir: sells the same routes and is not in the mandate. It undercuts VuelaYa
    # on exactly one route — Santiago — so the merchant-scope refusal is something the
    # presenter reaches for on purpose instead of something that ambushes another beat.
    # Everywhere else it is second cheapest: present, tempting, never accidental.
    _flight(
        "AN-SAO-SCL-1105", "São Paulo → Santiago, 5 nov · direto (AndesAir)", 21900,
        merchant_id="andesair", stops=0, duration_minutes=245, departs="13:10",
    ),
    _flight(
        "AN-SAO-BUE-1020", "São Paulo → Buenos Aires, 20 out · direto (AndesAir)", 17400,
        merchant_id="andesair", stops=0, duration_minutes=175, departs="11:30",
    ),
    _flight(
        "AN-SAO-COR-0917", "São Paulo → Córdoba, 17 set · direto (AndesAir)", 12500,
        merchant_id="andesair", stops=0, duration_minutes=185, departs="10:45",
    ),
    _flight(
        "AN-SAO-COR-1002", "São Paulo → Córdoba, 2 out · 1 escala (AndesAir)", 12900,
        merchant_id="andesair", stops=1, duration_minutes=520, departs="09:35",
    ),
    _flight(
        "AN-SAO-MVD-0928", "São Paulo → Montevidéu, 28 set · direto (AndesAir)", 13500,
        merchant_id="andesair", stops=0, duration_minutes=160, departs="18:20",
    ),
    _flight(
        "AN-SAO-LIM-1103", "São Paulo → Lima, 3 nov · direto (AndesAir)", 35000,
        merchant_id="andesair", stops=0, duration_minutes=350, departs="10:20",
    ),
    # ── Posadas: lodging from a seller the mandate never named. Two ways out of scope.
    _stay("PS-COR-BOUTIQUE", "Pousada Córdoba Boutique, 3 noites", 24000,
          merchant_id="posadas", nights=3),
    _stay("PS-MDZ-VINHEDO", "Pousada Mendoza Vinhedo, 2 noites", 19500,
          merchant_id="posadas", nights=2),
    _stay("PS-BUE-SANTELMO", "Pousada Buenos Aires San Telmo, 4 noites", 28500,
          merchant_id="posadas", nights=4),
)
