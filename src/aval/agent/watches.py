"""The agent that keeps working after the conversation ends.

Everything else in this system answers a request. A watch answers nothing until the
world changes — which is the only situation where the case's premise is literally true:
*"your assistant buys your flight when the price drops"*. Nobody is at the keyboard
when this fires.

The split is the same one the proposer already draws. **A watch is a preference; the
mandate is authority.** Registering one authorizes nothing: firing means calling the
very same `/authorize` and `/capture` a person typing would reach, so a standing order
against a revoked mandate is refused exactly like a typed purchase is. The autonomy is
in *when* the agent acts, never in *what it may do*.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from uuid import uuid4

from aval.agent.purchasing_agent import AgentRun, PurchasingAgent
from aval.domain.entities import Watch
from aval.domain.enums import WatchStatus
from aval.infrastructure.sqlite.transaction import run_in_write_transaction
from aval.infrastructure.sqlite.watch_repository import SqliteWatchRepository
from aval.runtime import AvalRuntime

# The one outcome that means "not yet". Everything else is an answer, and an answer
# ends the watch: an agent that kept retrying after a refusal would be an agent
# arguing with the mandate.
STILL_WAITING = "no_offer"


@dataclass(frozen=True)
class WatchOutcome:
    """A watch that stopped waiting, and what the core said about it.

    `run` is None when the watch ended without asking — an expiry is the agent giving
    up, not the mandate refusing, and the two must not read the same on screen.
    """

    watch: Watch
    run: AgentRun | None


class WatchService:
    def __init__(self, runtime: AvalRuntime, *, agent: PurchasingAgent) -> None:
        self._runtime = runtime
        self._agent = agent

    def _now(self) -> datetime:
        return self._runtime.clock.now()

    def register(
        self, *, mandate_id: str, instruction: str, expires_at: datetime | None = None
    ) -> Watch:
        """Start watching. A watch may not outlive the authority it depends on, so the
        mandate's own expiry is both the default and the ceiling."""
        mandate = self._runtime.core.mandate(mandate_id)
        if mandate is None:
            raise ValueError("mandate_not_found")
        deadline = mandate.expires_at if expires_at is None else min(expires_at, mandate.expires_at)
        watch = Watch(
            id=f"wch_{uuid4().hex}",
            mandate_id=mandate_id,
            instruction=instruction,
            created_at=self._now(),
            expires_at=deadline,
        )
        run_in_write_transaction(
            self._runtime.engine, lambda connection: SqliteWatchRepository(connection).create(watch)
        )
        return watch

    def for_mandate(self, mandate_id: str) -> list[Watch]:
        with self._runtime.engine.connect() as connection:
            return SqliteWatchRepository(connection).for_mandate(mandate_id)

    def tick(self, mandate_id: str) -> list[WatchOutcome]:
        """Try every open watch once. Returns only the ones that stopped waiting."""
        with self._runtime.engine.connect() as connection:
            open_watches = SqliteWatchRepository(connection).open_for_mandate(mandate_id)
        outcomes: list[WatchOutcome] = []
        for watch in open_watches:
            if watch.is_expired_at(self._now()):
                # The person said *until the end of the month*. Past that the agent
                # stops looking, and it stops before asking rather than by being
                # refused: an expired watch has nothing to put to the core.
                outcomes.append(
                    WatchOutcome(
                        self._close(watch, status=WatchStatus.EXPIRED, outcome="watch_expired"),
                        None,
                    )
                )
                continue
            run = self._agent.run(mandate_id=watch.mandate_id, instruction=watch.instruction)
            if run.outcome == STILL_WAITING:
                continue
            closed = self._close(
                watch,
                status=WatchStatus.FIRED,
                outcome=run.reason_code,
                settlement_reference=run.settlement_reference,
            )
            outcomes.append(WatchOutcome(closed, run))
        return outcomes

    def _close(
        self,
        watch: Watch,
        *,
        status: WatchStatus,
        outcome: str | None,
        settlement_reference: str | None = None,
    ) -> Watch:
        closed_at = self._now()
        run_in_write_transaction(
            self._runtime.engine,
            lambda connection: SqliteWatchRepository(connection).close(
                watch.id,
                status=status,
                outcome=outcome,
                settlement_reference=settlement_reference,
                closed_at=closed_at,
            ),
        )
        return replace(
            watch,
            status=status,
            outcome=outcome,
            settlement_reference=settlement_reference,
            closed_at=closed_at,
        )
