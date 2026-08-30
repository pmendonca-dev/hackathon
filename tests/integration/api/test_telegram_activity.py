"""The judges' feed publishes decisions, and never a way to look anyone up.

The directory next door (`/admin/telegram/chats`) is operator-gated because a list of
who exists and which mandate is theirs is an oracle. This feed is open, so the burden
it carries is different and heavier: every identifier has to be gone. If a mandate id
ever appears in a line here, that line becomes a read of a stranger's limits, and the
reason the directory is gated stops mattering at all.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aval.api.app import create_app
from aval.main import SEED_MANDATE_ID
from aval.main import create_app as main_create_app
from aval.runtime import build_runtime


PRIVATE_KEY = "-----BEGIN PRIVATE KEY-----\nsegredo\n-----END PRIVATE KEY-----\n"


def _identities(*records) -> dict:
    return {"identities": list(records)}


def _record(chat_id: int, name: str, mandate_id: str | None) -> dict:
    return {
        "chat_id": chat_id,
        "kid": f"tg_{chat_id}",
        "principal_id": f"usr_tg_{chat_id}",
        "display_name": name,
        "mandate_id": mandate_id,
        "private_key_pem": PRIVATE_KEY,
    }


@pytest.fixture
def make_client(tmp_path, monkeypatch):
    def build(identities: dict) -> TestClient:
        store = tmp_path / "telegram-identities.json"
        store.write_text(json.dumps(identities), encoding="utf-8")
        monkeypatch.setenv("TELEGRAM_IDENTITY_PATH", str(store))
        monkeypatch.setenv("AVAL_DATABASE_PATH", ":memory:")
        return TestClient(create_app(build_runtime()))

    return build


def test_a_chat_with_a_mandate_appears_on_the_feed(tmp_path, monkeypatch):
    """The whole point: what happened in Telegram becomes readable on the screen.

    Pointed at the seeded mandate, so the lines on the feed are events the core really
    recorded rather than fixtures written to look like them.
    """
    store = tmp_path / "telegram-identities.json"
    store.write_text(
        json.dumps(_identities(_record(1, "Marta Silva", SEED_MANDATE_ID))), encoding="utf-8"
    )
    monkeypatch.setenv("TELEGRAM_IDENTITY_PATH", str(store))
    client = TestClient(main_create_app(database_path=tmp_path / "feed.sqlite3"))

    body = client.get("/telegram/activity").json()

    assert body["chats"] == 1
    assert body["events"], "a registered mandate is already a decision worth showing"
    first = body["events"][0]
    assert first["who"] == "Marta", "a first name is what a person recognises across a room"
    assert first["summary"] and first["event_type"]
    assert first["digest"], "the auditor tab claims a chained trail; the digest is the claim"


def test_the_feed_carries_no_identifier_to_look_anyone_up_with(make_client):
    """Open surface, so every id has to be absent — not merely unused by the screen."""
    client = make_client(_identities(_record(1731834680, "Pedro", "mandate_abc")))

    raw = client.get("/telegram/activity").text

    for forbidden in ("mandate_abc", "usr_tg_1731834680", "1731834680", "tg_1731834680"):
        assert forbidden not in raw, f"{forbidden} would make this feed a lookup"


def test_the_feed_never_answers_a_private_key(make_client):
    """The same file holds a PEM per chat; one careless dump would publish spending authority."""
    client = make_client(_identities(_record(1, "Pedro", "mandate_abc")))

    raw = client.get("/telegram/activity").text

    assert "PRIVATE KEY" not in raw
    assert "segredo" not in raw


def test_a_full_name_is_shortened_to_the_first(make_client):
    """Across a room a first name identifies; a full one just publishes more of a stranger."""
    client = make_client(_identities(_record(1, "Matheus Fondello", "mandate_abc")))

    raw = client.get("/telegram/activity").text

    assert "Fondello" not in raw


def test_no_bot_has_ever_run_is_an_empty_feed_and_not_an_error(make_client, tmp_path, monkeypatch):
    """Before anybody types /start, "nothing yet" must not look like broken wiring."""
    monkeypatch.setenv("TELEGRAM_IDENTITY_PATH", str(tmp_path / "absent.json"))
    monkeypatch.setenv("AVAL_DATABASE_PATH", ":memory:")
    client = TestClient(create_app(build_runtime()))

    response = client.get("/telegram/activity")

    assert response.status_code == 200
    assert response.json() == {"events": [], "chats": 0}


def test_a_chat_without_a_mandate_yet_is_not_counted(make_client):
    """Someone who typed /start and nothing else has no trail to publish."""
    client = make_client(_identities(_record(1, "Pedro", None)))

    body = client.get("/telegram/activity").json()

    assert body == {"events": [], "chats": 0}
