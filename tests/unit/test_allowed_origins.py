"""Naming origins must narrow the set, not widen it."""

from __future__ import annotations

from aval.api.app import DEFAULT_ORIGINS, allowed_origins


def test_an_unconfigured_instance_keeps_the_development_origins(monkeypatch):
    """A clone with no configuration still has to run `vite dev` against this process."""
    monkeypatch.delenv("AVAL_ALLOWED_ORIGINS", raising=False)

    assert allowed_origins() == list(DEFAULT_ORIGINS)


def test_naming_origins_excludes_the_development_defaults(monkeypatch):
    """A public instance that went on trusting localhost:5173 would let any page a judge
    had running on that port drive routes that change what an agent may spend."""
    monkeypatch.setenv("AVAL_ALLOWED_ORIGINS", "https://aval.example.com")

    origins = allowed_origins()

    assert origins == ["https://aval.example.com"]
    assert "http://localhost:5173" not in origins


def test_several_named_origins_are_all_kept(monkeypatch):
    monkeypatch.setenv(
        "AVAL_ALLOWED_ORIGINS", "https://a.example.com , https://b.example.com"
    )

    assert allowed_origins() == ["https://a.example.com", "https://b.example.com"]
