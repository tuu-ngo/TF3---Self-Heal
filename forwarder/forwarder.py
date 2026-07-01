"""
Alert Forwarder — cầu nối Alertmanager → SQS (telemetry-contract §2.5.C "collector ghi SQS").

Luồng: Prometheus alert rule fire → Alertmanager POST /alerts → forwarder chuẩn hóa mỗi
alert thành telemetry signal (alert_map) → SendMessage vào SQS buffer. Executor đọc SQS
(executor/sqs_source.py) rồi chạy vòng detect→decide→verify.

KHÔNG gọi AI, KHÔNG chạm K8s. Chỉ stdlib + boto3.

ENV:
  CDO_TELEMETRY_QUEUE_URL  (bắt buộc) — SQS queue nhận telemetry
  AWS_REGION               (default us-east-1)
  CDO_TENANT_ID            (default tenant CDO-02)
  FORWARDER_PORT           (default 8080)

Endpoints: POST /alerts (Alertmanager webhook) · GET /health · GET /ready
Chạy:  python forwarder.py
"""
from __future__ import annotations

import json
import os
from http.server import BaseHTTPRequestHandler, HTTPServer

from alert_map import alerts_to_signals
from scrub import scrub_signal

REGION = os.environ.get("AWS_REGION", "us-east-1")
QUEUE_URL = os.environ.get("CDO_TELEMETRY_QUEUE_URL", "")
TENANT_ID = os.environ.get("CDO_TENANT_ID", "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c")
PORT = int(os.environ.get("FORWARDER_PORT", "8080"))

try:
    import boto3
    _sqs = boto3.client("sqs", region_name=REGION) if QUEUE_URL else None
except ImportError:
    _sqs = None


def _send_signals(signals: list[dict]) -> int:
    """Đẩy từng signal vào SQS. Trả số message gửi thành công.
    PII-scrub trước khi gửi — telemetry không mang PII/secret thô (SOC2)."""
    signals = [scrub_signal(s) for s in signals]
    if _sqs is None or not QUEUE_URL:
        # dev/offline: log ra stdout thay vì gửi
        for s in signals:
            print(f"[forwarder] (mock SQS) {json.dumps(s, ensure_ascii=False)}")
        return len(signals)
    sent = 0
    for s in signals:
        try:
            _sqs.send_message(QueueUrl=QUEUE_URL, MessageBody=json.dumps(s, ensure_ascii=False))
            sent += 1
        except Exception as e:  # noqa: BLE001
            print(f"[forwarder] send_message error: {e}")
    return sent


class Handler(BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        if self.path != "/alerts":
            self._reply(404, {"error": "not found"})
            return
        length = int(self.headers.get("Content-Length", 0))
        try:
            payload = json.loads(self.rfile.read(length) or b"{}")
        except ValueError:
            self._reply(400, {"error": "invalid json"})
            return
        signals = alerts_to_signals(payload, TENANT_ID)
        sent = _send_signals(signals)
        n_alerts = len(payload.get("alerts", []) or [])
        print(f"[forwarder] alerts={n_alerts} → signals={len(signals)} → sqs_sent={sent}")
        self._reply(200, {"received": n_alerts, "forwarded": sent})

    def do_GET(self):  # noqa: N802
        if self.path in ("/health", "/ready"):
            self._reply(200, {"status": "ok", "sqs": bool(_sqs and QUEUE_URL)})
        else:
            self._reply(404, {"error": "not found"})

    def _reply(self, code: int, body: dict):
        payload = json.dumps(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, *args):  # tắt log mặc định cho gọn
        pass


def main() -> None:
    print(f"[forwarder] listen :{PORT} region={REGION} "
          f"queue={'set' if QUEUE_URL else 'MOCK(stdout)'}")
    HTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    main()
