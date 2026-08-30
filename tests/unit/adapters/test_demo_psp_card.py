"""The demo processor's card form.

There is no page and no number here — the point is the two properties the real
adapter has and the demo one must not lose: the token comes from the processor, and a
session answers only for the mandate that opened it.
"""

from __future__ import annotations

import pytest

from aval.infrastructure.psp import DemoPspAdapter, PspUnreachable


def test_a_registered_card_is_named_by_the_processor_and_never_by_the_caller() -> None:
    psp = DemoPspAdapter()
    session = psp.create_setup_session("mandate_01", return_url="https://aval.local/ok")

    card = psp.read_setup_session(session["session_id"], mandate_id="mandate_01")

    assert card is not None
    # Nothing the caller sent appears in the credential: a surface that could name its
    # own token could attach a card its holder never registered.
    assert card["token"].startswith("vt_demo_")
    assert card["label"] == "•••• 4242"
    assert session["url"].startswith("https://aval.local/ok")


def test_a_session_answers_only_for_the_mandate_that_opened_it() -> None:
    psp = DemoPspAdapter()
    session = psp.create_setup_session("mandate_01", return_url="https://aval.local/ok")

    # Unguessable is not an authorization, and the caller asked about *this* mandate.
    assert psp.read_setup_session(session["session_id"], mandate_id="mandate_02") is None
    assert psp.read_setup_session("cs_demo_unknown", mandate_id="mandate_01") is None


def test_an_offline_processor_cannot_open_a_card_form() -> None:
    psp = DemoPspAdapter(lambda: "offline")

    # Unreachable, not refused — the same distinction settlement makes.
    with pytest.raises(PspUnreachable):
        psp.create_setup_session("mandate_01", return_url="https://aval.local/ok")
