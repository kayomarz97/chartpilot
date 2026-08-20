"""A shared, thread-safe token-bucket rate limiter (spec §24, §12A.3).

Every external-evidence adapter (openFDA, PubMed) that shares an outbound
rate limit is expected to share ONE `TokenBucketRateLimiter` instance across
threads/requests within a run. Both the clock and the sleep function are
injected so this can be tested deterministically -- fake time advances only
when the fake `sleep` is called, never for real.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

# Floating-point tolerance for the "do we have enough tokens" comparison.
# Without this, a deficit can shrink below the float precision available at
# the current magnitude of the monotonic clock (e.g. ~1e-16 once the clock
# has advanced past ~1.0), so `tokens + wait_s * rate` never quite reaches
# `n` and `acquire` spins forever recomputing an ever-smaller `wait_s` that
# advances the clock by an amount too small to change its float value at
# all. Accepting a deficit smaller than this epsilon is not a materially
# different rate-limiting contract -- 1e-9s is many orders of magnitude
# below anything an external HTTP call's timing could ever depend on.
_TOKEN_EPSILON = 1e-9


class TokenBucketRateLimiter:
    """Blocks callers until a token is available, refilling at `rate_per_sec`.

    Thread-safe: all state reads/writes happen under an internal `Lock`, and
    the (potentially slow) `sleep` call always happens OUTSIDE the lock so
    one blocked thread never holds up another thread's bookkeeping.
    """

    def __init__(
        self,
        rate_per_sec: float,
        capacity: float | None = None,
        *,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if rate_per_sec <= 0:
            raise ValueError("rate_per_sec must be > 0")
        self._rate = rate_per_sec
        self._capacity = capacity if capacity is not None else rate_per_sec
        if self._capacity <= 0:
            raise ValueError("capacity must be > 0")
        self._monotonic = monotonic
        self._sleep = sleep
        self._lock = threading.Lock()
        self._tokens = self._capacity
        self._last_refill = self._monotonic()

    def _refill_locked(self) -> None:
        """Top up `_tokens` for elapsed time. Caller must hold `_lock`."""
        now = self._monotonic()
        elapsed = now - self._last_refill
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._last_refill = now

    def acquire(self, n: float = 1.0) -> None:
        """Block (via the injected `sleep`) until `n` tokens are available.

        Raises `ValueError` if `n` exceeds the bucket's capacity -- such a
        request could never be satisfied.
        """
        if n <= 0:
            raise ValueError("n must be > 0")
        if n > self._capacity:
            raise ValueError(f"n={n} exceeds bucket capacity={self._capacity}; never satisfiable")

        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= n - _TOKEN_EPSILON:
                    self._tokens = max(0.0, self._tokens - n)
                    return
                wait_s = (n - self._tokens) / self._rate
            self._sleep(wait_s)
