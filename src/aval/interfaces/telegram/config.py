"""Bot configuration. Privileged surfaces are fail-closed unless opened on purpose."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import timedelta
from pathlib import Path


class ConfigError(Exception):
    """The environment cannot produce a usable bot."""


@dataclass(frozen=True)
class MandateDefaults:
    """What a fresh mandate authorizes when someone says /start.

    These are the numbers the demo script tells: a live budget, a ceiling nobody
    crosses, travel at VuelaYa. They are configurable because a judge moving them
    mid-demo is the point, not an accident.
    """

    merchants: tuple[str, ...]
    categories: tuple[str, ...]
    currency: str
    scale: int
    limit_minor_units: int
    ceiling_minor_units: int | None
    valid_for: timedelta
    # The case's "up to 3 times a month", as a rolling window. Frequency is authority
    # over *how often*, next to the budget's *how much* — so it ships on by default
    # instead of being a feature only the API can reach.
    max_uses: int | None
    usage_window: timedelta


@dataclass(frozen=True)
class EdgeCredentials:
    """The two transport secrets between Computer A and Computer B.

    They authenticate a *hop*, never a purchase. Nothing signed with either can create
    a mandate, authorize a spend or capture a payment — that authority is a holder's
    ES256 JWS and lives on B alone — so both computers holding both secrets costs
    nothing. The directions are kept apart anyway, so that a compromise of the public
    discovery endpoint cannot also drain the event outbox.
    """

    # A signs, B verifies: watch commands, event polling, acknowledgement.
    edge_to_core_secret: str
    # B signs, A verifies: the discovery call that reaches the open web.
    core_to_edge_secret: str


@dataclass(frozen=True)
class BotConfig:
    token: str
    api_base_url: str
    allowed_chat_ids: frozenset[int]
    open_mode: bool
    identity_path: Path
    mandate_defaults: MandateDefaults
    poll_timeout_seconds: int
    request_timeout_seconds: int
    escalation_poll_seconds: int
    # None on a single machine, where A and B are the same process and there is no hop
    # to authenticate. Present only when the deployment said the halves are apart.
    edge: EdgeCredentials | None

    def may_act(self, chat_id: int) -> bool:
        """Open mode is safe here: each chat holds its own key and its own mandate,
        so a stranger can only ever move their own authority."""
        return self.open_mode or chat_id in self.allowed_chat_ids

    @classmethod
    def from_env(cls, env: Mapping[str, str]) -> "BotConfig":
        token = env.get("TELEGRAM_BOT_TOKEN", "").strip()
        if not token:
            raise ConfigError("TELEGRAM_BOT_TOKEN é obrigatório")
        base_url = env.get("AVAL_API_BASE_URL", "http://127.0.0.1:8099").strip().rstrip("/")
        if not base_url:
            raise ConfigError("AVAL_API_BASE_URL cannot be empty")
        currency = env.get("AVAL_MANDATE_CURRENCY", "USD").strip().upper()
        if len(currency) != 3:
            raise ConfigError("AVAL_MANDATE_CURRENCY deve ser um código ISO de três letras")
        return cls(
            token=token,
            api_base_url=base_url,
            allowed_chat_ids=_chat_ids(env.get("TELEGRAM_ALLOWED_CHAT_IDS", "")),
            open_mode=env.get("TELEGRAM_OPEN_MODE", "").strip().lower() in {"1", "true", "yes"},
            identity_path=Path(
                env.get("TELEGRAM_IDENTITY_PATH", "").strip() or "var/telegram-identities.json"
            ),
            mandate_defaults=MandateDefaults(
                merchants=_csv(env.get("AVAL_MANDATE_MERCHANTS", "vuelaya")),
                categories=_csv(env.get("AVAL_MANDATE_CATEGORIES", "travel")),
                currency=currency,
                scale=_positive_int(env, "AVAL_MANDATE_SCALE", 2, allow_zero=True),
                limit_minor_units=_positive_int(env, "AVAL_MANDATE_LIMIT_MINOR_UNITS", 20_000),
                ceiling_minor_units=_optional_int(env, "AVAL_MANDATE_CEILING_MINOR_UNITS", 50_000),
                valid_for=timedelta(days=_positive_int(env, "AVAL_MANDATE_VALID_DAYS", 30)),
                max_uses=_optional_int(env, "AVAL_MANDATE_MAX_USES", 3),
                usage_window=timedelta(
                    days=_positive_int(env, "AVAL_MANDATE_USAGE_WINDOW_DAYS", 30)
                ),
            ),
            poll_timeout_seconds=_positive_int(env, "TELEGRAM_POLL_TIMEOUT_SECONDS", 30),
            request_timeout_seconds=_positive_int(env, "AVAL_REQUEST_TIMEOUT_SECONDS", 15),
            escalation_poll_seconds=_positive_int(env, "AVAL_ESCALATION_POLL_SECONDS", 8),
            edge=_edge_credentials(env),
        )


def _edge_credentials(env: Mapping[str, str]) -> EdgeCredentials | None:
    """The secrets for the two-computer split, demanded only when it was asked for.

    Fail-closed by omission: `AVAL_EDGE_MODE=remote` is the deployment saying the
    halves are on different machines, and a remote deployment missing a secret must
    refuse to boot. Signing with an empty string would "work" on both sides and leave
    B's private endpoints open to anyone who found the port.
    """
    if env.get("AVAL_EDGE_MODE", "").strip().lower() != "remote":
        return None
    edge_to_core = env.get("AVAL_EDGE_TO_CORE_SECRET", "").strip()
    core_to_edge = env.get("AVAL_CORE_TO_EDGE_SECRET", "").strip()
    missing = [
        name
        for name, value in (
            ("AVAL_EDGE_TO_CORE_SECRET", edge_to_core),
            ("AVAL_CORE_TO_EDGE_SECRET", core_to_edge),
        )
        if not value
    ]
    if missing:
        raise ConfigError(f"AVAL_EDGE_MODE=remote exige {' e '.join(missing)}")
    if edge_to_core == core_to_edge:
        # One secret for both directions means a captured discovery credential also
        # reads the outbox. The whole point of two is that they are two.
        raise ConfigError(
            "AVAL_EDGE_TO_CORE_SECRET e AVAL_CORE_TO_EDGE_SECRET devem ser diferentes"
        )
    return EdgeCredentials(edge_to_core_secret=edge_to_core, core_to_edge_secret=core_to_edge)


def _csv(raw: str) -> tuple[str, ...]:
    return tuple(item.strip() for item in raw.split(",") if item.strip())


def _chat_ids(raw: str) -> frozenset[int]:
    ids: set[int] = set()
    for item in raw.replace(";", ",").split(","):
        candidate = item.strip()
        if not candidate:
            continue
        try:
            ids.add(int(candidate))
        except ValueError as error:
            raise ConfigError(
                f"TELEGRAM_ALLOWED_CHAT_IDS has a non-numeric id: {candidate!r}"
            ) from error
    return frozenset(ids)


def _positive_int(
    env: Mapping[str, str], name: str, default: int, *, allow_zero: bool = False
) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise ConfigError(f"{name} deve ser inteiro") from error
    if value < 0 or (value == 0 and not allow_zero):
        raise ConfigError(f"{name} deve ser positivo")
    return value


def _optional_int(env: Mapping[str, str], name: str, default: int) -> int | None:
    raw = env.get(name, "").strip()
    if raw.lower() in {"none", "off"}:
        return None
    return _positive_int(env, name, default)
