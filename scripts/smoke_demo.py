"""End-to-end smoke run against a live server.

    AVAL_OPERATOR_TOKEN=demo-token uvicorn aval.main:app --port 8099
    AVAL_OPERATOR_TOKEN=demo-token python scripts/smoke_demo.py http://127.0.0.1:8099

This walks the whole case in order — mandate, purchase, escalation with a signed
approval, the ceiling nobody can approve, live revocation, the impostor, the three
views and a dispute — and fails loudly on the first step that does not behave. It is
the rehearsal for the trial by fire, and it is meant to be run from a clean clone.
"""

from __future__ import annotations

import os
import sys
from datetime import UTC, datetime, timedelta

# The project depends on httpx2 — the 2.x line, published under its own name, and what
# both `anthropic` and Starlette's TestClient pull in. This script asked for `httpx` and
# so could not run at all on a clean clone, which is the worst place for that to happen:
# it is the rehearsal for the trial by fire. The fallback keeps a clone that installed
# the 0.x line working, and only `Client` is used, which both provide.
try:
    import httpx2 as httpx
except ModuleNotFoundError:  # pragma: no cover - depends on what the clone installed
    import httpx

from aval.security.jws import sign_compact_jws
from aval.security.mandate_creation import mandate_creation_claims
from aval.security.key_custody import KeyCustodyService

HOLDER_KID = "smoke_holder_k1"
PASS = "  ok  "
FAIL = " FAIL "


class Smoke:
    def __init__(self, base_url: str) -> None:
        token = os.environ.get("AVAL_OPERATOR_TOKEN", "demo-token")
        self.client = httpx.Client(
            base_url=base_url, timeout=15.0, headers={"X-Aval-Operator": token}
        )
        self.custody = KeyCustodyService()
        self.custody.generate_es256(HOLDER_KID)
        self.failures = 0

    def check(self, label: str, condition: bool, detail: str = "") -> None:
        marker = PASS if condition else FAIL
        print(f"[{marker}] {label}{'' if not detail else f' — {detail}'}")
        if not condition:
            self.failures += 1

    def create_mandate(self) -> str:
        body = {
            "principal": {"id": "usr_marta", "display_name": "Marta Silva"},
            "allowed_merchant_ids": ["vuelaya"],
            "allowed_categories": ["travel"],
            "limit": {"minor_units": 20000, "currency": "USD", "scale": 2},
            "ceiling": {"minor_units": 50000, "currency": "USD", "scale": 2},
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "authorities": [
                {
                    "kid": HOLDER_KID,
                    "role": "holder",
                    "public_jwk": self.custody.public_jwk(HOLDER_KID),
                    "allowed_scopes": ["mandate"],
                }
            ],
        }
        # The mandate is born signed: the same key that revokes it below is the key
        # that authorized it to exist, and the trail keeps that signature at position 0.
        body["creation_jws"] = sign_compact_jws(
            mandate_creation_claims(body), self.custody, HOLDER_KID
        )
        response = self.client.post("/mandates", json=body)
        response.raise_for_status()
        return response.json()["mandate_id"]

    def read_token(self) -> str:
        """The holder's authorization to see their own record. Sight is scoped by the
        key, so the id alone stopped being enough to read a person's budget."""
        return sign_compact_jws({"principal_id": "usr_marta"}, self.custody, HOLDER_KID)

    def sign(self, claims: dict) -> str:
        return sign_compact_jws(claims, self.custody, HOLDER_KID)

    def register_card(self, mandate_id: str) -> str:
        """Put a card on the mandate the way a person does: at the processor.

        A mandate is born unfunded — it is authority to spend, not a means of paying —
        and the core refuses a capture whose instrument the mandate does not name. So
        the card is registered before anything is bought, in three calls that never
        carry a number: open the processor's form, read what was left on it, and name
        it on the mandate with the holder's own signature.
        """
        session_scope = {"mandate_id": mandate_id, "scope": "instrument_session"}
        session = self.client.post(
            f"/mandates/{mandate_id}/instrument/session",
            json={"authorization_jws": self.sign(session_scope)},
        )
        session.raise_for_status()
        session_id = session.json()["session_id"]
        card = self.client.get(
            f"/mandates/{mandate_id}/instrument/session/{session_id}",
            headers={"X-Aval-Authorization": self.sign(session_scope)},
        )
        card.raise_for_status()
        registered = card.json()
        if not registered.get("ready"):
            return ""
        bound = self.client.post(
            f"/mandates/{mandate_id}/instrument",
            json={
                "token": registered["token"],
                "label": registered["label"],
                "authorization_jws": self.sign(
                    {
                        "mandate_id": mandate_id,
                        "scope": "instrument",
                        "instrument_token": registered["token"],
                        "instrument_label": registered["label"],
                        # Nothing to supersede: this mandate has never named a card.
                        "supersedes": None,
                    }
                ),
            },
        )
        bound.raise_for_status()
        return bound.json()["instrument_label"]

    def buy(self, mandate_id: str, instruction: str) -> dict:
        return self.client.post(
            "/agent/purchase", json={"mandate_id": mandate_id, "instruction": instruction}
        ).json()

    def run(self) -> int:
        print("\n== AVAL smoke ==\n")
        self.check("health", self.client.get("/health").json()["status"] == "ok")

        mandate_id = self.create_mandate()
        self.check("mandate created", mandate_id.startswith("mandate_"), mandate_id)

        unfunded = self.buy(mandate_id, "buy a flight to Córdoba under $150")
        self.check(
            "a mandate with no card cannot pay",
            unfunded["reason_code"] == "instrument_not_in_mandate",
            unfunded["reason_code"],
        )

        label = self.register_card(mandate_id)
        self.check("the card is registered at the processor", label.startswith("••••"), label)

        bought = self.buy(mandate_id, "buy a flight to Córdoba under $150")
        self.check(
            "agent buys inside the mandate",
            bought["outcome"] == "settled",
            f"{bought['reason_code']} · {bought.get('settlement_reference')}",
        )

        verified = self.client.post(
            "/merchant/verify",
            json={
                "authorization_proof": bought["authorization_proof"],
                "merchant_authorization": bought["offer"]["merchant_authorization"],
            },
        ).json()
        self.check("merchant verification accepts", verified["accepted"] is True)
        raw = str(verified)
        self.check("merchant never sees the mandate", mandate_id not in raw and "usr_marta" not in raw)

        hotel = self.buy(mandate_id, "book a hotel in Córdoba")
        self.check(
            "out of scope escalates instead of passing",
            hotel["outcome"] == "awaiting_human" and hotel["reason_code"] == "category_not_allowed",
            hotel["reason_code"],
        )

        handle = hotel["escalation_id"]
        approval = sign_compact_jws(
            {
                "decision_handle": handle,
                "mandate_id": mandate_id,
                "decision": "approve",
                "amount_minor_units": hotel["offer"]["total"]["minor_units"],
                "decided_at": datetime.now(UTC).isoformat(),
            },
            self.custody,
            HOLDER_KID,
        )
        resumed = self.client.post(
            f"/escalations/{handle}/decision",
            json={"decision": "approve", "approval_jws": approval},
        ).json()
        self.check(
            "a signed approval resumes the purchase",
            resumed["resumed"] and resumed["capture"]["approved"],
            resumed["capture"]["reason_code"],
        )

        stranger = KeyCustodyService()
        stranger.generate_es256("stranger_k1")
        forged_escalation = self.buy(mandate_id, "book a hotel in Córdoba")
        forged = self.client.post(
            f"/escalations/{forged_escalation.get('escalation_id')}/decision",
            json={
                "decision": "approve",
                "approval_jws": sign_compact_jws(
                    {
                        "decision_handle": forged_escalation.get("escalation_id"),
                        "mandate_id": mandate_id,
                        "decision": "approve",
                        "amount_minor_units": 22000,
                        "decided_at": datetime.now(UTC).isoformat(),
                    },
                    stranger,
                    "stranger_k1",
                ),
            },
        )
        self.check(
            "an approval signed by a stranger is refused",
            forged.status_code == 403,
            str(forged.status_code),
        )

        ceiling = self.buy(mandate_id, "buy the business class fare to Córdoba at $900")
        self.check(
            "the ceiling refuses and offers no approval",
            ceiling["reason_code"] == "mandate_ceiling" and ceiling["escalation_id"] is None,
            ceiling["reason_code"],
        )

        unsigned = self.client.patch(
            f"/mandates/{mandate_id}/limit",
            json={"limit": {"minor_units": 100000, "currency": "USD", "scale": 2}},
        )
        self.check(
            "an unsigned limit change is refused",
            unsigned.status_code == 403
            and unsigned.json()["reason_code"] == "limit_change_unsigned",
            str(unsigned.status_code),
        )

        def signed_limit(minor_units: int, policy_version: int) -> str:
            return sign_compact_jws(
                {
                    "mandate_id": mandate_id,
                    "limit_minor_units": minor_units,
                    "currency": "USD",
                    "scale": 2,
                    "policy_version": policy_version,
                },
                self.custody,
                HOLDER_KID,
            )

        def policy_version() -> int:
            return int(
                self.client.get(
                    f"/mandates/{mandate_id}",
                    headers={"X-Aval-Authorization": self.read_token()},
                ).json()["policy_version"]
            )

        before_change = policy_version()
        stale_token = signed_limit(50_000, before_change)
        self.client.patch(
            f"/mandates/{mandate_id}/limit",
            json={
                "limit": {"minor_units": 100, "currency": "USD", "scale": 2},
                "authorization_jws": signed_limit(100, before_change),
            },
        )
        after_change = self.buy(mandate_id, "buy a flight to Buenos Aires")
        self.check(
            "a signed limit change binds the next decision",
            after_change["reason_code"] in ("budget_exceeded", "no_offer_matched"),
            after_change["reason_code"],
        )

        # A limit change is reversible, so its authorization has to be single-use.
        # Without that, anyone who captured the earlier token could undo the holder
        # lowering the budget — which is exactly the move the trial by fire invites.
        replayed = self.client.patch(
            f"/mandates/{mandate_id}/limit",
            json={
                "limit": {"minor_units": 50_000, "currency": "USD", "scale": 2},
                "authorization_jws": stale_token,
            },
        )
        self.check(
            "an old limit authorization cannot be replayed",
            replayed.status_code == 403
            and replayed.json()["reason_code"] == "limit_change_version_stale",
            f"{replayed.status_code} {replayed.json().get('reason_code')}",
        )

        anonymous = httpx.Client(base_url=str(self.client.base_url), timeout=15.0)
        self.check(
            "registering a trusted agent needs the operator token",
            anonymous.post(
                "/agents",
                json={
                    "id": "agent_attacker",
                    "profile_url": "https://evil.example/a",
                    "public_jwk": self.custody.public_jwk(HOLDER_KID),
                    "trusted": True,
                },
            ).status_code
            == 401,
        )
        self.check(
            "the processor switch needs the operator token",
            anonymous.post("/admin/psp", json={"mode": "offline"}).status_code == 401,
        )

        impostor = self.client.post(
            "/authorize",
            json={
                "mandate_id": mandate_id,
                "checkout_id": "chk_impostor",
                "merchant_id": "vuelaya",
                "category": "travel",
                "total": {"minor_units": 1000, "currency": "USD", "scale": 2},
            },
        )
        self.check(
            "an unsigned agent request is refused",
            impostor.status_code == 401
            and impostor.json()["reason_code"] == "signature_missing",
            str(impostor.status_code),
        )

        revocation = sign_compact_jws(
            {"mandate_id": mandate_id, "scope": "mandate", "reason": "smoke", "epoch": 1},
            self.custody,
            HOLDER_KID,
        )
        self.client.post(f"/mandates/{mandate_id}/revocation", json={"token": revocation})
        after_revocation = self.buy(mandate_id, "buy a flight to Córdoba under $150")
        self.check(
            "revocation blocks the next attempt",
            after_revocation["reason_code"] == "mandate_revoked",
            after_revocation["reason_code"],
        )

        human = self.client.get(
            "/ledger",
            params={"mandate_id": mandate_id, "view": "human"},
            headers={"X-Aval-Authorization": self.read_token()},
        ).json()
        merchant = self.client.get(
            "/ledger", params={"merchant_id": "vuelaya", "view": "merchant"}
        ).json()
        auditor = self.client.get(
            "/ledger", params={"mandate_id": mandate_id, "view": "auditor"}
        ).json()
        self.check("human view shows the budget", "remaining" in human["mandate"])
        self.check(
            "merchant view hides the buyer",
            mandate_id not in str(merchant) and "usr_marta" not in str(merchant),
        )
        self.check(
            "auditor chain verifies",
            auditor["chain"]["intact"] is True,
            f"{auditor['chain']['checked']} eventos",
        )

        # Both halves signed: denying a purchase and deciding when the trail answers are
        # said in the holder's name, so they carry the holder's key.
        dispute = self.client.post(
            "/disputes",
            json={
                "reservation_id": bought["reservation_id"],
                "reason": "Eu nunca autorizei isso",
                "authorization_jws": self.read_token(),
            },
        ).json()
        resolution = self.client.post(
            f"/disputes/{dispute['dispute_id']}/resolution",
            json={"authorization_jws": self.read_token()},
        ).json()
        self.check(
            "the trail resolves the dispute",
            resolution["status"] == "MANDATE_HELD",
            resolution["status"],
        )

        print(f"\n{'ALL GREEN' if not self.failures else f'{self.failures} FAILED'}\n")
        return 1 if self.failures else 0


if __name__ == "__main__":
    base = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
    raise SystemExit(Smoke(base).run())
