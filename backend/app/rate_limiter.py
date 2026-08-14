"""Simple in-memory sliding-window rate limiter.

Sufficient for single-worker uvicorn (preview and small-scale production).
For multi-worker deployments, replace with Redis-backed limiter.
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock


class RateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, list[float]] = defaultdict(list)
        self._lock = Lock()

    def allow(self, key: str, *, limit: int, window_seconds: int) -> bool:
        """Return True if the request is allowed, False if rate-limited."""
        now = time.monotonic()
        cutoff = now - window_seconds
        with self._lock:
            bucket = self._buckets[key]
            # Drop expired entries
            self._buckets[key] = [ts for ts in bucket if ts > cutoff]
            if len(self._buckets[key]) >= limit:
                return False
            self._buckets[key].append(now)
            return True

    def cleanup(self, max_age_seconds: int = 3600) -> None:
        """Remove stale buckets to bound memory. Call periodically if needed."""
        now = time.monotonic()
        cutoff = now - max_age_seconds
        with self._lock:
            stale = [k for k, v in self._buckets.items() if not v or v[-1] < cutoff]
            for k in stale:
                del self._buckets[k]
