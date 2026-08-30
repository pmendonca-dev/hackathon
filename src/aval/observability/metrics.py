"""The two things the trail cannot know about itself.

Every decision this system makes is already in the hash-chained ledger, so counting
decisions in a second place would create a tally that can disagree with the trail —
and when a panel and an audit log disagree, neither is evidence any more. Decision
counts are therefore aggregated *from* the ledger, in `AuthorizationCore`.

What the ledger genuinely cannot hold is here:

- **how long a decision took**, which is not a fact about authority at all; and
- **requests refused at the edge**, which never became decisions. A replayed signature
  is turned away before the mandate is read, so there is nothing to write against a
  mandate — and that refusal is exactly the number a judge attacking the system wants
  to watch move.

Both are per process and are lost on restart. That is the honest scope of an in-memory
counter, and neither is evidence of anything: they are instrumentation.
"""

from __future__ import annotations

from collections import Counter, deque
from threading import Lock
from typing import ClassVar


class LatencyWindow:
    """A bounded window of recent durations, in milliseconds.

    Bounded on purpose: an unbounded list is a memory leak that only shows up during
    the long demo, which is the worst possible moment for it to show up.
    """

    def __init__(self, capacity: int = 512) -> None:
        self._samples: deque[float] = deque(maxlen=capacity)
        self._seen = 0

    def record(self, milliseconds: float) -> None:
        self._samples.append(milliseconds)
        self._seen += 1

    def snapshot(self) -> dict[str, float | int]:
        if not self._samples:
            return {"count": 0, "p50": 0.0, "p99": 0.0, "max": 0.0}
        ordered = sorted(self._samples)
        return {
            "count": self._seen,
            "p50": round(_percentile(ordered, 0.50), 3),
            "p99": round(_percentile(ordered, 0.99), 3),
            "max": round(ordered[-1], 3),
        }


def _percentile(ordered: list[float], fraction: float) -> float:
    """Nearest-rank, so a small window never reports a value nobody measured."""
    index = max(0, min(len(ordered) - 1, round(fraction * len(ordered)) - 1))
    return ordered[index]


class MetricsRegistry:
    """Instrumentation for one process. Thread-safe because uvicorn is not single
    threaded and a torn counter during a live demo is worse than no counter."""

    #: Routes worth timing, and nothing else — timing every path buries the numbers
    #: anyone actually asks about.
    #:
    #: `/agent/purchase` is here because it is the route a judge presses. The agent
    #: inside it reaches the core in process rather than over HTTP, so timing only the
    #: two machine lanes leaves the footer reading almost nothing during the live demo,
    #: which is precisely when the number is being looked at.
    TIMED_PATHS: ClassVar[dict[str, str]] = {
        "/authorize": "authorize",
        "/capture": "capture",
        "/agent/purchase": "agent_purchase",
    }

    def __init__(self) -> None:
        self._lock = Lock()
        self._edge_refusals: Counter[str] = Counter()
        self._latency = {name: LatencyWindow() for name in self.TIMED_PATHS.values()}

    def refused_at_edge(self, reason_code: str) -> None:
        with self._lock:
            self._edge_refusals[reason_code] += 1

    def timed(self, path: str, milliseconds: float) -> None:
        name = self.TIMED_PATHS.get(path)
        if name is None:
            return
        with self._lock:
            self._latency[name].record(milliseconds)

    def snapshot(self) -> dict[str, object]:
        with self._lock:
            return {
                "edge_refusals": dict(self._edge_refusals),
                "latency_ms": {
                    name: window.snapshot() for name, window in self._latency.items()
                },
            }
