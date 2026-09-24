"""A token bucket sized for SEC's published rate ceiling.

Deliberately a simple blocking limiter rather than anything adaptive: EDGAR
answers a burst above the ceiling with a block at the CDN, not a 429, and that
block applies to the source IP for hours. Being conservative and boring here is
worth more than throughput.
"""

from __future__ import annotations

import threading
import time


class TokenBucket:
    """Thread-safe token bucket.

    ``rate`` tokens are added per second up to ``capacity``. ``acquire`` blocks
    until a token is available, so callers need no retry logic of their own.
    """

    def __init__(self, rate: float, capacity: float | None = None) -> None:
        if rate <= 0:
            raise ValueError("rate must be positive")
        self.rate = rate
        # A one-second burst allowance: enough to absorb scheduling jitter,
        # small enough that we never present more than `rate` over any second.
        self.capacity = capacity if capacity is not None else rate
        self._tokens = self.capacity
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until ``tokens`` are available. Returns seconds spent waiting."""
        if tokens > self.capacity:
            raise ValueError(f"cannot acquire {tokens} tokens from a bucket of {self.capacity}")
        waited = 0.0
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(self.capacity, self._tokens + (now - self._updated) * self.rate)
                self._updated = now
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                sleep_for = deficit / self.rate
            time.sleep(sleep_for)
            waited += sleep_for

    @property
    def available(self) -> float:
        with self._lock:
            now = time.monotonic()
            return min(self.capacity, self._tokens + (now - self._updated) * self.rate)
