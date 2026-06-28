"""
HTTP client cho 3 AI endpoint (contract-new-4 §3, §4).
Xử lý header bắt buộc, timeout per-endpoint, và error/retry policy §4.
Auth: Local Trust + K8s NetworkPolicy — KHÔNG ký SigV4 cho AI endpoint.
"""
from __future__ import annotations

import time
import uuid
from typing import Any

import requests

from config import CONFIG
from errors import (
    AIBadRequest,
    AIConflict,
    AIInternalError,
    AITenantMismatch,
    AIUnauthorized,
    AIUnavailable,
)
from models import AnomalyContext, DecideResponse, DetectResponse, VerifyResponse


def new_uuid() -> str:
    return str(uuid.uuid4())


class AIClient:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self._session = requests.Session()

    # ---------- public API ----------

    def detect(self, telemetry_window: list[dict], correlation_id: str,
               idempotency_key: str | None = None) -> DetectResponse:
        body = {
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key or new_uuid(),
            "dry_run_mode": self.cfg.dry_run_mode,
            "telemetry_window": telemetry_window,
        }
        data = self._post("/v1/detect", body, correlation_id, self.cfg.ai_timeout_detect_s)
        return DetectResponse.from_dict(data)

    def decide(self, anomaly_context: AnomalyContext, correlation_id: str,
               idempotency_key: str) -> DecideResponse:
        # /v1/decide: idempotency_key đã được lock ở DynamoDB (idempotency.py) trước khi gọi
        body = {
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "dry_run_mode": self.cfg.dry_run_mode,
            "anomaly_context": anomaly_context.to_dict(),
        }
        data = self._post("/v1/decide", body, correlation_id, self.cfg.ai_timeout_decide_s)
        return DecideResponse.from_dict(data)

    def verify(self, action_executed: dict[str, Any], post_telemetry_window: list[dict],
               correlation_id: str, idempotency_key: str) -> VerifyResponse:
        body = {
            "correlation_id": correlation_id,
            "idempotency_key": idempotency_key,
            "dry_run_mode": self.cfg.dry_run_mode,
            "action_executed": action_executed,
            "post_telemetry_window": post_telemetry_window,
        }
        data = self._post("/v1/verify", body, correlation_id, self.cfg.ai_timeout_verify_s)
        return VerifyResponse.from_dict(data)

    # ---------- internals ----------

    def _headers(self, correlation_id: str, idempotency_key: str) -> dict[str, str]:
        return {
            "Content-Type": "application/json",
            "X-Tenant-Id": self.cfg.tenant_id,
            "X-Correlation-Id": correlation_id,
            "Idempotency-Key": idempotency_key,
            "X-Dry-Run-Mode": "true" if self.cfg.dry_run_mode else "false",
        }

    def _post(self, path: str, body: dict, correlation_id: str, timeout_s: float) -> dict:
        """Gọi POST + áp dụng error/retry policy contract §4."""
        url = f"{self.cfg.ai_base_url}{path}"
        headers = self._headers(correlation_id, body["idempotency_key"])

        attempt = 0
        while True:
            try:
                resp = self._session.post(url, json=body, headers=headers, timeout=timeout_s)
            except requests.Timeout:
                # timeout coi như upstream unavailable → escalate, không execute
                raise AIUnavailable(f"timeout calling {path} after {timeout_s}s")
            except requests.RequestException as e:
                raise AIUnavailable(f"connection error calling {path}: {e}")

            code = resp.status_code
            if code == 200:
                return resp.json()
            if code == 400:
                raise AIBadRequest(self._msg(resp))
            if code == 401:
                raise AIUnauthorized(self._msg(resp))
            if code == 403:
                raise AITenantMismatch(self._msg(resp))
            if code == 409:
                raise AIConflict(self._msg(resp))
            if code == 429:
                retry_after = float(resp.headers.get("Retry-After", "1"))
                # backoff theo Retry-After rồi thử lại (không tính vào quota 500)
                time.sleep(retry_after)
                continue
            if code == 500:
                if attempt < self.cfg.http_500_max_retries:
                    time.sleep(self.cfg.http_500_backoff_s[attempt])
                    attempt += 1
                    continue
                raise AIInternalError(self._msg(resp))
            if code == 503:
                raise AIUnavailable(self._msg(resp))
            # mã lạ → coi như unavailable, fail-safe
            raise AIUnavailable(f"unexpected status {code}: {self._msg(resp)}")

    @staticmethod
    def _msg(resp: requests.Response) -> str:
        try:
            return str(resp.json())
        except Exception:
            return resp.text[:300]
