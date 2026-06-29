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
import time

import audit as A
import escalation as E
import snapshot as S
import watcher as W
from ai_client import AIClient, new_uuid
from circuit_breaker import CircuitBreaker
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
        self.breaker = CircuitBreaker(cfg)
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
        ctx = E.IncidentContext(correlation_id=correlation_id, tenant_id=self.cfg.tenant_id,
                                namespace=tenant_namespace, telemetry_window=telemetry_window)

        try:
            # ---------- [1] DETECT ----------
            log.event(A.DETECT_CALLED)
            detect: DetectResponse = self.ai.detect(telemetry_window, correlation_id)
            correlation_id = detect.correlation_id or correlation_id
            ctx.correlation_id = correlation_id
            ctx.detect = detect
            log.event(A.DETECT_RESPONSE, result="ok",
                      anomaly=detect.anomaly_detected, confidence=detect.confidence,
                      severity=detect.severity)

            # ---------- [1.5] PRE-DECIDE GATE ----------
            gate = evaluate(detect, self.flap)
            log.event(A.PREDECIDE, decision=gate.decision)
            if not gate.proceed:
                if gate.escalate:
                    return self._escalate(log, ctx, gate.decision)
                log.event(A.INCIDENT_CLOSED, result="no_action", reason=gate.decision)
                return gate.decision

            # ---------- [1.6] CIRCUIT BREAKER (safety sub-checkpoint #5) ----------
            if self.breaker.is_open():
                log.event(A.CIRCUIT_OPEN, decision="escalate",
                          reason="too_many_recent_failures")
                return self._escalate(log, ctx, "circuit_breaker_open")

            # ---------- [2] DECIDE (idempotency lock trước) ----------
            idem_key = new_uuid()
            if not self.locks.acquire(idem_key):
                log.event(A.LOCK_DENIED, idempotency_key=idem_key)
                return A.LOCK_DENIED
            log.event(A.LOCK_ACQUIRED, idempotency_key=idem_key)

            log.event(A.DECIDE_CALLED, idempotency_key=idem_key)
            decide = self.ai.decide(detect.anomaly_context, correlation_id, idem_key)
            ctx.decide = decide
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
                return self._escalate(log, ctx, d.reason)
            log.event(A.SAFETY_PASSED, decision="allow",
                      checks=",".join(verdict.checks_passed))

            # ---------- [4] SNAPSHOT + EXECUTE ----------
            snap = S.capture(decide, self.k8s)
            ctx.snapshot = snap
            log.event(A.SNAPSHOT_CAPTURED, namespace=first.namespace,
                      snapshot_type=snap.pattern_type)

            executor = pick(decide)
            result = executor.execute(decide)
            ctx.result = result
            if result.status != "COMPLETED":
                log.event(A.EXECUTE_DONE, result="failed", action_type=result.action,
                          detail=result.detail)
                if self.breaker.record_failure():
                    log.event(A.CIRCUIT_TRIPPED, reason="execute_failed")
                return self._escalate(log, ctx, "execute_failed")
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
            return self._handle_next_action(log, ctx, verify, executor)

        except AIConflict:
            log.event(A.LOCK_DENIED, reason="ai_409_conflict")
            return A.LOCK_DENIED
        except AIError as e:
            # 400/401/403/500/503/timeout → fail-safe escalate, KHÔNG execute
            if self.breaker.record_failure():
                log.event(A.CIRCUIT_TRIPPED, reason="ai_error")
            return self._escalate(log, ctx, e.audit_reason)
        finally:
            log.flush()

    # ---------- helpers ----------

    def _handle_next_action(self, log, ctx, verify, executor) -> str:
        na = verify.next_action
        if na == "DONE":
            self.breaker.record_success()
            log.event(A.INCIDENT_CLOSED, result="auto_resolved")
            return "auto_resolved"
        if na == "RETRY":
            log.event("retrying", reason="verify_retry")
            return "retry"  # MVP: caller re-inject; W12 có thể loop tại đây
        if na == "ROLLBACK":
            rb = executor.rollback(ctx.decide, ctx.snapshot)
            log.event(A.ROLLBACK_DONE, result=rb.status.lower(), action_type=rb.action)
            return "rolled_back"
        # ESCALATE — tự-heal không thành công, tính là failure cho circuit breaker
        if self.breaker.record_failure():
            log.event(A.CIRCUIT_TRIPPED, reason="verify_escalate")
        # verify path: AI trả escalation_bundle → CDO merge thêm context local
        return self._escalate(log, ctx, "verify_escalate",
                              ai_bundle=verify.escalation_bundle)

    def _escalate(self, log, ctx, reason, ai_bundle=None) -> str:
        """
        Assemble bundle {reason, logs, metrics} đầy đủ (req #8) rồi escalate.
        Mọi đường escalate đều đi qua đây → luôn có bundle, không còn None.
        """
        bundle = E.assemble_bundle(reason, ctx, k8s=self.k8s, ai_bundle=ai_bundle)
        log.event(A.ESCALATED, namespace=ctx.namespace, reason=reason, decision="escalate",
                  escalation_bundle=bundle)
        self._deliver_escalation(log, ctx, reason, bundle)
        return f"escalated:{reason}"

    def _deliver_escalation(self, log, ctx, reason, bundle) -> None:
        """
        Gửi bundle tới kênh trực ban. Có webhook (CDO_ESCALATION_WEBHOOK) → POST;
        không có → mock pager (chỉ audit). Transport là việc của CDO, không phải AI.
        """
        url = getattr(self.cfg, "escalation_webhook_url", "")
        if not url:
            log.event("escalation_delivered", reason=reason, channel="mock_pager")
            return
        try:
            import requests
            requests.post(url, json={"correlation_id": ctx.correlation_id,
                                     "reason": reason, "bundle": bundle}, timeout=3)
            log.event("escalation_delivered", reason=reason, channel="webhook")
        except Exception as e:  # delivery fail không được làm hỏng loop
            log.event("escalation_delivery_failed", reason=reason, detail=str(e))

    def _collect_post_telemetry(self, decide, telemetry_window) -> list[dict]:
        """
        Chờ verify_policy.window_seconds (cap CDO_VERIFY_MAX_WAIT_S) cho action ổn định,
        rồi scrape lại telemetry hiện tại của deployment đã tác động.
        Mock mode (không cluster) → trả window gốc để Offline test vẫn chạy hết loop.
        """
        if not self.k8s.enabled:
            return telemetry_window
        first = decide.action_plan[0]
        _, _, deployment = first.target.partition("/")  # "deployment/<name>"
        wait_s = min(decide.verify_policy.window_seconds, self.cfg.verify_max_wait_s)
        time.sleep(wait_s)
        fresh = W.scrape_deployment_telemetry(self.k8s, first.namespace, deployment, self.cfg)
        return fresh or telemetry_window


def watch_loop(cfg=CONFIG) -> None:
    """
    Production mode: poll pod status mỗi CDO_POLL_INTERVAL_S giây → trigger heal loop.
    Cooldown CDO_HEAL_COOLDOWN_S (default 5 phút) tránh trigger lại cùng deployment liên tục.

    Chạy: python main.py --watch
    """
    executor = Executor(cfg)
    cooldown: dict[str, float] = {}  # "ns/deployment" → monotonic time lần heal gần nhất
    print(f"[watcher] poll={cfg.poll_interval_s}s "
          f"cooldown={cfg.heal_cooldown_s}s "
          f"namespaces={list(cfg.tenant_namespaces)}")
    while True:
        now = time.monotonic()
        for ev in W.collect_fault_events(executor.k8s, cfg.tenant_namespaces, cfg):
            key = f"{ev.namespace}/{ev.deployment}"
            if now - cooldown.get(key, 0.0) < cfg.heal_cooldown_s:
                print(f"[watcher] {key} trong cooldown, bỏ qua")
                continue
            print(f"[watcher] phát hiện {ev.suspected_fault_type} tại {key}")
            outcome = executor.handle_incident(ev.telemetry_window, ev.namespace)
            print(f"[watcher] {key} → {outcome}")
            cooldown[key] = time.monotonic()
        time.sleep(cfg.poll_interval_s)


def main() -> None:
    if len(sys.argv) >= 2 and sys.argv[1] == "--watch":
        watch_loop()
        return
    if len(sys.argv) < 2:
        print("usage: python main.py <scenario.json>  |  python main.py --watch",
              file=sys.stderr)
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
