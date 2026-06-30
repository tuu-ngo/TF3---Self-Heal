# Team C - Custom Telemetry

Scope của Team C: `custom_telemetry`.

Team C nhận raw telemetry từ mock scenario hoặc runtime observability, sau đó chuẩn hóa thành `telemetry_window[]` đúng contract new 4.

```text
telemetry-contract.md
```

Output sau normalize bàn giao cho các bên:

- `TF3-Self-Heal-Agent-AWS/executor/main.py` trong mock/offline flow.
- Team deploy/Telemetry Forwarder để HTTP POST sang AI Engine `/v1/detect`.
- QA/evidence để chứng minh telemetry hợp lệ theo contract.

## Flow

```text
# Runtime flow
raw telemetry
  -> normalize_telemetry.py
  -> telemetry_window[]
  -> executor/main.py hoặc telemetry forwarder
  -> AI Engine /v1/detect

# Quality Check Flow
telemetry_window[]
  -> validate
  -> pass/fail contract new 4
```

Output Rules theo contract.

- Top-level field chỉ gồm `ts`, `tenant_id`, `service`, `signal_name`, `value`, `labels`.
- `tenant_id` là UUID v4.
- `ts` là RFC3339 UTC millisecond.
- `signal_name` thuộc 12 enum (trong contract new 4).
- `labels.system` luôn có.
- Log value được scrub email, token, API key, password, Bearer token, connection string.

## File chính

| File | Vai trò |
|---|---|
| `telemetry_contract.py` | Logic normalize, map signal, validate, scrub secret |
| `normalize_telemetry.py` | CLI cho Team C dùng với raw input |
| `DEPLOY_HANDOFF.md` | Bàn giao cho team deploy/platform |

## Raw input hỗ trợ

Team C không phụ thuộc raw data đến từ CloudWatch, OpenTelemetry, Fluent Bit hay collector nào. Trách nhiệm của Team C bắt đầu khi đã có raw JSON được đẩy vào adapter; adapter chỉ cần nhận input đó rồi normalize sang `telemetry_window[]`.

| Input | CLI mode | Output signal |
|---|---|---|
| Scenario JSON có `telemetry_window` | `scenario` hoặc `auto` | Map signal nội bộ sang enum contract |
| Metric raw JSON | `prometheus` hoặc `auto` | Metric signal theo tham số hoặc infer |
| Kubernetes event raw JSON | `k8s-events` hoặc `auto` | `pod_oom_event`, `service_unhealthy` |
| Log raw JSON từ collector bất kỳ | `logs` hoặc `auto` | `application_log_event` |
| Trace span raw JSON | `otel-spans` hoặc `auto` | `distributed_trace_error_event` cho span lỗi |
| Trace export raw JSON có `resourceSpans[]` | `otlp-export` hoặc `auto` | `distributed_trace_error_event` cho span lỗi |
| Telemetry đã normalize | `validate` | Kiểm tra contract |

## Chạy mock scenario hiện có

```bash
cd /mnt/g/XBrain/CDO-02_capstone/P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry

python3 normalize_telemetry.py scenario \
  --input ../../../TF3-Self-Heal-Agent-AWS/executor/scenarios/sc01_oom_kill_a.json \
  --output /tmp/sc01_contract.json

python3 normalize_telemetry.py validate --input /tmp/sc01_contract.json
```

Chạy executor bằng file đã normalize:

```bash
cd /mnt/g/XBrain/CDO-02_capstone/TF3-Self-Heal-Agent-AWS/executor

CDO_K8S_MOCK=true AI_BASE_URL=http://127.0.0.1:8080 \
  python3 main.py /tmp/sc01_contract.json
```

Mock AI cần chạy ở terminal khác nếu muốn test full flow:

```bash
cd /mnt/g/XBrain/CDO-02_capstone/TF3-Self-Heal-Agent-AWS/executor
python3 mock_ai_server.py
```

## Chạy với raw telemetry thật

Các raw telemetry thật cần input JSON do platform/collector export ra.

Prometheus query result:

```bash
python3 normalize_telemetry.py prometheus \
  --input prom_query_latency.json \
  --signal-name service_latency_p95 \
  --service checkout-svc \
  --namespace tenant-a \
  --deployment cdo-sample-api \
  --output /tmp/latency_window.json
```

K8s events:

```bash
kubectl get events -A -o json > /tmp/k8s_events.json

python3 normalize_telemetry.py k8s-events \
  --input /tmp/k8s_events.json \
  --output /tmp/k8s_event_window.json
```

Raw logs:

```bash
python3 normalize_telemetry.py logs \
  --input raw_logs.json \
  --output /tmp/log_window.json
```

OTel span list:

```bash
python3 normalize_telemetry.py otel-spans \
  --input spans.json \
  --output /tmp/trace_window.json
```

OTLP export:

```bash
python3 normalize_telemetry.py otlp-export \
  --input otlp_export.json \
  --output /tmp/otlp_trace_window.json
```

Auto-detect khi chưa biết raw shape:

```bash
python3 normalize_telemetry.py auto \
  --input raw_telemetry.json \
  --output /tmp/telemetry_window.json
```

## Validate output trước khi bàn giao

Kiểm tra chất lượng để telemetry_window[] gửi sang executor/AI đúng contract.

```bash
python3 normalize_telemetry.py validate --input /tmp/telemetry_window.json
```

Output kỳ vọng:

```json
{
  "valid": true,
  "points": 1
}
```

Nếu input là scenario wrapper có field `telemetry_window`, lệnh `validate` cũng đọc được:

```bash
python3 normalize_telemetry.py validate --input /tmp/sc01_contract.json
```

## Mapping phổ biến

Bảng này liệt kê các mapping raw/internal thường gặp. Đây không phải danh sách đầy đủ 12 signal contract.

```text
Hướng xử lý cho Raw signal lạ chưa được mapping.
   -> nếu đã là contract signal: pass
    -> nếu chưa có mapping: fail
    -> Thêm mapping
    -> chạy lại validate
```

| STT | Raw/internal signal | Contract signal |
|---:|---|---|
| 1 | `pod_waiting_reason=OOMKilled` | `pod_oom_event` |
| 2 | `exit_code_oom=137` | `pod_oom_event` |
| 3 | `restart_count` | `container_restart_count` |
| 4 | `container_memory_pct` | `container_resource_usage` |
| 5 | `readiness_fail_after_deploy` | `service_unhealthy` |
| 6 | `hpa_at_max_replicas` | `service_unhealthy` |
| 7 | `minor_blip` | `service_unhealthy` |
| 8 | raw log message | `application_log_event` |
| 9 | OTel span ERROR | `distributed_trace_error_event` |
| 10 | K8s `OOMKilling` | `pod_oom_event` |
| 11 | K8s `Unhealthy` / `BackOff` / `Failed` | `service_unhealthy` |

## 12 Contract Signals (new 4)

| STT | Contract signal |
|---:|---|
| 1 | `service_error_rate` |
| 2 | `service_latency_p95` |
| 3 | `container_resource_usage` |
| 4 | `application_log_event` |
| 5 | `distributed_trace_error_event` |
| 6 | `pod_oom_event` |
| 7 | `service_unhealthy` |
| 8 | `queue_backlog` |
| 9 | `service_throughput_rps` |
| 10 | `container_restart_count` |
| 11 | `secret_expiry_warning` |
| 12 | `db_connection_pool_saturation` |

## Check toàn bộ scenario TF3

 (note: phần này là phần con trong Quality Quick Test bên dưới).
```bash
cd /mnt/g/XBrain/CDO-02_capstone

python3 - <<'PY'
import glob, subprocess

normalizer = "P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py"
failed = []
paths = sorted(glob.glob("TF3-Self-Heal-Agent-AWS/executor/scenarios/*.json"))

for path in paths:
    result = subprocess.run(
        ["python3", normalizer, "scenario", "--input", path, "--window-only"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
    )
    if result.returncode:
        failed.append((path, result.stderr.strip()))

print("checked", len(paths))
print("all_pass" if not failed else failed)
raise SystemExit(1 if failed else 0)
PY
```

Kết quả hiện tại: `checked 15`, `all_pass`.(đạt yêu cầu contract để bàn giao cho team deploy). adapter xử lý được toàn bộ secenario mock trong repo.

## Quality Quick Test

Kiểm tra quality để bàn giao cho team deploy.

```bash
cd /mnt/g/XBrain/CDO-02_capstone

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache \
  python3 -m py_compile \
  P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/telemetry_contract.py \
  P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache python3 - <<'PY'
import glob, os, subprocess

normalizer = "P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py"
paths = sorted(glob.glob("TF3-Self-Heal-Agent-AWS/executor/scenarios/*.json"))
failed = []
env = {**os.environ, "PYTHONPYCACHEPREFIX": "/tmp/cdo_pycache"}

for path in paths:
    result = subprocess.run(
        ["python3", normalizer, "scenario", "--input", path, "--window-only"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        text=True,
        env=env,
    )
    if result.returncode:
        failed.append((path, result.stderr.strip()))

print("checked", len(paths))
print("all_pass" if not failed else failed)
raise SystemExit(1 if failed else 0)
PY

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache \
  python3 P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py scenario \
  --input TF3-Self-Heal-Agent-AWS/executor/scenarios/sc01_oom_kill_a.json \
  --output /tmp/sc01_contract.json

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache \
  python3 P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py validate \
  --input /tmp/sc01_contract.json
```

Expected:

```text
checked 15
all_pass
{
  "valid": true,
  "points": 1
}
```

Test scrub log:

```bash
printf '%s\n' '[{"timestamp":1782745200000,"service":"checkout-svc","namespace":"tenant-a","deployment":"cdo-sample-api","level":"ERROR","message":"checkout failed credential placeholder_token secret placeholder_password user user-at-example.test"}]' > /tmp/raw_logs.json

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache \
  python3 P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py logs \
  --input /tmp/raw_logs.json \
  --output /tmp/log_window.json

PYTHONPYCACHEPREFIX=/tmp/cdo_pycache \
  python3 P2_CD02_Duc/Telemetry_and_Observability/TeamC_Telemetry_customer/custom_telemetry/normalize_telemetry.py validate \
  --input /tmp/log_window.json

grep -n "application_log_event\\|placeholder_token\\|placeholder_password" /tmp/log_window.json
```

Expected có dạng:

```text
"value": "checkout failed credential placeholder_token secret placeholder_password user user-at-example.test"
```

Test full mock executor flow:

Terminal 1:

```bash
cd /mnt/g/XBrain/CDO-02_capstone/TF3-Self-Heal-Agent-AWS/executor
python3 mock_ai_server.py
```

Terminal 2:

```bash
cd /mnt/g/XBrain/CDO-02_capstone/TF3-Self-Heal-Agent-AWS/executor

CDO_K8S_MOCK=true AI_BASE_URL=http://127.0.0.1:8080 \
  python3 main.py /tmp/sc01_contract.json
```

Expected có các event `detect_called`, `detect_response`, `decide_called`, `verify_called`, `verify_done` và kết thúc:

```text
>>> OUTCOME: auto_resolved
```

## Evidence nên lưu

```text
evidence/custom_telemetry/
  raw_input_<source>.json
  telemetry_window_<source>.json
  validate_<source>.json
  executor_stdout_<scenario>.jsonl
```

Khi report, ghi rõ mode:

- `mock_scenario`: dùng file scenario của executor.
- `real_prometheus`: lấy từ Prometheus HTTP API.
- `real_k8s_event`: lấy từ Kubernetes events.
- `real_log_event`: lấy từ raw log JSON do collector/platform cung cấp.
- `real_otel_span`: lấy từ raw trace/span JSON do collector/platform cung cấp.
