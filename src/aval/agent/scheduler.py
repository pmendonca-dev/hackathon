"""The clock behind a standing order.

A watch is the one place in this system where the agent acts with nobody at the
keyboard — the case's actual premise, *"your assistant buys your flight when the price
drops"*. But a watch only ever fired when something called `POST /agent/watches/tick`,
and the only caller was the Telegram bot's polling loop. With the bot down, the standing
order sat there: registered, alive, and never asked.

This is the missing half. It is **opt-in**, off unless `AVAL_WATCH_TICK_SECONDS` names
an interval, because a background loop that starts itself is a behaviour change nobody
asked for on the morning of a demo.

It carries no authority whatsoever. Ticking calls the very same `WatchService.tick` the
HTTP route calls, which calls the same `/authorize` and `/capture` a person typing would
reach. A watch that fires against a revoked mandate is refused exactly like a typed
purchase — the autonomy is in *when* the agent acts, never in *what it may do*.
"""

from __future__ import annotations

import asyncio
import logging
import os
from contextlib import suppress

from aval.agent.purchasing_agent import PurchasingAgent
from aval.agent.watches import WatchService
from aval.infrastructure.sqlite.watch_repository import SqliteWatchRepository
from aval.runtime import AvalRuntime

logger = logging.getLogger("aval.watches")

# Below this the loop is a busy-wait against the catalogue rather than a scheduler.
MINIMUM_INTERVAL_SECONDS = 5.0


def configured_tick_interval() -> float | None:
    """The interval the deployment asked for, or None when it asked for nothing."""
    raw = os.environ.get("AVAL_WATCH_TICK_SECONDS", "").strip()
    if not raw:
        return None
    try:
        interval = float(raw)
    except ValueError:
        logger.warning("AVAL_WATCH_TICK_SECONDS=%r is not a number; watches disabled", raw)
        return None
    if interval < MINIMUM_INTERVAL_SECONDS:
        logger.warning(
            "AVAL_WATCH_TICK_SECONDS=%s is too short; using %s",
            interval,
            MINIMUM_INTERVAL_SECONDS,
        )
        return MINIMUM_INTERVAL_SECONDS
    return interval


def tick_once(runtime: AvalRuntime) -> int:
    """Let every open watch try once. Returns how many stopped waiting.

    Synchronous and self-contained so it can be called from a test without a loop.
    """
    with runtime.engine.connect() as connection:
        mandate_ids = SqliteWatchRepository(connection).mandates_with_open_watches()
    if not mandate_ids:
        return 0
    service = WatchService(
        runtime,
        agent=PurchasingAgent(runtime, custody=runtime.agent_custody, kid=runtime.agent_kid),
    )
    fired = 0
    for mandate_id in mandate_ids:
        try:
            fired += len(service.tick(mandate_id))
        except Exception:
            # One mandate's failure must not stop the others. The watch stays open and
            # is tried again next tick, which is the same thing that happens when the
            # catalogue simply has no matching offer yet.
            logger.exception("the watch on mandate %s failed on this tick", mandate_id)
    return fired


async def run_watch_scheduler(runtime: AvalRuntime, *, interval_seconds: float) -> None:
    """Tick forever, off the request path.

    Each tick runs in a worker thread: `tick_once` talks to SQLite and to the agent
    synchronously, and doing that on the event loop would stall every request for as
    long as a purchase takes.
    """
    logger.info("watches active: one tick every %ss", interval_seconds)
    while True:
        await asyncio.sleep(interval_seconds)
        with suppress(asyncio.CancelledError):
            fired = await asyncio.to_thread(tick_once, runtime)
            if fired:
                logger.info("%s watch(es) stopped waiting on this tick", fired)
