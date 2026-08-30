from __future__ import annotations

from aval.security.ecdsa import verify_es256_raw
from aval.security.key_custody import KeyCustodyService, public_key_from_jwk


def test_custody_signs_without_exposing_private_key_material():
    """Removing custody must prevent signing; callers never receive its private key."""
    custody = KeyCustodyService()
    custody.generate_es256("authority-key")

    signature = custody.sign_es256("authority-key", b"revocation-command")

    assert len(signature) == 64
    assert verify_es256_raw(
        public_key_from_jwk(custody.public_jwk("authority-key")),
        b"revocation-command",
        signature,
    )
    assert not hasattr(custody, "private_key")


def test_a_seeded_key_survives_a_restart():
    """The whole point: two processes given the same seed hold the same key.

    Without this the demo is one process that may never restart — the database keeps
    an agent's public key while a fresh custody signs with a new private one, and every
    purchase dies with `signature_invalid`.
    """
    first = KeyCustodyService()
    second = KeyCustodyService()

    first.derive_es256("agent-key", secret="master-seed", domain="protocol")
    second.derive_es256("agent-key", secret="master-seed", domain="protocol")

    assert first.public_jwk("agent-key") == second.public_jwk("agent-key")


def test_two_kids_from_one_seed_are_different_keys():
    """Domain separation per kid, or one seed would hand every role the same key —
    and the merchant could then sign what only the processor may sign."""
    custody = KeyCustodyService()

    custody.derive_es256("merchant-key", secret="master-seed", domain="protocol")
    custody.derive_es256("psp-key", secret="master-seed", domain="protocol")

    assert custody.public_jwk("merchant-key")["x"] != custody.public_jwk("psp-key")["x"]


def test_the_same_kid_in_two_domains_is_two_keys():
    """The agent's own custody and the protocol custody both name keys. One seed must
    not make them the same key, or an agent would sign as the protocol lane."""
    custody = KeyCustodyService()

    custody.derive_es256("shared-kid", secret="master-seed", domain="protocol")
    custody.derive_es256("shared-kid-agent", secret="master-seed", domain="agent")
    protocol = custody.public_jwk("shared-kid")

    other = KeyCustodyService()
    other.derive_es256("shared-kid", secret="master-seed", domain="agent")

    assert protocol["x"] != other.public_jwk("shared-kid")["x"]


def test_a_derived_key_still_signs():
    """Derivation must produce a usable P-256 key, not just a stable one."""
    custody = KeyCustodyService()
    custody.derive_es256("issuer-key", secret="master-seed", domain="protocol")

    signature = custody.sign_es256("issuer-key", b"mandate")

    assert verify_es256_raw(
        public_key_from_jwk(custody.public_jwk("issuer-key")), b"mandate", signature
    )
