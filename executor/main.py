"""
CDO Self-Heal Executor — vòng điều phối chính (orchestration loop).

    alert → /v1/detect → Pre-Decide Gate → [lock] → /v1/decide → Safety Gate
    → capture snapshot → execute (dry-run trước nếu urgent) → /v1/verify
    → xử next_action (DONE/RETRY/ROLLBACK/ESCALATE) → audit

Fail-safe nguyên tắc: bất kỳ điểm nào không chắc chắn → KHÔNG execute, escalate + audit.

Day-1 run:
    python main.py scenarios/tc01_service_stuck.json
(mock K8s/AWS khi chưa cài kubernetes/boto3 — vẫn chạy hết loop để test logic)
"""
from __future__ import annotations

import json
import sys

import audit as A
import snapshot as S
from ai_client import AIClient, new_uuid
from config import CONFIG
from errors import AIConflict, AIError, SafetyDenied
from executors import pick
from idempotency import IdempotencyLock
from k8s_client import K8sClient
from models import DetectResponse
from pre_decide_gate import FlapTracker, evaluate
from safety_gate import check as safety_check


class Executor:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self.ai = AIClient(cfg)
        self.locks = IdempotencyLock(cfg)
        self.flap = FlapTracker()
        self.k8s = K8sClient(in_cluster=False)

    def handle_incident(self, telemetry_window: list[dict],
                        tenant_namespace: str,
                        correlation_id: str | None = None) -> str:
        """
        Xử lý 1 incident end-to-end. Trả về terminal state (machine-readable).
        tenant_namespace = namespace của incident (CDO biết từ alert source).
        """
        correlation_id = correlation_id or new_uuid()
        log = A.AuditLogger(correlation_id, self.cfg.tenant_id, self.cfg)
        log.event(A.ALERT_RECEIVED, namespace=tenant_namespace)

        try:
            # ---------- [1] DETECT ----------
            log.event(A.DETECT_CALLED)
            detect: DetectResponse = self.ai.detect(telemetry_window, correlation_id)
            correlation_id = detect.correlation_id or correlation_id
            log.event(A.DETECT_RESPONSE, result="ok",
                      anomaly=detect.anomaly_detected, confidence=detect.confidence,
                      severity=detect.severity)

            # ---------- [1.5] PRE-DECIDE GATE ----------
            gate = evaluate(detect, self.flap)
            log.event(A.PREDECIDE, decision=gate.decision)
            if not gate.proceed:
                if gate.escalate:
                    return self._escalate(log, tenant_namespace, gate.decision)
                log.event(A.INCIDENT_CLOSED, result="no_action", reason=gate.decision)
                return gate.decision

            # ---------- [2] DECIDE (idempotency lock trước) ----------
            idem_key = new_uuid()
            if not self.locks.acquire(idem_key):
                log.event(A.LOCK_DENIED, idempotency_key=idem_key)
                return A.LOCK_DENIED
            log.event(A.LOCK_ACQUIRED, idempotency_key=idem_key)

            log.event(A.DECIDE_CALLED, idempotency_key=idem_key)
            decide = self.ai.decide(detect.anomaly_context, correlation_id, idem_key)
            first = decide.action_plan[0] if decide.action_plan else None
            log.event(A.ACTION_PLAN, action_type=first.action if first else None,
                      pattern_type=decide.pattern_type, runbook=decide.matched_runbook,
                      cost_cap_exceeded=decide.cost_cap_exceeded)

            # cost_cap_exceeded: vẫn execute, chỉ log cảnh báo (TC-17)
            if decide.cost_cap_exceeded:
                log.event("cost_cap_exceeded_warning", reason="ai_rule_based_fallback")

            # ---------- [3] SAFETY GATE ----------
            try:
                verdict = safety_check(decide, self.cfg.tenant_id, tenant_namespace)
            except SafetyDenied as d:
                log.event(A.SAFETY_DENIED, decision="deny", reason=d.reason,
                          action_type=first.action if first else None, detail=d.detail)
                return self._escalate(log, tenant_namespace, d.reason)
            log.event(A.SAFETY_PASSED, decision="allow",
                      checks=",".join(verdict.checks_passed))

            # ---------- [4] SNAPSHOT + EXECUTE ----------
            snap = S.capture(decide, self.k8s)
            log.event(A.SNAPSHOT_CAPTURED, namespace=first.namespace,
                      snapshot_type=snap.pattern_type)

            executor = pick(decide)
            result = executor.execute(decide)
            if result.status != "COMPLETED":
                log.event(A.EXECUTE_DONE, result="failed", action_type=result.action,
                          detail=result.detail)
                return self._escalate(log, tenant_namespace, "execute_failed")
            log.event(A.EXECUTE_DONE, result="success", action_type=result.action,
                      namespace=first.namespace, target=result.target)

            # ---------- [5] VERIFY ----------
            post_window = self._collect_post_telemetry(decide, telemetry_window)
            log.event(A.VERIFY_CALLED)
            verify = self.ai.verify(result.to_action_executed(), post_window,
                                    correlation_id, idem_key)
            log.event(A.VERIFY_DONE, result="ok", next_action=verify.next_action,
                      success=verify.success, regression=verify.regression_detected)

            # ---------- [6] NEXT ACTION ----------
            return self._handle_next_action(log, verify, decide, snap, executor, tenant_namespace)

        except AIConflict:
            log.event(A.LOCK_DENIED, reason="ai_409_conflict")
            return A.LOCK_DENIED
        except AIError as e:
            # 400/401/403/500/503/timeout → fail-safe escalate, KHÔNG execute
            return self._escalate(log, tenant_namespace, e.audit_reason)
        finally:
            log.flush()

    # ---------- helpers ----------

    def _handle_next_action(self, log, verify, decide, snap, executor, ns) -> str:
        na = verify.next_action
        if na == "DONE":
            log.event(A.INCIDENT_CLOSED, result="auto_resolved")
            return "auto_resolved"
        if na == "RETRY":
            log.event("retrying", reason="verify_retry")
            return "retry"  # MVP: caller re-inject; W12 có thể loop tại đây
        if na == "ROLLBACK":
            rb = executor.rollback(decide, snap)
            log.event(A.ROLLBACK_DONE, result=rb.status.lower(), action_type=rb.action)
            return "rolled_back"
        # ESCALATE
        return self._escalate(log, ns, "verify_escalate",
                              bundle=verify.escalation_bundle)

    def _escalate(self, log, ns, reason, bundle=None) -> str:
        # TODO(W12): gửi escalation_bundle lên Slack/mock pager
        log.event(A.ESCALATED, namespace=ns, reason=reason, decision="escalate",
                  escalation_bundle=bundle)
        return f"escalated:{reason}"

    def _collect_post_telemetry(self, decide, telemetry_window) -> list[dict]:
        # TODO(W12): chờ verify_policy.window_seconds rồi scrape post-action telemetry.
        # Offline/Mock Mode: lấy post_telemetry_window từ dataset RE2/RE3.
        return telemetry_window


def main() -> None:
    if len(sys.argv) < 2:
        print("usage: python main.py <scenario.json>", file=sys.stderr)
        sys.exit(2)
    with open(sys.argv[1], encoding="utf-8") as f:
        scenario = json.load(f)
    outcome = Executor().handle_incident(
        telemetry_window=scenario["telemetry_window"],
        tenant_namespace=scenario["tenant_namespace"],
        correlation_id=scenario.get("correlation_id"),
    )
    print(f"\n>>> OUTCOME: {outcome}")


if __name__ == "__main__":
    main()
