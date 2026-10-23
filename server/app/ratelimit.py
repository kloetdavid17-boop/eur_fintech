"""Tiny in-memory sliding-window rate limiter.

PER PROCESS ONLY: counters live in this worker's memory, reset on restart and are not shared
between workers/instances. That is fine for an MVP on a single Render instance; a multi-instance
deployment should move this to Redis (or the database).
"""

import time
from collections import defaultdict, deque


class RateLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def _prune(self, key: str, window: float, now: float) -> deque[float]:
        q = self._hits[key]
        while q and now - q[0] > window:
            q.popleft()
        if not q:
            self._hits.pop(key, None)
            return deque()
        return q

    def is_limited(self, key: str, max_hits: int, window: float) -> bool:
        q = self._prune(key, window, time.monotonic())
        return len(q) >= max_hits

    def hit(self, key: str, window: float) -> None:
        now = time.monotonic()
        self._prune(key, window, now)
        self._hits[key].append(now)

    def check_and_hit(self, key: str, max_hits: int, window: float) -> bool:
        """Record a hit; return True if the caller is now OVER the limit."""
        if self.is_limited(key, max_hits, window):
            return True
        self.hit(key, window)
        return False

    def reset(self, key: str | None = None) -> None:
        if key is None:
            self._hits.clear()
        else:
            self._hits.pop(key, None)


limiter = RateLimiter()
