# M6 - IaC Observability Stack Flow v5.2

**Dự án:** TF3 Self-Heal Engine - CDO-02  
**Phạm vi:** Observability, telemetry ingestion, alert routing, evidence, và IaC alignment  
**Trạng thái:** Version 5.2 

---

## 1. Mục tiêu

Observability stack v5.2 phục vụ 5 mục tiêu:

1. Quan sát EKS workloads trong `tenant-a` và `tenant-b`.
2. Phát hiện các known patterns: OOM, CrashLoop, bad deploy, latency/error spike, unhealthy service.
3. Chuẩn hóa alert/metric/log thành `telemetry_window[]` đúng telemetry contract.
4. Cung cấp dense time-series cho AI Engine `/v1/detect` và post-heal signal cho `/v1/verify`.
5. Lưu audit/evidence theo `correlation_id` để chứng minh self-heal loop.

Observability không mutate Kubernetes. Mutation chỉ nằm trong CDO Executor sau Pre-Decide Gate, Safety Gate, snapshot và dry-run.

---

## 2. Kiến trúc v5.2

```text
tenant-a / tenant-b workloads
  -> kube-state-metrics / node-exporter / cAdvisor / pod logs
  -> Prometheus (kube-prometheus-stack, namespace monitoring)
  -> PrometheusRule firing
  -> Alertmanager
  -> cdo-telemetry-forwarder /alerts
  -> scrub PII/secret
  -> map alert thành telemetry signal enum
  -> Amazon SQS cdo-telemetry-dev
  -> Executor SQS consumer
  -> group incident theo namespace/deployment
  -> Prometheus dense-window enrichment
  -> AI Engine V4 /v1/detect
  -> AI Engine V4 /v1/decide
  -> Executor safety/snapshot/execute
  -> Prometheus/K8s post telemetry
  -> AI Engine V4 /v1/verify
  -> audit stdout + CloudWatch Logs + S3 Object Lock
```

Grafana đọc dữ liệu từ Prometheus để hiển thị dashboard. CloudWatch và S3 là lớp evidence/audit, không phải metrics store chính.

---

## 3. Thành phần chính

| Thành phần | Vị trí trong repo | Namespace | Trách nhiệm |
|---|---|---|---|
| Prometheus stack | `infra/modules/monitoring`, `manifests/monitoring` | `monitoring` | Scrape metrics, evaluate alert rules, feed Grafana và Alertmanager |
| PrometheusRule | `manifests/monitoring/prometheus-rules.yaml` | `monitoring` | Phát hiện known patterns và phát alertname khớp `forwarder/alert_map.py` |
| Alertmanager | kube-prometheus-stack | `monitoring` | Route firing alerts tới CDO Telemetry Forwarder |
| Telemetry Forwarder | `forwarder/`, `manifests/forwarder/forwarder.yaml` | `monitoring` | Nhận `/alerts`, normalize telemetry, scrub, gửi SQS |
| SQS telemetry queue | `infra/modules/audit` | AWS | Buffer nội bộ CDO và backpressure layer |
| SQS DLQ | `infra/modules/audit` | AWS | Giữ telemetry malformed/retry quá số lần |
| Executor SQS consumer | `executor/sqs_source.py` | `self-heal-system` | Drain SQS, group message thành incident telemetry window |
| Prometheus enrichment | `executor/prom_source.py` | `self-heal-system` | Query dense metric window cho AI detect và health signal cho verify |
| AI Engine V4 | `AI Engine V4`, `manifests/ai-engine` | `self-heal-system` | `/v1/detect`, `/v1/decide`, `/v1/verify` |
| Audit logger | `executor/audit.py` | `self-heal-system` | Ghi stdout, CloudWatch Logs, S3 Object Lock evidence |

---

## 4. IaC và manifest alignment

### 4.1 Terraform

Wiring Terraform hiện tại:

```text
infra/envs/dev/main.tf
  module vpc
  module eks
  module audit         -> S3 Object Lock, DynamoDB idempotency, SQS, DLQ
  module iam           -> IRSA cho executor, AI engine, forwarder
  module observability -> CloudWatch log groups / alarms
  module ecr
  module secrets
```

Các Helm module phase-2 đã được tài liệu hóa nhưng đang comment trong `infra/envs/dev/main.tf`:

```text
module kyverno
module argocd
module monitoring
```

Lý do: Helm provider cần endpoint của EKS cluster thật. Repo đang dùng quy trình apply 2 phase:

1. Phase 1 tạo AWS base và EKS.
2. Phase 2 chuyển provider sang cluster ACTIVE rồi cài Kyverno, ArgoCD, và kube-prometheus-stack.

### 4.2 Kubernetes manifests

Runtime manifests hiện tại:

| Manifest | Mục đích |
|---|---|
| `manifests/monitoring/prometheus-rules.yaml` | Alert rules cho self-heal |
| `manifests/monitoring/podmonitor.yaml` | Prometheus scrape config cho app/executor nếu bật |
| `manifests/monitoring/grafana-dashboard-selfheal.yaml` | Dashboard config |
| `manifests/forwarder/forwarder.yaml` | Forwarder deployment, service account, service |
| `manifests/executor/configmap.yaml` | Env của Executor: AI URL, SQS URL, audit bucket, DDB table, tenant namespaces |
| `manifests/executor/deployment.yaml` | Executor pod |
| `manifests/ai-engine/deployment.yaml` | AI Engine V4 service |
| `manifests/networkpolicies/*` | In-cluster access control |
| `manifests/rbac/executor-rbac.yaml` | Least-privilege K8s access cho Executor |

---

## 5. Telemetry contract v5.2

Kênh chính thức hướng sang AI là HTTP push tới `/v1/detect`.

SQS là buffer nội bộ của CDO:

```text
CDO collectors / forwarder -> SQS -> Executor worker -> HTTP POST /v1/detect
```

Telemetry point shape:

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

Signal enum bắt buộc:

| Signal | Nguồn trong thiết kế hiện tại | Cách dùng |
|---|---|---|
| `service_error_rate` | Prometheus HTTP metrics | detect và verify |
| `service_latency_p95` | Prometheus histogram | detect service stuck |
| `service_throughput_rps` | Prometheus / OTel | load và capacity context |
| `application_log_event` | logs sau khi scrub | RCA evidence |
| `distributed_trace_error_event` | OTel/X-Ray/Jaeger nếu bật | cross-service RCA |
| `container_resource_usage` | cAdvisor / Prometheus | OOM hoặc memory pressure |
| `pod_oom_event` | kube-state-metrics / K8s event | urgent memory handling |
| `container_restart_count` | kube-state-metrics | crashloop / bad deploy |
| `service_unhealthy` | probes / alert rules | restart decision |
| `queue_backlog` | SQS/RabbitMQ metric collector | deferred scaling |
| `db_connection_pool_saturation` | APM / DB exporter | dependency saturation |
| `secret_expiry_warning` | Secrets/cert manager | deferred rotation |

---

## 6. Alert mapping

`manifests/monitoring/prometheus-rules.yaml` phát alertname được align có chủ đích với `forwarder/alert_map.py`.

| Prometheus alert | Telemetry signal | Kiểu value | Scenario chính |
|---|---|---:|---|
| `PodOOMKilled` | `pod_oom_event` | string | OOMKilled |
| `ContainerCrashLooping` | `container_restart_count` | int | CrashLoopBackOff |
| `ImagePullBackOff` | `service_unhealthy` | string | Bad deploy |
| `HighContainerMemory` | `container_resource_usage` | int/bytes | Memory pressure |
| `HighLatencyP95` | `service_latency_p95` | float/ms | Service stuck |
| `HighErrorRate` | `service_error_rate` | float 0..1 | Error spike |
| `ServiceUnhealthy` | `service_unhealthy` | string | Probe failure |

Hành vi của Forwarder:

```text
Alertmanager payload
  -> chỉ nhận status=firing
  -> bỏ qua alertname không nằm trong map
  -> yêu cầu labels.namespace
  -> derive deployment từ labels.deployment/workload/app hoặc pod name
  -> scrub dữ liệu nhạy cảm
  -> gửi một SQS message cho mỗi telemetry signal
```

---

## 7. Executor telemetry ingestion

Production watch loop:

```text
executor/main.py --watch
  -> SqsTelemetrySource.drain()
  -> group theo (labels.namespace, labels.deployment)
  -> Executor.handle_incident()
  -> ack SQS chỉ sau khi incident xử lý xong
  -> fallback watcher poll nếu SQS disabled hoặc rỗng
```

Chi tiết quan trọng hiện tại:

- `manifests/executor/deployment.yaml` vẫn chạy `sleep infinity`.
- Để chạy production loop, command cần đổi sang `python main.py --watch`, hoặc bổ sung process manager tương đương.
- Với demo mode, manifest hiện tại hỗ trợ `kubectl exec` vào pod và chạy scenario thủ công.

---

## 8. Prometheus dense-window enrichment

AI Engine V4 detect dùng BOCPD/EWMA và BARO RCA. Cơ chế này cần time-series dày hơn là vài alert event rời rạc.

Executor vì vậy sẽ cố enrich telemetry đầu vào:

```text
incoming telemetry_window
  -> deployment_of(window)
  -> Prometheus query_range
  -> build dense `container_resource_usage` points
  -> dùng dense window cho /v1/detect nếu có
  -> fallback về telemetry_window gốc nếu Prometheus disabled/unavailable
```

Memory query hiện tại:

```text
container_memory_working_set_bytes{namespace="<ns>", pod=~"<deployment>-.*", container!="", image!=""}
```

Verify health query hiện tại:

```text
service_error_rate =
sum(rate(http_requests_total{status=~"5.."}[2m]))
/
sum(rate(http_requests_total[2m]))
```

Env cần có:

```text
CDO_PROMETHEUS_URL
CDO_PROM_WINDOW_S
CDO_PROM_STEP_S
CDO_PROM_TIMEOUT_S
```

Nếu `CDO_PROMETHEUS_URL` rỗng, Executor sẽ bỏ qua dense-window enrichment.

---

## 9. Observability evidence model

Evidence phải trace được bằng `correlation_id`.

| Evidence source | Cần capture |
|---|---|
| Prometheus | Alert firing, query results, pre/post metrics |
| Alertmanager | Receiver config và delivered alert |
| Forwarder logs | alert count, signal count, SQS sent count |
| SQS metrics | queue depth, DLQ count, receive/delete count |
| Executor stdout | JSON audit chain: alert, detect, decide, safety, execute, verify |
| CloudWatch Logs | audit events query được theo `correlation_id` |
| S3 Object Lock | per-incident audit JSON bất biến |
| Grafana | dashboard screenshots cho cluster/self-heal health |
| Kubernetes | rollout status, pod status, `kubectl auth can-i`, Kyverno denies |

Audit chain tối thiểu:

```text
alert_received
prom_window_built
detect_called
detect_response_received
pre_decide_decision
idempotency_lock_acquired
decide_called
action_plan_received
safety_passed / safety_denied
rollback_snapshot_captured
execute_done / execute_skipped
verify_called
verify_done
incident_closed / rollback_done / escalated
```

---

## 10. Security và isolation

Security boundaries:

1. AI Engine không giữ kubeconfig và không mutate Kubernetes.
2. Forwarder chỉ gửi message vào SQS.
3. Executor ServiceAccount `tf3-cdo-controller` có namespace-scoped RoleBinding cho `tenant-a` và `tenant-b`.
4. NetworkPolicy giới hạn traffic từ Executor sang AI.
5. Kyverno enforce guardrail ở value-level:
   - replicas <= 10
   - memory limit <= 4Gi
   - deployment mutation chỉ trong allowed namespaces
6. Telemetry logs phải được scrub trước khi gửi sang AI.

IRSA roles:

| ServiceAccount | Namespace | AWS access |
|---|---|---|
| `cdo-telemetry-forwarder` | `monitoring` | chỉ `sqs:SendMessage` |
| `tf3-cdo-controller` | `self-heal-system` | SQS receive/delete, S3 audit, DynamoDB lock, CloudWatch logs |
| `ai-engine` | `self-heal-system` | Bedrock/Secrets nếu bật LLM, S3/DynamoDB theo contract |

---

## 11. Runtime configuration checklist

Trước khi claim real observability evidence, cần verify:

| Check | Expected |
|---|---|
| `kube-prometheus-stack` pods | Ready trong `monitoring` |
| `PrometheusRule` | Được Prometheus load |
| Alertmanager receiver | Route tới `cdo-telemetry-forwarder.monitoring.svc.cluster.local:8080/alerts` |
| Forwarder pod | Ready và có SQS URL |
| Forwarder IRSA | Gửi được `SendMessage` vào SQS |
| SQS queue | `cdo-telemetry-dev` tồn tại |
| DLQ | Tồn tại và thấy metrics/alarm |
| Executor config | `CDO_TELEMETRY_QUEUE_URL` là URL thật, không phải placeholder |
| Executor command | Chạy `python main.py --watch` cho production mode |
| Executor IRSA | Receive/delete SQS, write S3, write DDB |
| `CDO_PROMETHEUS_URL` | Được set nếu cần dense-window detect |
| AI Engine | `/ready` OK trên port 8080 |
| Audit bucket/table | Khớp Terraform outputs |

---

## 12. Test flow v5.2

### 12.1 Alert-to-SQS test

```text
Trigger workload issue
  -> Prometheus alert firing
  -> Alertmanager POST /alerts
  -> Forwarder logs `alerts=N -> signals=M -> sqs_sent=M`
  -> SQS queue receives messages
```

Pass:

- Alert firing visible trong Prometheus/Alertmanager.
- Forwarder emit telemetry đúng contract shape.
- SQS message body có `tenant_id`, `signal_name`, `labels.namespace`, `labels.deployment`.

### 12.2 SQS-to-AI detect test

```text
Executor --watch
  -> drain SQS
  -> group incident
  -> optional Prometheus dense-window
  -> POST /v1/detect
```

Pass:

- Audit có `alert_received`, `detect_called`, `detect_response_received`.
- AI response có `anomaly_detected`, `confidence`, `severity`, `correlation_id`.

### 12.3 Full self-heal observability test

```text
Alert -> SQS -> Executor -> AI detect/decide -> Safety Gate
  -> snapshot -> dry-run -> execute
  -> post telemetry -> AI verify
  -> audit evidence
```

Pass:

- Unsafe action count = 0.
- Cross-tenant action bị deny.
- Mỗi incident có audit trail theo `correlation_id`.
- Chỉ claim real K8s mutation khi `CDO_K8S_MOCK=false`, Kubernetes client đã được cài trong image, và có kubectl evidence.

---

## 13. Known gaps và risks hiện tại

| Gap | Impact | Required action |
|---|---|---|
| Executor manifest dùng `sleep infinity` | Pod sẽ không tự consume SQS ở production | Đổi command sang `python main.py --watch` sau khi runtime validation xong |
| `CDO_TELEMETRY_QUEUE_URL` trong configmap còn placeholder | SQS consumer sẽ disabled nếu chưa thay | Điền Terraform output `sqs_queue_url` |
| `CDO_AUDIT_BUCKET` cần verify lại tên thật | S3 audit có thể chỉ còn stdout-only nếu env sai hoặc thiếu boto3 | Verify Terraform output và image deps |
| Deferred GitOps executor còn stub | TC-05/TC-06 không thể claim real GitOps auto-resolve | Mark designed-only hoặc implement Git -> ArgoCD |
| Dense-window phụ thuộc `CDO_PROMETHEUS_URL` | AI detect có thể chỉ nhận sparse alert-only telemetry | Set in-cluster Prometheus URL |
| Real evidence không nằm sẵn trong code | Production claim cần runtime proof | Capture kubectl, SQS, CloudWatch, S3, Prometheus outputs |

---

## 14. Tóm tắt flow v5.2

```text
Prometheus observes workload
  -> Alertmanager fires known-pattern alert
  -> CDO Forwarder normalizes to telemetry contract
  -> SQS buffers telemetry inside CDO boundary
  -> Executor consumes and enriches telemetry
  -> AI Engine V4 detects and decides
  -> Executor gates, snapshots, executes or denies
  -> Prometheus/K8s provide post-action telemetry
  -> AI verifies result
  -> Audit evidence is written to stdout, CloudWatch, and S3 Object Lock
```

Đây là bản observability design v5.2 hiện hành cho TF3 Self-Heal CDO-02.
