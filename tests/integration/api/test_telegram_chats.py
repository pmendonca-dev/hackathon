"""The chat directory answers the operator, and never the private key.

The key redaction is the whole reason this file exists: the bot's identity store holds
a PEM per chat, and a route that reads that file is one careless `dict(entry)` away from
publishing spending authority over HTTP.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from aval.api.app import create_app
from aval.runtime import build_runtime


IDENTITIES = {
    "identities": [
        {
            "chat_id": 1731834680,
            "kid": "tg_1731834680",
            "principal_id": "usr_tg_1731834680",
            "display_name": "Pedro",
            "mandate_id": "mandate_abc",
            "private_key_pem": "-----BEGIN PRIVATE KEY-----\nsegredo\n-----END PRIVATE KEY-----\n",
        }
    ]
}


@pytest.fixture
def client(tmp_path, monkeypatch):
    store = tmp_path / "telegram-identities.json"
    store.write_text(json.dumps(IDENTITIES), encoding="utf-8")
    monkeypatch.setenv("TELEGRAM_IDENTITY_PATH", str(store))
    monkeypatch.setenv("AVAL_OPERATOR_TOKEN", "demo-token")
    monkeypatch.setenv("AVAL_DATABASE_PATH", ":memory:")
    return TestClient(create_app(build_runtime()))


def test_lists_chats_for_the_operator(client):
    response = client.get("/admin/telegram/chats", headers={"X-Aval-Operator": "demo-token"})

    assert response.status_code == 200
    chats = response.json()["chats"]
    assert chats == [
        {
            "chat_id": 1731834680,
            "display_name": "Pedro",
            "principal_id": "usr_tg_1731834680",
            "mandate_id": "mandate_abc",
        }
    ]


def test_never_answers_the_private_key(client):
    response = client.get("/admin/telegram/chats", headers={"X-Aval-Operator": "demo-token"})

    assert "PRIVATE KEY" not in response.text
    assert "private_key_pem" not in response.text


def test_a_stranger_gets_no_directory_of_buyers(client):
    assert client.get("/admin/telegram/chats").status_code == 401
    assert (
        client.get("/admin/telegram/chats", headers={"X-Aval-Operator": "errado"}).status_code
        == 403
    )


def test_no_bot_yet_is_an_empty_list_not_an_error(tmp_path, monkeypatch):
    monkeypatch.setenv("TELEGRAM_IDENTITY_PATH", str(tmp_path / "nao-existe.json"))
    monkeypatch.setenv("AVAL_OPERATOR_TOKEN", "demo-token")
    monkeypatch.setenv("AVAL_DATABASE_PATH", ":memory:")
    client = TestClient(create_app(build_runtime()))

    response = client.get("/admin/telegram/chats", headers={"X-Aval-Operator": "demo-token"})

    assert response.status_code == 200
    assert response.json() == {"chats": []}
