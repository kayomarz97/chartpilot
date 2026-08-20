"""Tests for `app.evidence.throttle.TokenBucketRateLimiter`.

Two guarantees are proven here:
  (a) rate-holding, DETERMINISTICALLY -- a fake clock/sleep pair (sleep
      advances the clock, nothing ever touches a real clock) proves K
      acquires at rate R take >= (K-1)/R simulated seconds.
  (b) thread-safety -- many real threads acquiring concurrently never cause
      the limiter to issue more tokens than `capacity + rate * elapsed`
      allows, proven via acquire-completion timestamps recorded under a
      `Lock`.
"""

from __future__ import annotations

import threading
import time

import pytest

from app.evidence.throttle import TokenBucketRateLimiter


class FakeClock:
    """A fake monotonic clock that only advances when `sleep` is called."""

    def __init__(self) -> None:
        self.now = 0.0
        self.sleep_calls: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleep_calls.append(seconds)
        self.now += seconds


def test_rate_holding_is_deterministic_with_fake_clock() -> None:
    clock = FakeClock()
    rate = 5.0
    limiter = TokenBucketRateLimiter(
        rate_per_sec=rate,
        capacity=1.0,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    k = 10
    for _ in range(k):
        limiter.acquire()

    # K acquires at rate R must take >= (K-1)/R simulated seconds: the first
    # acquire is free (bucket starts full), each subsequent one must wait
    # for a full token to refill. A 1e-9s tolerance matches the limiter's
    # own `_TOKEN_EPSILON` (see throttle.py) -- floats accumulated across
    # many refill/consume cycles can land a few ULPs under the exact bound
    # without the limiter having skipped any real waiting.
    assert clock.now >= (k - 1) / rate - 1e-9
    # And it must not have waited dramatically more than necessary either.
    assert clock.now <= (k - 1) / rate + 1e-6


def test_never_sleeps_when_tokens_are_available() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_sec=10.0, capacity=5.0, monotonic=clock.monotonic, sleep=clock.sleep
    )

    for _ in range(5):
        limiter.acquire()

    assert clock.sleep_calls == []
    assert clock.now == 0.0


def test_acquire_rejects_non_positive_n() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(rate_per_sec=1.0, monotonic=clock.monotonic, sleep=clock.sleep)
    with pytest.raises(ValueError):
        limiter.acquire(0)


def test_acquire_rejects_n_exceeding_capacity() -> None:
    clock = FakeClock()
    limiter = TokenBucketRateLimiter(
        rate_per_sec=1.0, capacity=2.0, monotonic=clock.monotonic, sleep=clock.sleep
    )
    with pytest.raises(ValueError):
        limiter.acquire(3.0)


def test_thread_safety_never_over_issues_tokens() -> None:
    """Many real threads hammer `acquire` concurrently; the limiter must
    never let more tokens through than `capacity + rate * elapsed` allows.
    """
    rate = 200.0
    capacity = 5.0
    limiter = TokenBucketRateLimiter(rate_per_sec=rate, capacity=capacity)

    start = time.monotonic()
    timestamps: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        limiter.acquire()
        completed_at = time.monotonic()
        with lock:
            timestamps.append(completed_at)

    threads = [threading.Thread(target=worker) for _ in range(40)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(timestamps) == 40, "all threads must eventually acquire a token"

    timestamps.sort()
    # At any point in time t (an acquire-completion timestamp), the number
    # of tokens issued by then can never exceed capacity + rate*elapsed --
    # that is the entire contract of a token bucket. A small epsilon
    # absorbs floating point / scheduling jitter, never a correctness gap.
    epsilon = 1e-3
    for i, t in enumerate(timestamps, start=1):
        elapsed = t - start
        max_allowed = capacity + rate * elapsed + epsilon
        assert i <= max_allowed, (
            f"over-issue detected: {i} tokens issued by elapsed={elapsed:.4f}s "
            f"but only {max_allowed:.4f} were allowed"
        )
