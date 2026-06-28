"""
Pre-Decide Gate — chạy SAU /v1/detect, TRƯỚC /v1/decide (02_infra_design §5 step 5).
Trả lời: "có nên để hệ thống tự xử lý không?" dựa trên confidence/severity/flapping/maintenance.
Nguyên tắc: CDO KHÔNG filter theo fault_type — AI tự trả confidence thấp nếu không match pattern.
"""
from __future__ import annotations

import time
from collections import defaultdict, deque
from dataclasses import dataclass

from config import CONFIG
from models import DetectResponse

# Quyết định của gate
PROCEED = "proceed_to_decide"
NO_ANOMALY = "no_anomaly"
LOW_CONF_DISCARD = "low_confidence_discard"
LOW_CONF_NO_ACTION = "low_confidence_no_action"
LOW_CONF_ESCALATE = "low_confidence_escalated"
FLAPPING_ESCALATE = "flapping_escalated"
MAINTENANCE_SUPPRESS = "maintenance_suppressed"

_HIGH_SEVERITY = 0.7  # severity >= 0.7 coi là HIGH/CRITICAL (0..1 theo contract)


@dataclass
class GateResult:
    decision: str
    proceed: bool
    escalate: bool


class FlapTracker:
    """Đếm số lần 1 service bị detect trong cửa sổ trượt (mặc định 10 phút)."""
    def __init__(self, window_s: int = CONFIG.flap_window_seconds):
        self.window_s = window_s
        self._hits: dict[str, deque[float]] = defaultdict(deque)

    def record_and_count(self, service_key: str, now: float | None = None) -> int:
        now = now or time.time()
        dq = self._hits[service_key]
        dq.append(now)
        cutoff = now - self.window_s
        while dq and dq[0] < cutoff:
            dq.popleft()
        return len(dq)


def evaluate(detect: DetectResponse, flap: FlapTracker,
             maintenance_active: bool = False, cfg=CONFIG) -> GateResult:
    if maintenance_active:
        return GateResult(MAINTENANCE_SUPPRESS, proceed=False, escalate=False)

    if not detect.anomaly_detected:
        return GateResult(NO_ANOMALY, proceed=False, escalate=False)

    conf, sev = detect.confidence, detect.severity
    is_high = sev >= _HIGH_SEVERITY

    # confidence < 0.5 → noise, discard
    if conf < cfg.confidence_discard_below:
        return GateResult(LOW_CONF_DISCARD, proceed=False, escalate=False)

    # 0.5 <= confidence < 0.8 → tùy severity
    if conf < cfg.confidence_execute_at:
        if is_high:
            return GateResult(LOW_CONF_ESCALATE, proceed=False, escalate=True)
        return GateResult(LOW_CONF_NO_ACTION, proceed=False, escalate=False)

    # confidence >= 0.8 → check flapping trước khi proceed
    svc = _service_key(detect)
    if flap.record_and_count(svc) >= cfg.flap_threshold:
        return GateResult(FLAPPING_ESCALATE, proceed=False, escalate=True)

    return GateResult(PROCEED, proceed=True, escalate=False)


def _service_key(detect: DetectResponse) -> str:
    ctx = detect.anomaly_context
    if ctx and ctx.namespace and ctx.target_service:
        return f"{ctx.namespace}/{ctx.target_service}"
    return ctx.target_service if ctx else "unknown"
