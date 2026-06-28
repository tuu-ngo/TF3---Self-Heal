"""
Mock AI endpoint — trả JSON đúng schema contract-new-4 cho /v1/detect, /v1/decide, /v1/verify.
Dùng để CDO integrate + test code path TRƯỚC khi AI team bàn giao image thật (W12 T3).
Chỉ stdlib, không cần dependency.

Chạy:  python mock_ai_server.py            # listen :8080
Trỏ:   export AI_BASE_URL=http://127.0.0.1:8080
"""
from __future__ import annotations

import json
from http.server import BaseHTTPRequestHandler, HTTPServer


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length", 0))
        req = json.loads(self.rfile.read(length) or b"{}")
        cid = req.get("correlation_id") or "9b1deb4d-3b7d-4bad-9bdd-2b0d7b3dcb6d"
        idem = req.get("idempotency_key", "d3b07384-d113-495f-9f58-20d18d357d75")

        if self.path == "/v1/detect":
            body = {
                "anomaly_detected": True, "severity": 0.85, "confidence": 0.92,
                "reasoning": "service_latency_p95 vượt ngưỡng + readiness probe fail.",
                "correlation_id": cid,
                "anomaly_context": {
                    "target_service": "checkout-svc",
                    "suspected_fault_type": "service_unhealthy",
                    "system": "E-COMMERCE",
                    "namespace": "tenant-a",
                    "deployment": "cdo-sample-api",
                    "trigger_metric": "service_latency_p95",
                    "trigger_value": 1850.0,
                },
            }
        elif self.path == "/v1/decide":
            body = {
                "matched_runbook": "ServiceStuckRestartRunbook",
                "pattern_type": "urgent",
                "action_plan": [{
                    "step": 1, "action": "RESTART_DEPLOYMENT",
                    "target": "deployment/cdo-sample-api",
                    "params": {"namespace": "tenant-a", "grace_period_seconds": 30},
                }],
                "blast_radius_config": {
                    "max_pod_impact_pct": 25, "circuit_breaker_error_rate": 0.20,
                    "allowed_namespaces": ["tenant-a"],
                },
                "verify_policy": {"window_seconds": 120,
                                  "success_conditions": ["pod_ready == true"]},
                "correlation_id": cid, "idempotency_key": idem,
                "dry_run_mode": req.get("dry_run_mode", False),
                "cost_cap_exceeded": False,
            }
        elif self.path == "/v1/verify":
            body = {"success": True, "regression_detected": False, "next_action": "DONE"}
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
