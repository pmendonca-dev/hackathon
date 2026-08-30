"""A returning-customer handle the merchant can use and cannot correlate.

Two facts about the merchant view, before this existed:

The merchant had *no* stable handle for a buyer at all. `agent_id` is one shared agent
identity for every buyer in the system, so it says "an agent bought this" and nothing
about who — useful for trust, useless for recognising a returning customer.

And the two fields that *were* mandate-scoped, `policy_version` and `revocation_epoch`,
are counters that move with the mandate rather than with the sale. Two merchants
comparing them against timestamps have a weak but real linkage signal for the same
buyer, and they buy the merchant nothing: what a merchant verifies is the signed proof,
which carries both already.

So the trade is exact: take away the counters that correlate and give back a pseudonym
that is stable where the merchant needs it and different everywhere else.
"""

from __future__ import annotations


def merchant_view(harness, merchant_id: str = "vuelaya") -> list[dict]:
    return harness.client.get(
        "/ledger", params={"merchant_id": merchant_id, "view": "merchant"}
    ).json()["entries"]


def buy(harness, mandate_id: str, key: str, **overrides):
    return harness.capture(harness.purchase(mandate_id, **overrides) | {"idempotency_key": key})


def pairwise_at(harness, merchant_id: str) -> str:
    entries = merchant_view(harness, merchant_id)
    assert entries, f"{merchant_id} must see its own sale"
    return entries[0]["detail"]["pairwise_id"]


def test_the_same_buyer_at_the_same_merchant_is_the_same_handle(harness):
    mandate_id = harness.create_mandate(
        limit={"minor_units": 100000, "currency": "USD", "scale": 2}
    )
    buy(harness, mandate_id, "cap_a", checkout_id="chk_a")
    buy(harness, mandate_id, "cap_b", checkout_id="chk_b")

    handles = {entry["detail"]["pairwise_id"] for entry in merchant_view(harness)}

    assert len(handles) == 1


def test_the_same_buyer_at_two_merchants_is_two_handles(harness):
    """The whole point: nothing the two sellers hold is the same value."""
    mandate_id = harness.create_mandate(
        allowed_merchant_ids=["vuelaya", "andesair"],
        limit={"minor_units": 100000, "currency": "USD", "scale": 2},
    )
    buy(harness, mandate_id, "cap_v", checkout_id="chk_v")
    buy(harness, mandate_id, "cap_a", checkout_id="chk_a", merchant_id="andesair")

    assert pairwise_at(harness, "vuelaya") != pairwise_at(harness, "andesair")


def test_two_buyers_at_one_merchant_are_two_handles(harness):
    marta = harness.create_mandate()
    other = harness.create_mandate(
        principal={"id": "usr_bruno", "display_name": "Bruno Reis"}
    )
    buy(harness, marta, "cap_m", checkout_id="chk_m")
    buy(harness, other, "cap_o", checkout_id="chk_o")

    handles = {entry["detail"]["pairwise_id"] for entry in merchant_view(harness)}

    assert len(handles) == 2


def test_the_handle_does_not_carry_the_mandate_inside_it(harness):
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id, "cap_h")

    raw = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    ).text

    assert mandate_id not in raw
    assert pairwise_at(harness, "vuelaya") != mandate_id


def test_the_merchant_no_longer_reads_the_mandate_scoped_counters(harness):
    """`policy_version` and `revocation_epoch` move with the mandate, not with the
    sale. They are in the signed proof the merchant verifies; repeating them in the
    trail only hands two sellers a value to compare."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id, "cap_c")

    detail = merchant_view(harness)[0]["detail"]

    assert "policy_version" not in detail
    assert "revocation_epoch" not in detail


def test_the_auditor_still_reads_everything(harness):
    """Redacting for the merchant must never redact the record itself."""
    mandate_id = harness.create_mandate()
    buy(harness, mandate_id, "cap_d")

    entries = harness.client.get(
        "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
    ).json()["entries"]

    committed = next(e for e in entries if e["event_type"] == "purchase_committed")
    assert committed["detail"]["policy_version"] == 1
    assert committed["detail"]["agent_id"]


def test_the_pairwise_handle_is_named_in_what_the_merchant_is_told_is_hidden(harness):
    response = harness.client.get(
        "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
    ).json()

    assert any("correlat" in line.lower() for line in response["redacted"])
