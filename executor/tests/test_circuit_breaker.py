"""Unit test cho CircuitBreaker (safety sub-checkpoint #5)."""
from __future__ import annotations

from circuit_breaker import CircuitBreaker


class _Cfg:
    circuit_fail_threshold = 3
    circuit_window_s = 300
    circuit_cooldown_s = 300


def _cb():
    return CircuitBreaker(_Cfg())


def test_closed_by_default():
    cb = _cb()
    assert cb.is_open(now=1000.0) is False


def test_trips_at_threshold():
    cb = _cb()
    assert cb.record_failure(now=1000.0) is False  # 1
    assert cb.record_failure(now=1001.0) is False  # 2
    assert cb.record_failure(now=1002.0) is True   # 3 → trip
    assert cb.is_open(now=1003.0) is True


def test_failures_outside_window_dont_trip():
    cb = _cb()
    cb.record_failure(now=1000.0)
    cb.record_failure(now=1100.0)
    # cách >window so với 2 lần đầu → 2 lần đầu rớt khỏi cửa sổ
    assert cb.record_failure(now=1500.0) is False
    assert cb.is_open(now=1500.0) is False


def test_success_resets_counter():
    cb = _cb()
    cb.record_failure(now=1000.0)
    cb.record_failure(now=1001.0)
    cb.record_success(now=1002.0)
    assert cb.record_failure(now=1003.0) is False  # counter đã reset → chưa đủ threshold
    assert cb.is_open(now=1003.0) is False


def test_half_open_after_cooldown():
    cb = _cb()
    cb.record_failure(now=1000.0)
    cb.record_failure(now=1001.0)
    cb.record_failure(now=1002.0)
    assert cb.is_open(now=1002.0) is True
    # trước hết cooldown → vẫn open
    assert cb.is_open(now=1002.0 + 299) is True
    # sau cooldown → half-open (reset về closed, cho thử lại)
    assert cb.is_open(now=1002.0 + 300) is False
