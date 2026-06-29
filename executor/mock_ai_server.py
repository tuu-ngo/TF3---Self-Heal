"""
Mock AI endpoint — trả JSON đúng schema contract-new-4 cho /v1/detect, /v1/decide, /v1/verify.
Dùng để CDO integrate + test code path TRƯỚC khi AI team bàn giao image thật (W12 T3).
Chỉ stdlib, không cần dependency.

SCENARIO-DRIVEN: mock đọc `labels.scenario` trong telemetry để quyết định nhánh trả về,
cho phép 1 mock phục vụ ≥10 scenario khác nhau (run_scenarios.py + đo auto-resolve rate).
  - /v1/detect : đọc telemetry_window[0].labels.scenario
  - /v1/decide : đọc anomaly_context.suspected_fault_type (= scenario, do detect set)
  - /v1/verify : đọc post_telemetry_window[0].labels.scenario

Chạy:  python mock_ai_server.py            # listen :8080
Trỏ:   export AI_BASE_URL=http://127.0.0.1:8080
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer

# scenario → action urgent (PATCH memory)
_PATCH_MEM = {"oom_kill", "oom_kill_b", "memory_pressure", "oom_persist"}
# scenario → ROLLOUT_UNDO
_ROLLOUT = {"bad_deploy"}
# verify trả ROLLBACK (regression sau khi heal)
_VERIFY_ROLLBACK = {"oom_persist"}
# verify trả ESCALATE
_VERIFY_ESCALATE = {"verify_escalate"}


def _scenario_of(telemetry: list | None, default: str = "default") -> str:
    if telemetry and isinstance(telemetry, list):
        return (telemetry[0] or {}).get("labels", {}).get("scenario", default)
    return default


def _detect(req: dict, cid: str) -> dict:
    tw = req.get("telemetry_window") or [{}]
    labels = (tw[0] or {}).get("labels", {})
    sc = labels.get("scenario", "default")
    low = sc == "low_conf"
    return {
        "anomaly_detected": True,
        "severity": 0.30 if low else 0.85,
        "confidence": 0.55 if low else 0.92,
        "reasoning": f"mock detect scenario={sc}",
        "correlation_id": cid,
        "anomaly_context": {
            "target_service": (tw[0] or {}).get("service", "svc"),
            "suspected_fault_type": sc,   # mang scenario key sang /v1/decide
            "system": labels.get("system", "K8S_NATIVE"),
            "namespace": labels.get("namespace", "tenant-a"),
            "deployment": labels.get("deployment", "cdo-sample-api"),
            "trigger_metric": (tw[0] or {}).get("signal_name"),
            "trigger_value": (tw[0] or {}).get("value"),
        },
    }


def _decide(req: dict, cid: str, idem: str) -> dict:
    ctx = req.get("anomaly_context", {})
    sc = ctx.get("suspected_fault_type", "default")
    ns = ctx.get("namespace", "tenant-a")
    dep = ctx.get("deployment", "cdo-sample-api")

    if sc in _PATCH_MEM:
        action, pattern, params, allowed = (
            "PATCH_MEMORY_LIMIT", "urgent",
            {"namespace": ns, "container": "main", "memory_limit_mb": 1024}, [ns])
        runbook = "OOMPatchMemoryRunbook"
    elif sc in _ROLLOUT:
        action, pattern, params, allowed = (
            "ROLLOUT_UNDO", "urgent", {"namespace": ns}, [ns])
        runbook = "BadDeployRollbackRunbook"
    elif sc == "scale_capacity":
        action, pattern, params, allowed = (
            "SCALE_REPLICAS", "deferred", {"namespace": ns, "replicas": 4}, [ns])
        runbook = "CapacityScaleRunbook"
    elif sc == "cross_tenant":
        # cố tình target namespace KHÁC incident → safety gate phải chặn (deny cross-tenant)
        action, pattern, params, allowed = (
            "RESTART_DEPLOYMENT", "urgent", {"namespace": "tenant-b"}, ["tenant-b"])
        runbook = "ServiceStuckRestartRunbook"
    elif sc == "unsafe_action":
        # action ngoài allow-list → safety gate phải chặn (denied_action_not_allowed)
        action, pattern, params, allowed = (
            "DELETE_NAMESPACE", "urgent", {"namespace": ns}, [ns])
        runbook = "n/a"
    else:  # crashloop / latency / default → restart
        action, pattern, params, allowed = (
            "RESTART_DEPLOYMENT", "urgent", {"namespace": ns}, [ns])
        runbook = "ServiceStuckRestartRunbook"

    return {
        "matched_runbook": runbook,
        "pattern_type": pattern,
        "action_plan": [{"step": 1, "action": action,
                         "target": f"deployment/{dep}", "params": params}],
        "blast_radius_config": {
            "max_pod_impact_pct": 25, "circuit_breaker_error_rate": 0.20,
            "allowed_namespaces": allowed,
        },
        "verify_policy": {"window_seconds": 120,
                          "success_conditions": ["pod_ready == true"]},
        "correlation_id": cid, "idempotency_key": idem,
        "dry_run_mode": req.get("dry_run_mode", False),
        "cost_cap_exceeded": False,
    }


def _verify(req: dict) -> dict:
    sc = _scenario_of(req.get("post_telemetry_window"))
    if sc in _VERIFY_ROLLBACK:
        return {"success": False, "regression_detected": True, "next_action": "ROLLBACK"}
    if sc in _VERIFY_ESCALATE:
        return {"success": False, "regression_detected": False, "next_action": "ESCALATE",
                "escalation_bundle": {
                    "reason": "Sau RESTART, error_rate vẫn vượt ngưỡng — AI không tự xử được.",
                    "logs": ["app: connection pool exhausted", "app: 503 upstream"],
                    "metrics": {"error_rate": 0.42, "p95_latency_ms": 3100},
                }}
    return {"success": True, "regression_detected": False, "next_action": "DONE"}


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        cid = req.get("correlation_id") or "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
        idem = req.get("idempotency_key", "d3b07384-d113-495f-9f58-20d18d357d75")

        if self.path == "/v1/detect":
            body = _detect(req, cid)
        elif self.path == "/v1/decide":
            body = _decide(req, cid, idem)
        elif self.path == "/v1/verify":
            body = _verify(req)
        else:
            self.send_response(404)
            self.end_headers()
            return

        payload = json.dumps(body).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # tắt log mặc định cho gọn
        pass


if __name__ == "__main__":
    print("mock AI on http://127.0.0.1:8080 (Ctrl-C to stop)")
    HTTPServer(("127.0.0.1", 8080), Handler).serve_forever()
