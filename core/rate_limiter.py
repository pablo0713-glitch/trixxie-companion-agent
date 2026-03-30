from __future__ import annotations

import time


class TokenBucket:
    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate  # tokens per second
        self._tokens = float(capacity)
        self._last_refill = time.monotonic()

    def consume(self) -> bool:
        """Attempt to consume one token. Returns True if allowed, False if throttled."""
        self._refill()
        if self._tokens >= 1.0:
            self._tokens -= 1.0
            return True
        return False

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        self._tokens = min(self._capacity, self._tokens + elapsed * self._refill_rate)
        self._last_refill = now


class RateLimiter:
    def __init__(self, capacity: int, refill_rate: float) -> None:
        self._capacity = capacity
        self._refill_rate = refill_rate
        self._buckets: dict[str, TokenBucket] = {}

    def check(self, user_id: str) -> bool:
        """Return True if the request is allowed for this user."""
        if user_id not in self._buckets:
            self._buckets[user_id] = TokenBucket(self._capacity, self._refill_rate)
        return self._buckets[user_id].consume()

    def cleanup_stale(self, idle_seconds: float = 3600.0) -> None:
        """Remove buckets for users inactive longer than idle_seconds."""
        cutoff = time.monotonic() - idle_seconds
        stale = [uid for uid, b in self._buckets.items() if b._last_refill < cutoff]
        for uid in stale:
            del self._buckets[uid]
