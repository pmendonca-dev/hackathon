"""End-to-end smoke run of the Telegram lane against a live server.

    AVAL_OPERATOR_TOKEN=demo-token uvicorn aval.main:app --port 8099
    python scripts/telegram_smoke.py http://127.0.0.1:8099

The browser lane has `live-browser-journey.mjs` and the HTTP lane has `smoke_demo.py`.
The bot lane had neither: its 39 tests all drive a fake opener, so nothing proved the
gateway spoke to a real server. That matters more here than anywhere else, because the
demo opens on Telegram and the whole trial by fire is judges typing into the bot.

This drives the *real* `AvalGateway` over real HTTP with a real per-chat holder key —
the same objects the bot process uses, minus the Telegram polling loop, which is the
one part that needs a bot token and a network nobody controls. Everything the bot does
to AVAL is exercised here; everything Telegram does to the bot is not.
"""

from __future__ import annotations

import sys
import tempfile
from datetime import timedelta
from pathlib import Path

from aval.interfaces.telegram.gateway import AvalGateway, GatewayError, MoneyView
from aval.interfaces.telegram.identity import IdentityStore


CHAT_ID = 424242
USD = lambda minor: MoneyView(minor, "USD", 2)  # noqa: E731 - a table of amounts reads better


class Smoke:
    def __init__(self, base_url: str) -> None:
        self.store = IdentityStore(Path(tempfile.mkdtemp()) / "identities.json")
        self.gateway = AvalGateway(base_url, identities=self.store)
        self.failures = 0

    def check(self, label: str, ok: bool, detail: str = "") -> None:
        mark = "  ok  " if ok else " FAIL "
        suffix = f" - {detail}" if detail else ""
        print(f"[{mark}] {label}{suffix}")
        if not ok:
            self.failures += 1

    def run(self) -> int:
        print("\n== AVAL telegram smoke ==\n")

        self.check("health", self.gateway.health() == "ok")

        # /start — the chat mints its own P-256 key and a mandate in its own name.
        identity = self.store.enrol(CHAT_ID, "Marta Silva")
        mandate_id = self.gateway.create_mandate(
            identity,
            merchants=["vuelaya"],
            categories=["travel"],
            limit=USD(20_000),
            ceiling=USD(50_000),
            valid_for=timedelta(days=7),
        )
        identity = self.store.bind_mandate(CHAT_ID, mandate_id)
        self.check("/start cria chave do chat e mandato", bool(mandate_id), mandate_id)

        mandate = self.gateway.mandate(mandate_id)
        self.check(
            "o mandato volta com orçamento vivo",
            mandate is not None and mandate.limit.minor_units == 20_000,
            f"limite {mandate.limit.minor_units}" if mandate else "sem mandato",
        )

        # The holder key is the chat's own. Nobody else can revoke this mandate.
        self.check(
            "a chave que assina é a do chat, não a do servidor",
            mandate is not None and self.store.public_jwk(identity)["kid"] == identity.kid,
            identity.kid,
        )

        offers = self.gateway.catalogue()
        self.check("/catalogo lista ofertas assinadas", len(offers) > 0, f"{len(offers)} ofertas")

        # /comprar — inside the mandate.
        bought = self.gateway.purchase(mandate_id, "compre um voo para Córdoba abaixo de $150")
        self.check(
            "/comprar dentro do mandato liquida",
            bought.outcome == "settled",
            f"{bought.outcome} · {bought.reason_code}",
        )
        self.check(
            "o recibo diz quem escolheu e por quê",
            bought.proposed_by in ("rules", "llm"),
            f"proposto por {bought.proposed_by}",
        )

        # /comprar — outside the mandate. Escalates rather than passing.
        hotel = self.gateway.purchase(mandate_id, "reserve um hotel em Córdoba")
        self.check(
            "fora do escopo escala em vez de passar",
            hotel.outcome != "settled" and hotel.escalation_id is not None,
            hotel.reason_code,
        )

        # The approve button, signed by the chat's key.
        pending = self.gateway.open_escalations(mandate_id)
        self.check("a escalação aparece na lista", len(pending) >= 1, f"{len(pending)} aberta(s)")
        if pending:
            message = self.gateway.decide(identity, pending[0], approve=True)
            self.check("Aprovar assina com a chave do chat e retoma", bool(message), message[:60])

        # The ceiling refuses with no button at all.
        executive = self.gateway.purchase(mandate_id, "compre a passagem executiva de $900")
        self.check(
            "o teto recusa e não abre escalação",
            executive.reason_code == "mandate_ceiling" and executive.escalation_id is None,
            executive.reason_code,
        )

        # /limite — holder-signed, and single-use since the replay fix.
        before = self.gateway.mandate(mandate_id)
        stale = self.store.sign(
            identity,
            {
                "mandate_id": mandate_id,
                "limit_minor_units": 50_000,
                "currency": "USD",
                "scale": 2,
                "policy_version": before.policy_version,
            },
        )
        moved = self.gateway.replace_limit(identity, mandate_id, USD(10_000))
        self.check("/limite muda o orçamento vivo", bool(moved), moved)

        replayed = "aceito"
        try:
            self.gateway._call(  # noqa: SLF001 - deliberately bypassing the fresh read
                "PATCH",
                f"/mandates/{mandate_id}/limit",
                body={
                    "limit": {"minor_units": 50_000, "currency": "USD", "scale": 2},
                    "authorization_jws": stale,
                },
            )
        except GatewayError as error:
            replayed = error.reason_code
        self.check(
            "uma autorização de limite antiga não é reaproveitada",
            replayed == "limit_change_version_stale",
            replayed,
        )

        # /extrato — what the human gets back.
        receipt = self.gateway.receipt(mandate_id)
        self.check(
            "/extrato traz o registro do que foi comprado",
            len(receipt.entries) > 0 and receipt.mandate.id == mandate_id,
            f"{len(receipt.entries)} eventos",
        )

        # A second chat is a different holder, and cannot touch the first one.
        other = self.store.enrol(999_111, "Jurado 2")
        other_mandate = self.gateway.create_mandate(
            other,
            merchants=["vuelaya"],
            categories=["travel"],
            limit=USD(20_000),
            ceiling=USD(50_000),
            valid_for=timedelta(days=7),
        )
        stolen = "aceito"
        try:
            self.gateway.revoke(other, mandate_id, epoch=0, reason="não é meu")
        except GatewayError as error:
            stolen = error.reason_code
        self.check(
            "um jurado não revoga o mandato do outro",
            stolen != "aceito",
            stolen,
        )
        self.check(
            "cada chat carrega o próprio mandato",
            other_mandate != mandate_id,
            f"{other_mandate[:24]}...",
        )

        # /revogar — signed, irreversible, and the next attempt fails.
        revoked = self.gateway.revoke(identity, mandate_id, epoch=0, reason="fim do teste")
        self.check("/revogar assina e encerra o mandato", bool(revoked), revoked)

        after = self.gateway.purchase(mandate_id, "compre um voo para Córdoba")
        self.check(
            "depois da revogação a próxima compra falha",
            after.reason_code == "mandate_revoked",
            after.reason_code,
        )

        print()
        if self.failures:
            print(f"{self.failures} PASSO(S) FALHARAM")
            return 1
        print("ALL GREEN")
        return 0


def main() -> int:
    base_url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8099"
    return Smoke(base_url).run()


if __name__ == "__main__":
    sys.exit(main())
