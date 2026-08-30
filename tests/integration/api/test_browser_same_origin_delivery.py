from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from aval.main import create_app


def _production_build(directory: Path) -> Path:
    """Create the smallest output shape emitted by a production Vite build."""
    assets = directory / "assets"
    assets.mkdir(parents=True)
    (directory / "index.html").write_text(
        "<!doctype html><html><body><div id=\"root\">AVAL UI</div>"
        "<script type=\"module\" src=\"/assets/app-abc12345.js\"></script></body></html>",
        encoding="utf-8",
    )
    (assets / "app-abc12345.js").write_text(
        "console.log('AVAL production UI');",
        encoding="utf-8",
    )
    return directory


def _client(monkeypatch, tmp_path, web_dist: Path, *, local_http: bool = False) -> TestClient:
    monkeypatch.setenv("AVAL_UI_MERCHANT_CREDENTIAL", "merchant-secret-not-for-browser")
    if local_http:
        monkeypatch.setenv("AVAL_UI_LOCAL_HTTP", "true")
        base_url = "http://ui.aval.local"
    else:
        monkeypatch.delenv("AVAL_UI_LOCAL_HTTP", raising=False)
        base_url = "https://ui.aval.local"
    return TestClient(
        create_app(database_path=tmp_path / "runtime.sqlite3", web_dist_path=web_dist),
        base_url=base_url,
    )


def test_same_origin_delivers_production_index_hashed_assets_and_spa_routes(monkeypatch, tmp_path) -> None:
    """Removing the static delivery boundary would send Vite users back to a different origin."""
    client = _client(monkeypatch, tmp_path, _production_build(tmp_path / "dist"))

    index = client.get("/")
    asset = client.get("/assets/app-abc12345.js")
    spa_route = client.get("/operator/workspace")

    assert index.status_code == 200
    assert index.headers["content-type"].startswith("text/html")
    assert index.headers["cache-control"] == "no-cache"
    assert "AVAL UI" in index.text
    assert asset.status_code == 200
    assert asset.headers["cache-control"] == "public, max-age=31536000, immutable"
    assert "AVAL production UI" in asset.text
    assert spa_route.status_code == 200
    assert spa_route.text == index.text


def test_same_origin_preserves_bff_and_agent_api_precedence(monkeypatch, tmp_path) -> None:
    """A catch-all before APIs would turn BFF and unsigned agent failures into HTML."""
    client = _client(monkeypatch, tmp_path, _production_build(tmp_path / "dist"))

    login = client.post(
        "/ui-api/v1/session/login",
        json={"role": "merchant", "credential": "merchant-secret-not-for-browser"},
    )
    unknown_bff = client.get("/ui-api/v1/not-a-route")
    unknown_agent = client.get("/agentic_commerce/not-a-route")
    unsigned_agent = client.post(
        "/agentic_commerce/delegate_payment",
        headers={"Idempotency-Key": "unsigned"},
        json={},
    )

    assert login.status_code == 200
    assert login.headers["content-type"].startswith("application/json")
    assert "<html" not in login.text.lower()
    assert unknown_bff.status_code == 404
    assert unknown_bff.headers["content-type"].startswith("application/json")
    assert "<html" not in unknown_bff.text.lower()
    assert unknown_agent.status_code == 404
    assert unknown_agent.headers["content-type"].startswith("application/json")
    assert "<html" not in unknown_agent.text.lower()
    assert unsigned_agent.status_code == 422
    assert unsigned_agent.json() == {"detail": {"code": "ucp_agent_invalid"}}


def test_same_origin_preserves_strict_httponly_session_cookie_in_secure_and_local_modes(monkeypatch, tmp_path) -> None:
    """Serving the SPA must not downgrade the session cookie's contract flags."""
    dist = _production_build(tmp_path / "dist")
    secure_login = _client(monkeypatch, tmp_path, dist).post(
        "/ui-api/v1/session/login",
        json={"role": "merchant", "credential": "merchant-secret-not-for-browser"},
    )
    local_login = _client(monkeypatch, tmp_path / "local", dist, local_http=True).post(
        "/ui-api/v1/session/login",
        json={"role": "merchant", "credential": "merchant-secret-not-for-browser"},
    )

    assert secure_login.status_code == 200
    assert "HttpOnly" in secure_login.headers["set-cookie"]
    assert "SameSite=strict" in secure_login.headers["set-cookie"]
    assert "Secure" in secure_login.headers["set-cookie"]
    assert local_login.status_code == 200
    assert "HttpOnly" in local_login.headers["set-cookie"]
    assert "SameSite=strict" in local_login.headers["set-cookie"]
    assert "Secure" not in local_login.headers["set-cookie"]


def test_same_origin_fails_closed_when_the_production_build_is_absent(monkeypatch, tmp_path) -> None:
    """A missing dist directory must not be replaced with a fixture or an unrelated success page."""
    client = _client(monkeypatch, tmp_path, tmp_path / "missing-dist")

    root = client.get("/")
    asset = client.get("/assets/app-abc12345.js")

    assert root.status_code == 503
    assert root.json() == {"detail": {"code": "ui_build_unavailable"}}
    assert asset.status_code == 503
    assert asset.json() == {"detail": {"code": "ui_build_unavailable"}}


def test_same_origin_delivery_never_synthesizes_runtime_secrets_into_static_responses(monkeypatch, tmp_path, capsys) -> None:
    """Leaking process credentials into a served build would expose payment authority to every browser."""
    client = _client(monkeypatch, tmp_path, _production_build(tmp_path / "dist"))

    responses = [client.get("/"), client.get("/assets/app-abc12345.js"), client.get("/merchant")]
    captured = capsys.readouterr()
    delivered = "".join(response.text for response in responses) + captured.out + captured.err

    for forbidden in (
        "merchant-secret-not-for-browser",
        "4242424242424242",
        "vt_sensitive",
        "proof_sensitive",
        "eyJhbGciOiJFUzI1NiJ9",
        "private_key",
    ):
        assert forbidden not in delivered
