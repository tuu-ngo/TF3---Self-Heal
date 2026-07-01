"""
Prometheus dense-window builder — telemetry cho AI /v1/detect.

AI engine (BOCPD/BARO) cần chuỗi metric DÀY (hàng nghìn điểm time-series) để
detect anomaly, KHÔNG phải vài signal rời rạc từ K8s event. Module này query
Prometheus `query_range` cho 1 deployment → build telemetry_window
contract-compliant (signal_name=`container_resource_usage`, value SỐ, labels.system=K8S_NATIVE).

Khớp reference push của AI (`benchmark_e2e_push.py`): metric số dày + (log qua
application_log_event — thêm sau). Degrade: không có PROMETHEUS_URL / lỗi → trả []
(executor fallback sang window rời cũ, không crash).
"""
from __future__ import annotations

import time
from typing import Any

try:
    import requests
    _HAS_REQ = True
except ImportError:  # pragma: no cover
    _HAS_REQ = False

from config import CONFIG

# Memory working-set bytes theo pod của deployment — tín hiệu OOM/memory-pressure.
_PROMQL_MEM = (
    'container_memory_working_set_bytes'
    '{{namespace="{ns}",pod=~"{dep}-.*",container!="",image!=""}}'
)

# Error rate (5xx/total) theo deployment — signal cho VERIFY. Tên chứa "error" nên
# AI verifier (verifier.py: `if "error" in signal_name and value>threshold`) THẬT SỰ đánh giá,
# thay vì rubber-stamp DONE. value 0.0–1.0 (khớp threshold 0.05), đúng contract service_error_rate.
_PROMQL_ERR = (
    'sum(rate(http_requests_total{{namespace="{ns}",pod=~"{dep}-.*",status=~"5.."}}[2m])) '
    '/ clamp_min(sum(rate(http_requests_total{{namespace="{ns}",pod=~"{dep}-.*"}}[2m])), 1)'
)


def deployment_of(window: list[dict]) -> str:
    """Rút deployment name từ labels của telemetry_window (điểm đầu có labels.deployment)."""
    for p in window:
        dep = (p.get("labels") or {}).get("deployment")
        if dep:
            return dep
    return ""


class PromWindow:
    def __init__(self, cfg=CONFIG):
        self.cfg = cfg
        self.enabled = _HAS_REQ and bool(cfg.prometheus_base_url)

    def build_window(self, namespace: str, deployment: str, tenant_id: str) -> list[dict]:
        """Trả list telemetry point (container_resource_usage) dày cho deployment.
        Rỗng nếu tắt/không có dữ liệu → caller fallback."""
        if not self.enabled or not deployment:
            return []
        end = int(time.time())
        start = end - self.cfg.prom_window_seconds
        query = _PROMQL_MEM.format(ns=namespace, dep=deployment)
        try:
            series = self._query_range(query, start, end, self.cfg.prom_step_seconds)
        except Exception:  # noqa: BLE001 — telemetry builder không được làm crash loop
            return []

        pts: list[dict] = []
        for s in series:
            pod = s.get("metric", {}).get("pod", deployment)
            for ts, val in s.get("values", []):
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                pts.append({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(float(ts))),
                    "tenant_id": tenant_id,
                    "service": deployment,
                    "signal_name": "container_resource_usage",
                    "value": v,
                    "labels": {
                        "system": "K8S_NATIVE",
                        "namespace": namespace,
                        "deployment": deployment,
                        "pod": pod,
                    },
                })
        return pts

    def build_health_signals(self, namespace: str, deployment: str, tenant_id: str) -> list[dict]:
        """Signal service_error_rate (vài điểm gần nhất) cho VERIFY — để AI verifier đánh giá
        thật (recovered → error_rate~0 → DONE; còn lỗi → cao → RETRY). Rỗng nếu không có data."""
        if not self.enabled or not deployment:
            return []
        end = int(time.time())
        start = end - 180  # 3 phút gần nhất
        try:
            series = self._query_range(_PROMQL_ERR.format(ns=namespace, dep=deployment),
                                       start, end, 30)
        except Exception:  # noqa: BLE001
            return []
        pts: list[dict] = []
        for s in series:
            for ts, val in s.get("values", []):
                try:
                    v = float(val)
                except (TypeError, ValueError):
                    continue
                pts.append({
                    "ts": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(float(ts))),
                    "tenant_id": tenant_id,
                    "service": deployment,
                    "signal_name": "service_error_rate",
                    "value": v,
                    "labels": {"system": "K8S_NATIVE", "namespace": namespace,
                               "deployment": deployment},
                })
        return pts

    def _query_range(self, query: str, start: int, end: int, step: int) -> list[dict[str, Any]]:
        url = f"{self.cfg.prometheus_base_url.rstrip('/')}/api/v1/query_range"
        resp = requests.get(
            url,
            params={"query": query, "start": start, "end": end, "step": step},
            timeout=self.cfg.prom_timeout_s,
        )
        resp.raise_for_status()
        data = resp.json()
        if data.get("status") != "success":
            return []
        return data.get("data", {}).get("result", [])
