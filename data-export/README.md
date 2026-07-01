# Telemetry export cho AI team — data THẬT từ cluster CDO-02

Dữ liệu trích từ hệ thống live (EKS `cdo-eks-cluster-dev`, us-east-1) để AI team tune/test engine.
Định dạng bám đúng dataset fixture mà engine ăn (`simple_metrics.csv` + `logs.csv`).

## File

| File | Nội dung | Nguồn |
|---|---|---|
| `simple_metrics.csv` | Chuỗi metric dày: cột `time` + `<service>_<metric>` | Prometheus `query_range` (kube-prometheus-stack) |
| `logs.csv` | `timestamp,service,level,message` | `kubectl logs --timestamps` các pod tenant |

### `simple_metrics.csv` — cột hiện có
`time`, và cho mỗi service (`cdo-sample-api` @tenant-a, `notification-service` @tenant-b):
- `_mem` — `container_memory_working_set_bytes` (bytes)
- `_cpu` — `rate(container_cpu_usage_seconds_total[1m])`
- `_delay` — p95 latency `histogram_quantile(0.95, http_request_duration_seconds_bucket)` (ms)
- `_loss` — error rate (5xx/total) — **hiện rỗng** vì không có 5xx traffic (hệ khỏe)

Mẫu hiện tại: **721 dòng × 6 cột**, window 6h, step 30s (khớp scrape interval).

## ⚠ Giới hạn LOG (quan trọng — báo AI team)
Workload demo (`podinfo`) **gần như không sinh log** — chỉ vài dòng startup → `logs.csv` rất thưa.
Muốn có log thật cho BARO/drain3, cần **1 trong 3**:
1. **Gen traffic + inject lỗi** vào `cdo-sample-api` để podinfo phát log request/error (CDO làm được).
2. Deploy workload "nói nhiều" hơn (app thật/synthetic log generator).
3. Engine chạy **metrics-only** ở giai đoạn này (metric đã dày & thật).

## Tái tạo (regenerate)

### Metrics
```bash
# chạy in-cluster (có DNS tới Prometheus). WINDOW_S / STEP_S tùy chỉnh.
kubectl -n self-heal-system exec -i deploy/cdo-executor -- \
    python - < executor/tools/export_telemetry.py > data-export/simple_metrics.csv
```
Ngoài cluster: `kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090`
rồi `PROM_URL=http://localhost:9090 python executor/tools/export_telemetry.py > simple_metrics.csv`.

### Logs
```bash
kubectl -n tenant-a logs deploy/cdo-sample-api --timestamps --since=6h --tail=5000
kubectl -n tenant-b logs deploy/notification-service --timestamps --since=6h --tail=5000
```

## Ghi chú contract
- Metric numeric ↔ signal contract: `_mem`→`container_resource_usage`, `_delay`→`service_latency_p95`,
  `_loss`→`service_error_rate`. Log ↔ `application_log_event`.
- Nếu AI team muốn dạng **push JSON** (telemetry_window) thay vì CSV: CDO executor đã build sẵn
  dense-window từ Prometheus (`executor/prom_source.py`) — có thể xuất JSON thay vì CSV.
