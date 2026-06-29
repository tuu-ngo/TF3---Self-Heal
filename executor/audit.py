"""
Audit logger — ghi tamper-evident theo correlation_id (03_security_design §8).
Target: S3 Object Lock Governance Mode, retention 90 ngày. Luôn echo stdout.

SKELETON: ghi stdout đã chạy; S3 PutObject cần boto3 + bucket thật (W12).
Mỗi incident = 1 chuỗi event; audit fields tối thiểu theo 07_test_eval §11.
"""
from __future__ import annotations

import json
import sys
import time
from typing import Any

from config import CONFIG

# stdout có thể là cp1252 (Windows console) → ép UTF-8 để log JSON chứa ký tự
# non-ASCII (vd reason "≠", tiếng Việt) không làm crash audit.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass

try:
    import boto3
    _HAS_BOTO = True
except ImportError:
    _HAS_BOTO = False

# Các event chuẩn (07_test_eval §11) — dùng làm hằng để tránh typo
ALERT_RECEIVED = "alert_received"
DETECT_CALLED = "detect_called"
DETECT_RESPONSE = "detect_response_received"
PREDECIDE = "pre_decide_decision"
DECIDE_CALLED = "decide_called"
ACTION_PLAN = "action_plan_received"
LOCK_ACQUIRED = "idempotency_lock_acquired"
LOCK_DENIED = "idempotency_duplicate_denied"
SAFETY_PASSED = "safety_passed"
SAFETY_DENIED = "safety_denied"
SNAPSHOT_CAPTURED = "rollback_snapshot_captured"
DRY_RUN_DONE = "dry_run_done"
DRY_RUN_FAILED = "dry_run_failed"
EXECUTE_DONE = "execute_done"
EXECUTE_SKIPPED = "execute_skipped"
VERIFY_CALLED = "verify_called"
VERIFY_DONE = "verify_done"
ROLLBACK_DONE = "rollback_done"
CIRCUIT_OPEN = "circuit_breaker_open"
CIRCUIT_TRIPPED = "circuit_breaker_tripped"
ESCALATED = "escalated"
INCIDENT_CLOSED = "incident_closed"


class AuditLogger:
    def __init__(self, correlation_id: str, tenant_id: str, cfg=CONFIG):
        self.correlation_id = correlation_id
        self.tenant_id = tenant_id
        self.cfg = cfg
        self._events: list[dict[str, Any]] = []
        self._s3 = boto3.client("s3", region_name=cfg.aws_region) if (_HAS_BOTO and cfg.audit_bucket) else None

    def event(self, event_type: str, *, namespace: str | None = None,
              action_type: str | None = None, decision: str | None = None,
              result: str | None = None, reason: str | None = None,
              idempotency_key: str | None = None, **extra: Any) -> None:
        rec = {
            "timestamp": _now_rfc3339(),
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "event": event_type,
            "namespace": namespace,
            "action_type": action_type,
            "decision": decision,
            "result": result,
            "reason": reason,
            "idempotency_key": idempotency_key,
            **extra,
        }
        rec = {k: v for k, v in rec.items() if v is not None}
        self._events.append(rec)
        print(json.dumps(rec, ensure_ascii=False))  # stdout → CloudWatch

    def flush(self) -> None:
        """Ghi toàn bộ chuỗi event của incident thành 1 object bất biến vào S3."""
        if self._s3 is None:
            return
        key = f"audit/{self.tenant_id}/{self.correlation_id}.json"
        body = json.dumps({"correlation_id": self.correlation_id, "events": self._events},
                          ensure_ascii=False).encode("utf-8")
        # Object Lock Governance + retention 90d đã set ở bucket-level (audit/main.tf),
        # nên PutObject thường là đủ; có thể set per-object retention nếu cần.
        self._s3.put_object(Bucket=self.cfg.audit_bucket, Key=key, Body=body,
                            ContentType="application/json")


def _now_rfc3339() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime()) + \
        f".{int((time.time() % 1) * 1000):03d}Z"
