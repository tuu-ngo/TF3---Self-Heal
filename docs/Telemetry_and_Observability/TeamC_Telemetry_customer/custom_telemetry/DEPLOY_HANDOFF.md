# Deploy Handoff - Team C Custom Telemetry

## Scope bàn giao

Team C bàn giao lớp normalize telemetry, không bàn giao AI Engine hoặc executor deployment.

Thư mục:

```text
P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/
```

Source of truth contract:

```text
TF3-Self-Heal-Agent-AWS/contract - new 4/telemetry-contract.md
```

## Deploy team cần chạy gì?

Script chính:

```text
normalize_telemetry.py
telemetry_contract.py
```

Runtime requirement:

```text
python3
không cần package ngoài standard library
```

## Input từ platform

Team C không phụ thuộc dữ liệu được lấy bằng CloudWatch, OpenTelemetry, Fluent Bit hay tool cụ thể nào. Deploy/platform chỉ cần đưa raw JSON vào adapter theo một trong các shape dưới đây:

| Source | Format | CLI mode |
|---|---|---|
| Metric raw JSON | Prometheus-compatible query result hoặc metric JSON tương đương | `prometheus` |
| Kubernetes event raw JSON | Event list JSON từ cluster/platform | `k8s-events` |
| Log raw JSON | JSON event/list hoặc `logEvents[]` từ collector bất kỳ | `logs` |
| Trace span raw JSON | JSON list spans | `otel-spans` |
| Trace export raw JSON | JSON có `resourceSpans[]` | `otlp-export` |
| Unknown/common shape | JSON raw bất kỳ được hỗ trợ | `auto` |

## Output cho downstream

Output là JSON array:

```text
telemetry_window[]
```

Mỗi item chỉ có các top-level fields:

```text
ts
tenant_id
service
signal_name
value
labels
```

Downstream sử dụng output này để:

- Bọc vào request `POST /v1/detect`.
- Ghi vào SQS internal telemetry buffer trước khi forward.
- Chạy executor mock/offline bằng scenario wrapper.

## Command mẫu cho deploy pipeline

Prometheus:

```bash
cd /mnt/g/XBrain/CDO-02_capstone/P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry

python3 normalize_telemetry.py prometheus \
  --input /tmp/prom_query.json \
  --signal-name service_latency_p95 \
  --service checkout-svc \
  --namespace tenant-a \
  --deployment cdo-sample-api \
  --output /tmp/telemetry_window.json

python3 normalize_telemetry.py validate --input /tmp/telemetry_window.json
```

K8s events:

```bash
kubectl get events -A -o json > /tmp/k8s_events.json

python3 normalize_telemetry.py k8s-events \
  --input /tmp/k8s_events.json \
  --output /tmp/telemetry_window.json

python3 normalize_telemetry.py validate --input /tmp/telemetry_window.json
```

Logs:

```bash
python3 normalize_telemetry.py logs \
  --input /tmp/raw_logs.json \
  --output /tmp/telemetry_window.json

python3 normalize_telemetry.py validate --input /tmp/telemetry_window.json
```

OTLP:

```bash
python3 normalize_telemetry.py otlp-export \
  --input /tmp/otlp_export.json \
  --output /tmp/telemetry_window.json

python3 normalize_telemetry.py validate --input /tmp/telemetry_window.json
```

## Cách forward sang AI

Contract new 4 quy định CDOps push telemetry bằng HTTP POST tới AI Engine `/v1/detect`. Deploy team hoặc forwarder bọc output của Team C vào payload:

```json
{
  "idempotency_key": "telemetry-forwarder-<unique-id>",
  "dry_run_mode": true,
  "telemetry_window": []
}
```

`telemetry_window` là nội dung file `/tmp/telemetry_window.json`.

Endpoint nội bộ theo contract:

```text
http://ai-engine.self-heal-system.svc.cluster.local:8080/v1/detect
```

## Điều kiện pass trước khi deploy

| Check | Pass criteria |
|---|---|
| Python compile | `python3 -m py_compile telemetry_contract.py normalize_telemetry.py` pass |
| Contract validation | `normalize_telemetry.py validate` trả `{"valid": true, ...}` |
| Signal enum | Không có signal ngoài 12 enum contract new 4 |
| Secret scrub | Log output không còn email/token/password/API key/connection string rõ |
| Tenant scope | Mọi point có `tenant_id` UUID v4 |
| Labels | Mọi point có `labels.system` |
| AI API | `/v1/detect` không trả `400 Bad Request` vì telemetry schema |

## Lỗi thường gặp

| Lỗi | Nguyên nhân | Cách xử lý |
|---|---|---|
| `unsupported raw telemetry shape for auto mode` | Raw JSON chưa thuộc shape adapter hỗ trợ | Dùng mode cụ thể hoặc đưa sample cho Team C map thêm |
| `cannot map internal signal to contract enum` | Scenario/source có signal ngoài mapping | Team C thêm mapping vào `_INTERNAL_SIGNAL_MAP` |
| `tenant_id must be UUID v4` | Raw có tenant sai format | Sửa collector/forwarder hoặc để adapter dùng default tenant test |
| `labels.system is required` | Labels thiếu system | Bổ sung metadata collector hoặc để adapter set default |
| AI trả `400 Bad Request` | Payload wrapper hoặc telemetry schema sai | Chạy `validate` trước, lưu request/response làm evidence |

## Artifact deploy team nên lưu

```text
evidence/custom_telemetry_deploy/
  raw_input.json
  telemetry_window.json
  validate_output.json
  detect_request.json
  detect_response.json
  forwarder_log.txt
```

## Ownership

Team C chịu trách nhiệm:

- Mapping raw telemetry sang contract signal.
- Validation contract new 4.
- Scrub PII/secret trong `application_log_event`.
- Cung cấp sample/evidence cho QA.

Deploy/platform chịu trách nhiệm:

- Cung cấp raw collector output thật.
- Mount/copy script vào nơi forwarder chạy nếu cần.
- Bọc `telemetry_window[]` vào payload `/v1/detect`.
- SQS/DLQ, retry, rate limit, service account, network routing.
