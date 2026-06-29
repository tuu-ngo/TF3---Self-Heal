"""
Escalation bundle assembler — thoả hard requirement #8 "context bundle đầy đủ".

Schema bundle bám đúng ai-api-contract §3 (/v1/verify escalation_bundle):
    { "reason": str, "logs": [str], "metrics": {object} }

- Đường verify→ESCALATE: AI trả escalation_bundle (reason/logs/metrics) → CDO MERGE thêm
  context local cho đầy đủ.
- Mọi đường escalate KHÁC (safety-deny, AI-unavailable, circuit-open, flapping, execute-failed):
  contract giao CDO tự lo (§4 mã 503: "CDO bắt buộc có luồng fallback nội bộ ... gửi thẳng
  escalation cho SRE"). CDO assemble bundle từ context đã thu trong incident.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# reason_code → mô tả người đọc được
_REASON_TEXT: dict[str, str] = {
    "denied_cross_tenant": "Safety Gate từ chối: target nằm ngoài tenant của sự cố (cross-tenant).",
    "denied_action_not_allowed": "Safety Gate từ chối: action không thuộc allow-list.",
    "scale_to_zero_denied": "Safety Gate từ chối: không cho phép scale về 0 replica.",
    "blast_radius_exceeded": "Safety Gate từ chối: vượt giới hạn blast-radius.",
    "missing_verify_policy": "Safety Gate từ chối: AI không trả verify_policy.",
    "missing_rollback_path": "Safety Gate từ chối: thiếu đường rollback / action_plan rỗng.",
    "invalid_pattern_type": "Safety Gate từ chối: pattern_type không hợp lệ.",
    "circuit_breaker_open": "Circuit breaker đang MỞ: quá nhiều lần tự-heal thất bại gần đây, "
                            "tạm dừng hành động tự động cho tới khi hết cooldown.",
    "execute_failed": "Thực thi hành động khắc phục thất bại.",
    "flapping_escalated": "Service flapping: bị detect lặp lại nhiều lần trong cửa sổ trượt.",
    "low_confidence_escalated": "Confidence thấp nhưng severity cao → cần người quyết định.",
    "verify_escalate": "Sau khắc phục, /v1/verify xác định sự cố CHƯA được giải quyết.",
}


@dataclass
class IncidentContext:
    """Gom state của 1 incident để assemble bundle ở bất kỳ điểm escalate nào."""
    correlation_id: str
    tenant_id: str
    namespace: str
    telemetry_window: list[dict] = field(default_factory=list)
    detect: Any = None      # DetectResponse | None
    decide: Any = None      # DecideResponse | None
    result: Any = None      # ExecutionResult | None
    snapshot: Any = None    # RollbackSnapshot | None


def assemble_bundle(reason_code: str, ctx: IncidentContext,
                    k8s=None, ai_bundle: dict | None = None) -> dict:
    """Trả bundle {reason, logs, metrics}. Nếu có ai_bundle (verify path) → merge."""
    cdo = _cdo_bundle(reason_code, ctx, k8s)
    if not ai_bundle:
        return cdo
    return {
        "reason": ai_bundle.get("reason") or cdo["reason"],
        "logs": list(ai_bundle.get("logs", [])) + cdo["logs"],
        "metrics": {**cdo["metrics"], **(ai_bundle.get("metrics") or {})},
    }


# ---------- internals ----------

def _cdo_bundle(reason_code: str, ctx: IncidentContext, k8s) -> dict:
    return {
        "reason": _reason_text(reason_code),
        "logs": _logs(ctx, k8s),
        "metrics": _metrics(reason_code, ctx),
    }


def _reason_text(code: str) -> str:
    if code in _REASON_TEXT:
        return _REASON_TEXT[code]
    if code.startswith("ai_"):
        return f"AI Engine không phục vụ được ({code}); CDO escalate trực tiếp cho SRE (fallback nội bộ §4)."
    return f"Tự-heal dừng, lý do: {code}"


def _logs(ctx: IncidentContext, k8s) -> list[str]:
    logs: list[str] = []
    if ctx.detect is not None:
        logs.append(
            f"detect: anomaly={ctx.detect.anomaly_detected} "
            f"conf={ctx.detect.confidence} sev={ctx.detect.severity} :: {ctx.detect.reasoning}"
        )
    if ctx.decide is not None and getattr(ctx.decide, "action_plan", None):
        a = ctx.decide.action_plan[0]
        logs.append(f"action_attempted: {a.action} target={a.target} "
                    f"runbook={ctx.decide.matched_runbook} pattern={ctx.decide.pattern_type}")
    if ctx.result is not None:
        logs.append(f"execute_result: status={ctx.result.status} detail={ctx.result.detail}")
    if ctx.snapshot is not None:
        logs.append(f"rollback_snapshot: type={ctx.snapshot.pattern_type} "
                    f"at={ctx.snapshot.captured_at}")
    logs.extend(_pod_logs(ctx, k8s))
    return logs


def _pod_logs(ctx: IncidentContext, k8s) -> list[str]:
    """Best-effort: kéo log pod thật (RBAC có pods/log get). Mock/lỗi → []."""
    if k8s is None or not getattr(k8s, "enabled", False):
        return []
    dep = None
    if ctx.decide is not None and getattr(ctx.decide, "action_plan", None):
        _, _, dep = ctx.decide.action_plan[0].target.partition("/")
    if not dep:
        return []
    try:
        return k8s.get_recent_pod_logs(ctx.namespace, dep, tail_lines=20)
    except Exception:
        return []


def _metrics(reason_code: str, ctx: IncidentContext) -> dict:
    m: dict[str, Any] = {
        "correlation_id": ctx.correlation_id,
        "namespace": ctx.namespace,
        "escalation_reason_code": reason_code,
    }
    if ctx.detect is not None:
        m["confidence"] = ctx.detect.confidence
        m["severity"] = ctx.detect.severity
        c = ctx.detect.anomaly_context
        if c is not None:
            m["suspected_fault_type"] = c.suspected_fault_type
            if c.trigger_metric:
                m[c.trigger_metric] = c.trigger_value
    return m
