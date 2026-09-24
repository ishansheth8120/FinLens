from __future__ import annotations

import time

import pytest

from finlens.ingest.ratelimit import TokenBucket


def test_bucket_allows_an_initial_burst_up_to_capacity():
    bucket = TokenBucket(rate=10, capacity=5)
    started = time.monotonic()
    for _ in range(5):
        bucket.acquire()
    # The bucket starts full, so the first `capacity` acquisitions are free.
    assert time.monotonic() - started < 0.05


def test_bucket_throttles_beyond_capacity():
    bucket = TokenBucket(rate=20, capacity=2)
    for _ in range(2):
        bucket.acquire()

    started = time.monotonic()
    bucket.acquire()
    elapsed = time.monotonic() - started
    # One extra token at 20/s costs ~50ms.
    assert elapsed >= 0.03


def test_bucket_refills_over_time():
    bucket = TokenBucket(rate=100, capacity=2)
    bucket.acquire()
    bucket.acquire()
    time.sleep(0.05)
    assert bucket.available > 1.0


def test_rejects_non_positive_rate():
    with pytest.raises(ValueError):
        TokenBucket(rate=0)


def test_rejects_acquiring_more_than_capacity():
    bucket = TokenBucket(rate=10, capacity=2)
    with pytest.raises(ValueError, match="cannot acquire"):
        bucket.acquire(5)
