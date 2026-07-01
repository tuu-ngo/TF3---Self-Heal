# Telemetry export cho AI team — data THẬT từ cluster CDO-02

Dữ liệu trích từ hệ thống live (EKS `cdo-eks-cluster-dev`, us-east-1) để AI team tune/test engine.
Định dạng bám đúng dataset fixture mà engine ăn (`simple_metrics.csv` + `logs.csv`).

## File

| File | Nội dung | Nguồn |
|---|---|---|
| `simple_metrics.csv` | Chuỗi metric dày: cột `time` + `<service>_<metric>` | Prometheus `query_range` (kube-prometheus-stack) |
| `logs.csv` | `timestamp,service,level,message` (podinfo — thưa) | `kubectl logs` cdo-sample-api |
| `online_boutique_logs.csv` | **LOG THẬT DÀY** `timestamp,service,level,message` — 10 service | `executor/tools/export_logs.py` |
| `ground_truth.json` | **NHÃN**: `inject_time` + `suspected_fault_type` mỗi fault | Sinh bởi `executor/tools/inject_faults.sh` |

## ⭐ DATASET ONLINE BOUTIQUE NHẤT QUÁN (metric + log + nhãn CÙNG APP) — dùng được trọn vẹn
Bộ 3 file dưới đây **cùng trên Online Boutique** (khớp `platform_profile_online_boutique.json`),
nên BARO correlate được metric↔log cùng service, và có nhãn để test detect:

| File | Nội dung |
|---|---|
| `online_boutique_metrics.csv` | metric cadvisor **per-service** (mem/cpu/restarts) × 10 OB service |
| `online_boutique_logs.csv` | ~12.6k dòng log OB (JSON severity+message) |
| `ground_truth_ob.json` | **2 nhãn**: `frontend_cpu` (load spike), `checkoutservice_restart` (crash) + `inject_time` |

**Anomaly khớp inject_time (verify):**
| Fault | inject_time | Tín hiệu | Đo được |
|---|---|---|---|
| `frontend_cpu` | 1782910192 | `frontend_cpu`, `checkoutservice_cpu` | cpu **x4.0** (load spike loadgen ×4) |
| `checkoutservice_restart` | 1782910497 | log ERROR/gap + checkout mem/cpu dip | crash pod checkoutservice |

> **Lưu ý**: OB service dùng gRPC → KHÔNG expose http metric (delay/loss rỗng, đã bỏ). Tín hiệu OB
> nằm ở **cpu/mem/restarts (cadvisor) + log**. Metrics mới ~50 dòng (OB vừa deploy) — chạy lại
> `SERVICES="frontend@tenant-a,..." WINDOW_S=21600 python executor/tools/export_telemetry.py`
> sau vài giờ để có history dày hơn (loadgen chạy 24/7 tích lũy).
> Regenerate fault+nhãn: `bash executor/tools/inject_faults_ob.sh`.

## 📜 LOG THẬT từ Online Boutique (2026-07-01) — nguồn log chính cho AI team
Đã deploy **Google Online Boutique** (11 microservice + Locust loadgenerator) vào `tenant-a` —
app thật, log verbose, **khớp đúng `platform_profile_online_boutique.json`** của engine.

`online_boutique_logs.csv`: **~5.8k dòng** từ 10 service (frontend, checkoutservice, cartservice,
paymentservice, recommendationservice, productcatalogservice, shippingservice, currencyservice,
emailservice, adservice). Log JSON có `severity` + `message` + `http.*` → hợp drain3/BARO.
Levels: DEBUG/INFO/WARNING. Loadgenerator bơm traffic liên tục → log sinh không ngừng.

Regenerate / lấy thêm:
```bash
# toàn bộ (mặc định 10 service, 15 phút gần nhất, tail 2000/service)
python executor/tools/export_logs.py > data-export/online_boutique_logs.csv
# tuỳ chỉnh:
LOG_SVCS=frontend,checkoutservice LOG_SINCE=30m LOG_TAIL=5000 python executor/tools/export_logs.py
```
> Metric của Online Boutique lấy cùng cách `export_telemetry.py` (đổi SERVICES sang các svc OB) —
> nhưng engine đã có metric online-boutique từ dataset gốc; **log mới là thứ họ thiếu**.

## 🎯 Dataset có ANOMALY THẬT + nhãn (2026-07-01)
Đã deploy `loadgen` (traffic nền ~12-25 req/s vào podinfo) + inject fault thật qua chaos endpoints.
`ground_truth.json` ghi 3 fault có nhãn; anomaly **hiện rõ** trong `simple_metrics.csv`:

| Fault | inject_time | Tín hiệu trong metric | Đo được |
|---|---|---|---|
| `delay` | 1782907830 | `cdo-sample-api_delay` (p95 ms) | 4.8ms → **1655ms (x347)** |
| `loss` | 1782908134 | `cdo-sample-api_loss` (error rate) | 0 → **0.47 (47% 5xx)** |
| `restart` | 1782908437 | pod restart (panic) | restart_count tăng |

→ AI team dùng `inject_time` slice cửa sổ before/after để test detect (đúng cách `benchmark_e2e_push.py`).
**Log vẫn thưa**: podinfo không log từng request/lỗi (bản chất app) → nếu cần log dày cho BARO/drain3,
phải thay bằng app "nói nhiều" (xem mục Giới hạn LOG). Metric đã đủ dày + có nhãn để tune DETECT.

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
