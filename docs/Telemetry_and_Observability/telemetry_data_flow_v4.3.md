# Luong Data Telemetry Va Observability

## Muc tieu

File nay tom tat luong data telemetry trong phan Observability cua TF3 Self-Heal.

## Luong tong quan

```text
Workload tenant-a / tenant-b
-> Prometheus / Alertmanager / K8s events / pod logs
-> Telemetry Forwarder
-> Scrub PII / secret
-> Map alert thanh telemetry signal dung contract
-> SQS telemetry buffer
-> Executor drain SQS
-> Gom signal theo namespace/deployment
-> Prometheus dense-window enrichment neu co
-> AI Engine /v1/detect
-> AI Engine /v1/decide
-> Executor execute hoac deny/escalate
-> Prometheus/K8s scrape post-telemetry
-> AI Engine /v1/verify
-> Audit stdout / CloudWatch / S3 Object Lock
```

## 1. Nguon telemetry

Nguon data chinh trong repo:

| Nguon | Du lieu |
|---|---|
| Prometheus metrics | `container_memory_working_set_bytes`, error rate, latency, throughput |
| Prometheus Alertmanager | Alert `PodOOMKilled`, `ContainerCrashLooping`, `HighLatencyP95`, `HighErrorRate`, `ServiceUnhealthy` |
| Kubernetes API | Pod status, restart count, deployment state, recent pod logs |
| Application logs | `application_log_event` sau khi scrub |
| Trace/error events | `distributed_trace_error_event` neu pipeline trace co day du |

## 2. Forwarder

`forwarder/forwarder.py` la cau noi Alertmanager -> SQS.

Flow:

```text
Alertmanager POST /alerts
-> forwarder.alert_map.alerts_to_signals()
-> forwarder.scrub.scrub_signal()
-> SendMessage vao SQS
```

Forwarder khong goi AI va khong cham Kubernetes. No chi chuan hoa alert thanh telemetry signal theo telemetry contract.

Vi du mapping:

| Alertmanager alert | Telemetry signal |
|---|---|
| `PodOOMKilled` | `pod_oom_event` |
| `ContainerCrashLooping` | `container_restart_count` |
| `HighLatencyP95` | `service_latency_p95` |
| `HighErrorRate` | `service_error_rate` |
| `HighContainerMemory` | `container_resource_usage` |
| `ServiceUnhealthy` | `service_unhealthy` |

## 3. Telemetry contract

Moi telemetry point can co shape chinh:

```json
{
  "ts": "2026-06-25T10:30:00.123Z",
  "tenant_id": "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c",
  "service": "cdo-sample-api",
  "signal_name": "service_error_rate",
  "value": 0.12,
  "labels": {
    "system": "K8S_NATIVE",
    "namespace": "tenant-a",
    "deployment": "cdo-sample-api"
  }
}
```

Signal enum quan trong:

- `service_error_rate`
- `service_latency_p95`
- `container_resource_usage`
- `application_log_event`
- `distributed_trace_error_event`
- `pod_oom_event`
- `service_unhealthy`
- `queue_backlog`
- `service_throughput_rps`
- `container_restart_count`
- `secret_expiry_warning`
- `db_connection_pool_saturation`

## 4. SQS buffer

SQS la buffer noi bo cua CDO, khong phai kenh AI truc tiep.

Vai tro:

- Giu telemetry khi executor/AI tam thoi chua xu ly kip.
- Cho phep long-poll va batch.
- Ho tro DLQ khi message malformed hoac retry qua so lan.
- Dam bao executor chi ack message sau khi incident da xu ly xong.

Theo contract-new-4, kenh chinh thuc sang AI van la HTTP push `/v1/detect`. SQS nam trong boundary CDO.

## 5. Executor drain va group incident

`executor/sqs_source.py` doc SQS va gom message theo:

```text
(labels.namespace, labels.deployment)
```

Sau do tao mot incident:

```text
namespace
deployment
telemetry_window[]
receipt_handles[]
```

Executor chi `ack` SQS message sau khi `handle_incident()` chay xong.

## 6. Prometheus dense-window enrichment

AI detect dung BOCPD/BARO can time-series day, khong chi vai alert roi rac. Vi vay `executor/prom_source.py` co nhiem vu bo sung dense-window tu Prometheus.

Flow:

```text
telemetry_window tu SQS/scenario
-> lay deployment tu labels.deployment
-> query Prometheus query_range
-> build container_resource_usage points
-> neu co dense-window thi dung dense-window cho /v1/detect
-> neu khong co thi fallback ve telemetry_window goc
```

Metric memory hien dang dung:

```text
container_memory_working_set_bytes{namespace="<ns>", pod=~"<deployment>-.*"}
```

Verify health signal hien dang dung:

```text
service_error_rate
```

## 7. Detect / Decide / Verify

Executor goi AI:

```text
POST /v1/detect
POST /v1/decide
POST /v1/verify
```

Header bat buoc:

- `X-Tenant-Id`
- `X-Correlation-Id`
- `Idempotency-Key`
- `X-Dry-Run-Mode`

AI validate tenant, idempotency key, dry-run mode va telemetry shape. Neu tenant mismatch thi fail-safe.

## 8. Observability output va evidence

Data dau ra can dung cho evidence:

| Evidence | Noi dung |
|---|---|
| Executor stdout | Audit event JSON theo `correlation_id` |
| CloudWatch Logs | Query audit/log theo incident |
| S3 Object Lock | Tamper-evident audit trail |
| Prometheus metrics | Pre/post action health signals |
| Grafana dashboard | View system health va self-heal events |
| SQS/DLQ metrics | Backlog, malformed telemetry, retry/dead-letter |

