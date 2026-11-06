"""In-memory sliding-window rate limiting for the auth brute-force surface.

State is per-process and resets on restart. That is the right tool for slowing
brute force on a single instance; a distributed deployment would need a shared
store behind the same interface.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque

from app.core.config import get_settings


class SlidingWindowRateLimiter:
    """A sliding-window limiter keyed by an arbitrary string (e.g. ``route:ip``)."""

    def __init__(self, max_attempts: int, window_seconds: int) -> None:
        if max_attempts <= 0:
            raise ValueError("max_attempts must be positive")
        if window_seconds <= 0:
            raise ValueError("window_seconds must be positive")
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    @staticmethod
    def _prune(hits: deque[float], now: float, window_seconds: int) -> None:
        cutoff = now - window_seconds
        while hits and hits[0] <= cutoff:
            hits.popleft()

    def allow(self, key: str) -> bool:
        """Record an attempt for ``key`` and return whether it is within the limit."""
        now = time.monotonic()
        with self._lock:
            hits = self._hits[key]
            self._prune(hits, now, self.window_seconds)
            if len(hits) >= self.max_attempts:
                return False
            hits.append(now)
            return True

    def reset(self) -> None:
        """Forget every recorded attempt (used to isolate tests)."""
        with self._lock:
            self._hits.clear()


_auth_limiter: SlidingWindowRateLimiter | None = None
_auth_limiter_lock = threading.Lock()


def get_auth_rate_limiter() -> SlidingWindowRateLimiter:
    """Return the process-wide auth rate limiter, built from settings on first use."""
    global _auth_limiter
    if _auth_limiter is None:
        with _auth_limiter_lock:
            if _auth_limiter is None:
                settings = get_settings()
                _auth_limiter = SlidingWindowRateLimiter(
                    max_attempts=settings.auth_rate_limit_max_attempts,
                    window_seconds=settings.auth_rate_limit_window_seconds,
                )
    return _auth_limiter


def reset_auth_rate_limiter() -> None:
    """Clear the process-wide auth rate limiter (used by tests)."""
    get_auth_rate_limiter().reset()
