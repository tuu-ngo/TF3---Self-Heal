"""
Export telemetry THẬT từ cluster cho AI team tune engine.

Sinh 2 file đúng định dạng engine ăn (dataset fixture):
  - simple_metrics.csv : cột `time` + `<service>_<metric>` (mem/cpu/delay/loss), rows theo timestamp.
  - (logs.csv sinh riêng bằng `kubectl logs --timestamps`, xem data-export/README.md)

Nguồn metric = Prometheus (kube-prometheus-stack) qua /api/v1/query_range.
Chạy IN-CLUSTER (có DNS tới Prometheus):
    kubectl -n self-heal-system exec -i deploy/cdo-executor -- \
        python - < executor/tools/export_telemetry.py > data-export/simple_metrics.csv

Env (tùy chỉnh):
    PROM_URL   (default kube-prometheus-stack in-cluster)
    WINDOW_S   (default 21600 = 6h)   STEP_S (default 30 = scrape interval)
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.parse
import urllib.request

PROM = os.getenv("PROM_URL", "http://kube-prometheus-stack-prometheus.monitoring.svc.cluster.local:9090")
WINDOW_S = int(os.getenv("WINDOW_S", "21600"))
STEP_S = int(os.getenv("STEP_S", "30"))

# (service, namespace) cần export
SERVICES = [("cdo-sample-api", "tenant-a"), ("notification-service", "tenant-b")]

# metric_type → PromQL template (aggregate về 1 giá trị/service). {ns},{svc} sẽ format.
QUERIES = {
    "mem":   'sum(container_memory_working_set_bytes{{namespace="{ns}",pod=~"{svc}-.*",container!="",image!=""}})',
    "cpu":   'sum(rate(container_cpu_usage_seconds_total{{namespace="{ns}",pod=~"{svc}-.*",container!="",image!=""}}[1m]))',
    "delay": 'histogram_quantile(0.95, sum by (le) (rate(http_request_duration_seconds_bucket{{namespace="{ns}"}}[5m]))) * 1000',
    "loss":  'sum(rate(http_requests_total{{namespace="{ns}",status=~"5.."}}[5m])) / clamp_min(sum(rate(http_requests_total{{namespace="{ns}"}}[5m])), 1)',
}


def query_range(expr: str, start: int, end: int, step: int) -> dict[int, float]:
    qs = urllib.parse.urlencode({"query": expr, "start": start, "end": end, "step": step})
    try:
        r = json.load(urllib.request.urlopen(f"{PROM}/api/v1/query_range?{qs}", timeout=30))
    except Exception:
        return {}
    if r.get("status") != "success":
        return {}
    res = r.get("data", {}).get("result", [])
    if not res:
        return {}
    out = {}
    for ts, val in res[0].get("values", []):
        try:
            out[int(float(ts))] = float(val)
        except (TypeError, ValueError):
            pass
    return out


def main() -> None:
    end = int(time.time())
    start = end - WINDOW_S
    cols: list[str] = []
    data: dict[str, dict[int, float]] = {}
    for svc, ns in SERVICES:
        for mtype, tmpl in QUERIES.items():
            col = f"{svc}_{mtype}"
            series = query_range(tmpl.format(ns=ns, svc=svc), start, end, STEP_S)
            if series:
                cols.append(col)
                data[col] = series
    # trục thời gian chung
    times = sorted({t for s in data.values() for t in s})
    w = sys.stdout
    w.write("time," + ",".join(cols) + "\n")
    for t in times:
        row = [str(t)] + [(f"{data[c].get(t, ''):.6f}" if t in data[c] else "") for c in cols]
        w.write(",".join(row) + "\n")
    sys.stderr.write(f"[export] {len(times)} rows x {len(cols)} cols, window={WINDOW_S}s step={STEP_S}s\n")


if __name__ == "__main__":
    main()
