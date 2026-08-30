from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import select

from aval.application.authorization_core import AuthorizationCore
from aval.domain.entities import Mandate, Principal, RevocationAuthority
from aval.domain.enums import RevocationRole
from aval.domain.money import Money
from aval.infrastructure.sqlite.engine import create_sqlite_engine
from aval.infrastructure.sqlite.models import audit_events, metadata
from aval.security.jws import sign_compact_jws
from aval.security.key_custody import KeyCustodyService


def _core_with_authorities(tmp_path, authorities: tuple[tuple[str, RevocationRole, frozenset[str]], ...]):
    custody = KeyCustodyService()
    registered = []
    for kid, role, scopes in authorities:
        custody.generate_es256(kid)
        registered.append(
            RevocationAuthority(
                f"authority-{kid}", kid, role, custody.public_jwk(kid), scopes
            )
        )
    engine = create_sqlite_engine(tmp_path / "authority-scopes.db")
    metadata.create_all(engine)
    core = AuthorizationCore(clock=lambda: datetime(2026, 8, 29, tzinfo=UTC), engine=engine)
    core.register_mandate(
        Mandate(
            "m1", Principal("p1", "Marta"), frozenset({"merchant-1"}), Money(1_000, "BRL", 2),
            datetime(2026, 8, 30, tzinfo=UTC), 1, {"revocation_id": "r1", "epoch": 0}, tuple(registered),
        )
    )
    return core, custody, engine


def _token(custody: KeyCustodyService, kid: str, scope: str) -> str:
    return sign_compact_jws(
        {"mandate_id": "m1", "scope": scope, "reason": "test", "epoch": 1}, custody, kid
    )


@pytest.mark.parametrize("role,kid", [(RevocationRole.GUARDIAN, "guardian"), (RevocationRole.ISSUER, "issuer")])
def test_guardian_and_issuer_cannot_revoke_a_registered_non_mandate_scope(tmp_path, role, kid):
    """Changing the role gate would let a co-signer partially rewrite a mandate."""
    core, custody, _ = _core_with_authorities(
        tmp_path, ((kid, role, frozenset({"mandate", "merchant:merchant-1"})),)
    )

    with pytest.raises(ValueError, match="only revoke the mandate"):
        core.submit_signed_revocation(_token(custody, kid, "merchant:merchant-1"))


def test_operator_scope_must_be_registered_and_is_audited(tmp_path):
    """Removing operator registration or audit would make the emergency role a bypass."""
    core, custody, engine = _core_with_authorities(
        tmp_path,
        (
            ("holder", RevocationRole.HOLDER, frozenset({"merchant:merchant-1"})),
            ("operator", RevocationRole.OPERATOR, frozenset({"instrument:vt_123"})),
        ),
    )

    core.submit_signed_revocation(_token(custody, "holder", "merchant:merchant-1"))
    core.submit_signed_revocation(_token(custody, "operator", "instrument:vt_123"))

    with engine.connect() as connection:
        event_types = connection.execute(select(audit_events.c.event_type)).scalars().all()

    assert "revocation.operator" in event_types
    with pytest.raises(ValueError, match="scope is not allowed"):
        core.submit_signed_revocation(_token(custody, "operator", "budget:zero"))


@pytest.mark.parametrize("scope", ["mandate", "budget:zero", "merchant:merchant-1", "instrument:vt_123"])
def test_holder_accepts_each_registered_canonical_scope(tmp_path, scope):
    """Changing the canonical scope grammar must reject a malformed signed revocation."""
    core, custody, _ = _core_with_authorities(
        tmp_path,
        (("holder", RevocationRole.HOLDER, frozenset({"mandate", "budget:zero", "merchant:merchant-1", "instrument:vt_123"})),),
    )

    core.submit_signed_revocation(_token(custody, "holder", scope))


def test_holder_rejects_malformed_registered_instrument_scope(tmp_path):
    core, custody, _ = _core_with_authorities(
        tmp_path, (("holder", RevocationRole.HOLDER, frozenset({"instrument:card_123"})),)
    )

    with pytest.raises(ValueError, match="invalid revocation scope"):
        core.submit_signed_revocation(_token(custody, "holder", "instrument:card_123"))
