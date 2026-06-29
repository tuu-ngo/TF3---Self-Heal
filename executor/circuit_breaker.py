"""
Circuit Breaker — safety sub-checkpoint #5/5.
(5 mandatory: dry-run · blast-radius · verify post-act · auto rollback · circuit breaker)

Mục đích: khi tự-heal LIÊN TỤC thất bại (execute fail / verify ESCALATE / AI unavailable)
trong cửa sổ ngắn → "trip" breaker → mọi incident kế tiếp bị escalate thẳng cho con người,
KHÔNG execute, cho tới khi hết cooldown. Tránh vòng lặp tự-heal hỏng làm tình hình tệ hơn.

Trạng thái: closed (bình thường) → open (đã trip, chặn execute) → half-open (hết cooldown,
cho phép thử lại 1 lần; thành công → đóng, thất bại → mở lại).
"""
from __future__ import annotations

import time
from collections import deque

from config import CONFIG


class CircuitBreaker:
    def __init__(self, cfg=CONFIG):
        self.threshold = cfg.circuit_fail_threshold
        self.window_s = cfg.circuit_window_s
        self.cooldown_s = cfg.circuit_cooldown_s
        self._failures: deque[float] = deque()
        self._opened_at: float | None = None

    def is_open(self, now: float | None = None) -> bool:
        """True nếu breaker đang chặn execute. Tự chuyển half-open khi hết cooldown."""
        now = now or time.time()
        if self._opened_at is None:
            return False
        if now - self._opened_at >= self.cooldown_s:
            # hết cooldown → half-open: reset counter, cho phép incident kế tiếp thử lại
            self._opened_at = None
            self._failures.clear()
            return False
        return True

    def record_failure(self, now: float | None = None) -> bool:
        """Ghi 1 lần tự-heal thất bại. Trả True nếu lần này khiến breaker trip."""
        now = now or time.time()
        self._failures.append(now)
        cutoff = now - self.window_s
        while self._failures and self._failures[0] < cutoff:
            self._failures.popleft()
        if self._opened_at is None and len(self._failures) >= self.threshold:
            self._opened_at = now
            return True
        return False

    def record_success(self, now: float | None = None) -> None:
        """1 lần heal thành công → xả counter, giữ breaker đóng."""
        self._failures.clear()

    @property
    def state(self) -> str:
        return "open" if self.is_open() else "closed"
