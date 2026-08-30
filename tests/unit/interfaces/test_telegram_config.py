"""What the bot demands from its environment before it agrees to run.

The edge secrets are the only new thing here that can open a hole: they authenticate
Computer B's private endpoints, and an unset variable reads as an empty string that
both sides would happily agree on. So the interesting cases are all refusals.
"""

from __future__ import annotations

import pytest

from aval.interfaces.telegram.config import BotConfig, ConfigError

BASE = {"TELEGRAM_BOT_TOKEN": "tok", "AVAL_API_BASE_URL": "http://127.0.0.1:8099"}


def test_a_single_machine_deployment_needs_no_edge_secrets() -> None:
    """The default is one computer, where there is no hop to authenticate."""
    assert BotConfig.from_env(BASE).edge is None


def test_edge_mode_remote_carries_both_direction_secrets() -> None:
    config = BotConfig.from_env(
        {
            **BASE,
            "AVAL_EDGE_MODE": "remote",
            "AVAL_EDGE_TO_CORE_SECRET": "a-to-b",
            "AVAL_CORE_TO_EDGE_SECRET": "b-to-a",
        }
    )
    assert config.edge is not None
    assert config.edge.edge_to_core_secret == "a-to-b"
    assert config.edge.core_to_edge_secret == "b-to-a"


@pytest.mark.parametrize(
    "env",
    [
        {"AVAL_EDGE_MODE": "remote"},
        {"AVAL_EDGE_MODE": "remote", "AVAL_EDGE_TO_CORE_SECRET": "a-to-b"},
        {"AVAL_EDGE_MODE": "remote", "AVAL_CORE_TO_EDGE_SECRET": "b-to-a"},
        {
            "AVAL_EDGE_MODE": "remote",
            "AVAL_EDGE_TO_CORE_SECRET": "   ",
            "AVAL_CORE_TO_EDGE_SECRET": "b-to-a",
        },
    ],
)
def test_a_remote_deployment_missing_a_secret_refuses_to_boot(env: dict[str, str]) -> None:
    with pytest.raises(ConfigError):
        BotConfig.from_env({**BASE, **env})


def test_the_two_directions_may_not_share_one_secret() -> None:
    """Reusing one value means a leaked discovery credential also reads the outbox."""
    with pytest.raises(ConfigError):
        BotConfig.from_env(
            {
                **BASE,
                "AVAL_EDGE_MODE": "remote",
                "AVAL_EDGE_TO_CORE_SECRET": "same",
                "AVAL_CORE_TO_EDGE_SECRET": "same",
            }
        )
