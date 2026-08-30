"""A restart must not invalidate what the database already trusts.

Every custody in this system publishes a public half that outlives the process: agent
identities are registered in the database, offers carry a merchant signature, and the
protocol lane verifies against keys it was told about. Drawing those keys fresh on every
boot is what the demo runbook warns about — the second process wins, and every purchase
after it dies with `signature_invalid`. `AVAL_CUSTODY_SEED` is what closes that.
"""

from __future__ import annotations

from aval.merchant.catalog import MERCHANTS
from aval.runtime import DEMO_AGENT_KID, PROOF_KID, build_runtime
from aval.main import PROTOCOL_KEY_IDS


def _boot(monkeypatch, **environment: str):
    for name, value in environment.items():
        monkeypatch.setenv(name, value)
    return build_runtime(extra_key_ids=PROTOCOL_KEY_IDS)


def test_without_a_seed_every_boot_draws_new_keys(monkeypatch):
    """The throwaway default stays as it is: a clone with no configuration owes nobody
    a stable identity, and a seed silently invented here would be a seed nobody kept."""
    monkeypatch.delenv("AVAL_CUSTODY_SEED", raising=False)

    first = build_runtime(extra_key_ids=PROTOCOL_KEY_IDS)
    second = build_runtime(extra_key_ids=PROTOCOL_KEY_IDS)

    assert first.custody.public_jwk("merchant-key") != second.custody.public_jwk("merchant-key")


def test_a_seed_reproduces_every_protocol_key(monkeypatch):
    first = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")
    second = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")

    for key_id in (PROOF_KID, *PROTOCOL_KEY_IDS):
        if key_id == "operator-key":
            continue
        assert first.custody.public_jwk(key_id) == second.custody.public_jwk(key_id), key_id


def test_a_seed_reproduces_the_agent_key_the_database_registered(monkeypatch):
    """This is the one the runbook's warning is about: the agent's public key is written
    into the shared database, so a fresh private key there is a broken purchase."""
    first = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")
    second = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")

    assert first.agent_custody.public_jwk(DEMO_AGENT_KID) == second.agent_custody.public_jwk(
        DEMO_AGENT_KID
    )


def test_a_seed_reproduces_the_merchant_offer_keys(monkeypatch):
    first = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")
    second = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")

    for merchant_kid in MERCHANTS.values():
        assert first.merchant_custody.public_jwk(merchant_kid) == (
            second.merchant_custody.public_jwk(merchant_kid)
        ), merchant_kid


def test_the_agent_custody_and_the_protocol_custody_stay_different_keys(monkeypatch):
    """One seed, several custodies — and no two of them may end up holding the same
    private key, or an agent could sign as the issuer."""
    runtime = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")

    protocol = {runtime.custody.public_jwk(kid)["x"] for kid in PROTOCOL_KEY_IDS if kid != "operator-key"}
    agent = runtime.agent_custody.public_jwk(DEMO_AGENT_KID)["x"]
    merchant = {runtime.merchant_custody.public_jwk(kid)["x"] for kid in MERCHANTS.values()}

    assert agent not in protocol
    assert not (merchant & protocol)
    assert agent not in merchant


def test_a_custody_seed_alone_does_not_grant_operator_revocation_authority(monkeypatch):
    """`operator-key` is the one key whose existence is an authority decision. It stays
    behind its own explicit variable: a deployment that only wanted stable keys must not
    quietly acquire an operator who can revoke a mandate."""
    monkeypatch.delenv("AVAL_OPERATOR_AUTHORITY_SEED", raising=False)

    runtime = _boot(monkeypatch, AVAL_CUSTODY_SEED="production-seed")

    assert not runtime.custody.has("operator-key")
