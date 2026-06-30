# Requirements Analysis - Task Force 3 Self-Heal Engine - CDO-02

**Doc owner:** CDO-02  
**Trạng thái:** Ready for W11 Pack #1 review  
**Cập nhật lần cuối:** 2026-06-26 (sync contract-new-4)  

## 1. Bối cảnh đề tài

Task Force 3 xây dựng **Self-Heal Engine** cho một nền tảng SaaS B2B đang vận hành hơn 200 microservices trên Kubernetes/EKS. Client là VP Engineering, đang gặp vấn đề on-call quá tải vì mỗi đêm có 2-4 page, trong đó khoảng 80% là các known patterns lặp lại như Pod OOMKilled, service stuck, queue backlog, cert expiring.

Client muốn xây một hệ thống tự động hóa xử lý sự cố theo pipeline:

```text
detect -> match runbook -> execute audited action -> verify -> escalate nếu fail
```

CDO-02 không xây AI model. Vai trò của CDO-02 là xây platform/infra để Self-Heal Engine chạy an toàn trên Kubernetes sandbox: nhận alert, gom context, gọi AI endpoint, kiểm tra safety gate, dry-run, execute action, verify kết quả, rollback/escalate nếu fail và ghi audit log.

## 2. Problem Statement

On-call engineers hiện đang mất nhiều thời gian cho các thao tác lặp lại, đặc biệt là những action có runbook rõ như restart deployment, scale worker hoặc xử lý OOMKilled. Nếu tự động hóa không có kiểm soát, hệ thống có thể gây unsafe action trên Kubernetes như thao tác sai namespace, scale quá mức, rollback sai target hoặc thiếu audit trail.

Vì vậy, yêu cầu của CDO-02 không chỉ là "gọi AI rồi execute", mà là xây một platform có guardrails rõ ràng:

- AI chỉ đưa ra decision/action plan.
- CDO enforce safety gate trước khi execute.
- Mọi action phải có dry-run, blast-radius, local rollback/runbook path, `verify_policy` và audit.
- Multi-tenant isolation phải rõ ràng giữa ít nhất 2 tenants.
- Nếu AI timeout, confidence thấp hoặc action không an toàn thì CDO không execute, mà escalate và ghi audit.

## 3. Phạm vi CDO-02 phụ trách

CDO-02 sẽ phụ trách các phần sau:

| Hạng mục | Trách nhiệm của CDO-02 |
|---|---|
| Platform architecture | Thiết kế workflow alert -> AI -> safety -> execute -> verify -> audit |
| Kubernetes sandbox | EKS/Kubernetes cluster, namespaces, sample workloads |
| Multi-tenant isolation | Ít nhất `tenant-a` và `tenant-b`, tách namespace và RBAC |
| Safety gate | Validate tenant, namespace, confidence threshold, action allow-list, `allowed_namespaces`, blast-radius, `verify_policy` |
| Execution layer | Executor/operator-style workflow để restart/scale/rollback theo action plan |
| Audit | Ghi audit log theo `correlation_id`, retention target >= 90 ngày |
| Observability | Logs, metrics, Kubernetes events; ưu tiên CloudWatch/Container Insights |
| Deployment/IaC | Terraform skeleton cho VPC, EKS, observability |
| AI integration | Consume 3 AI contracts, gọi AI endpoint theo schema đã ký |

## 4. Ngoài Phạm Vi

CDO-02 không làm các phần sau trong scope capstone:

- Không build AI model hoặc decision engine.
- Không cho AI gọi Kubernetes trực tiếp.
- Không làm production traffic; chỉ sandbox + synthetic workload.
- Không làm multi-cluster federation.
- Không auto-discover pattern mới; chỉ implement/design known patterns.
- Không làm real PagerDuty/OpsGenie; Slack/mock pager là đủ.
- Không làm hash-chain crypto audit; S3 Object Lock hoặc append-only audit là đủ.
- Không làm cross-region replication.
- Auth cho AI API call dùng **Local Trust + K8s NetworkPolicy** (mTLS tùy chọn); không cần IAM SigV4 signing để gọi AI endpoint (confirmed new contract).

## 5. Hướng Khác Biệt Của CDO-02

- **Angle chọn:** K8s-heavy / Kubernetes Workflow Orchestration.
- **Why this angle:** TF3 là bài toán self-healing cho microservices chạy trên Kubernetes/EKS, nên CDO-02 chọn Kubernetes-native workflow để thao tác trực tiếp với workload, enforce RBAC theo namespace, kiểm soát blast-radius, dry-run, rollback, verify và audit. Trục tối ưu chính là **reliability** và **operational control**.
- **Trade-off chấp nhận:** Chi phí và độ phức tạp vận hành cao hơn serverless-first, nhưng đổi lại sát đề bài hơn, dễ chứng minh tenant isolation/RBAC hơn và phù hợp với self-heal trên Kubernetes workload.
- **Locked T3 W11:** 2026-06-23.

## 6. Pattern Mục Tiêu / Phạm Vi Dataset

Theo contract hiện tại của AI, phạm vi dữ liệu được căn theo **RE2/RE3 dataset** và hệ thống mẫu **Online Boutique**. Vì vậy CDO-02 cần align pattern demo với các signals/actions mà AI contract đã định nghĩa, thay vì tự đặt pattern theo tên quá chung chung.

### 6.1 Patterns build thật

CDO-02 build thật 5 patterns (confirmed với AI contract):

| Pattern | Signal kích hoạt | Action | pattern_type |
|---|---|---|---|
| Service stuck / latency spike | `service_latency_p95`, `service_unhealthy` | `RESTART_DEPLOYMENT` | urgent |
| Error rate spike / code-level fault | `service_error_rate`, `application_log_event`, `distributed_trace_error_event` | `RESTART_DEPLOYMENT` hoặc escalate | urgent |
| Memory pressure / OOM | `container_resource_usage`, `pod_oom_event` | `PATCH_MEMORY_LIMIT` hoặc escalate | urgent |
| Secret/cert expiry | `secret_expiry_warning` | `ROTATE_SECRET` (với allow-list + verify_policy bắt buộc) | deferred |

### 6.2 Patterns design-only

CDO-02 không còn pattern design-only. Queue/backpressure đã được nâng lên build-real (TC-05) từ W12 bằng cách dùng **synthetic signal injection** — inject telemetry payload `queue_backlog: 15000` qua script thay vì cần real queue infrastructure. Full flow: inject → `/v1/detect` → `/v1/decide` (SCALE_REPLICAS deferred) → Git commit → ArgoCD sync → `/v1/verify`.

Danh sách pattern đã confirmed với AI team và khớp với contracts đã ký 2026-06-25.

## 7. Yêu Cầu Phi Chức Năng Cho Infra

| NFR | Target | Justification |
|---|---|---|
| Multi-tenant isolation | >= 2 tenants trong sandbox | Hard requirement của TF3 |
| Auto-resolve rate | >= 60% trên >= 10 scenarios | Hard requirement của TF3 |
| Scenario simulation | >= 4h test window | Hard requirement của TF3 |
| Unsafe action | 0 unsafe action | Không delete prod namespace, không IAM modify |
| Audit retention | >= 90 ngày | SOC2/compliance requirement |
| Safety checkpoint | Dry-run, blast-radius, verify, rollback, circuit breaker | Hard requirement của TF3 |
| AI endpoint timeout handling | Timeout/503 -> no execute, escalate + audit | Prevent unsafe automated action |
| Observability | Logs + metrics + traces theo AI contract | Cần đủ dữ liệu cho detect/decide/verify và trace end-to-end |
| Cost control | W11 draft estimate, W12 refine with evidence | Tránh over-architecting |

## 8. Điểm Cần Làm Rõ Với Client/Trainer

Các điểm dưới đây cần hỏi trainer/mentor đóng vai client trước khi chốt final, vì nếu tự giả định sai thì có thể ảnh hưởng thiết kế W12.

| Chủ đề | Câu hỏi cần hỏi trainer/client | Ảnh hưởng nếu chưa chốt |
|---|---|---|
| ✅ Sandbox environment | **Resolved W11**: EKS thật bắt buộc — cluster `cdo-eks-cluster-dev` ACTIVE (K8s 1.30, us-east-1). Namespace `platform`, `tenant-a`, `tenant-b` tạo thành công. Evidence: `02_infra_design.md` Section 15. | - |
| Region | Client/trainer có bắt buộc `us-east-1` theo brief không? | Ảnh hưởng Terraform variables, cost estimate, deployment |
| ✅ Audit storage | **Resolved W11**: S3 Object Lock bắt buộc, dùng **Governance Mode** (trainer feedback). Governance cho phép admin với `s3:BypassGovernanceRetention` unlock khi cần trong sandbox; Compliance Mode hoàn toàn không xóa được kể cả admin. | - |
| Auto-resolved definition | Một incident được tính auto-resolved khi action execute thành công hay khi metrics trở lại normal sau verify? | Ảnh hưởng test report và success criteria |
| Blast-radius limit | Một lần self-heal được thao tác tối đa bao nhiêu deployment/replica/namespace? | Ảnh hưởng safety gate |
| Escalation policy | Retry mấy lần trước khi escalate? Escalation message cần format Slack/Markdown/JSON? | Ảnh hưởng workflow và AI response |
| Observability requirement | Traces trong AI contract cần triển khai đầy đủ ở W12 hay chấp nhận phased implementation? | Ảnh hưởng tool choice: CloudWatch, Prometheus, X-Ray/OpenTelemetry |
| Offline simulation | AI contract đã định nghĩa Mock Mode cho RE2/RE3; cần trainer xác nhận Mock Mode có đủ evidence cho W12 demo không. | Ảnh hưởng demo và test evidence |

Trong khi chờ trainer/client confirm, CDO-02 sẽ ghi các điểm này là **assumption**, không xem là quyết định cuối cùng.

## 9. Phụ Thuộc Contract Giữa AI Và CDO

AI team đã publish 3 contracts tại repo `AIops-g4/Capstone-Phase-2-Code/tf-3/ai/contracts`. CDO-02 cập nhật requirement theo các điểm chính dưới đây.

Mục tiêu của CDO-02 trong Pack #1 là chứng minh platform design **consume được contract của AI**, không tự thiết kế lệch interface. Các phần telemetry, API integration, security và deployment của CDO-02 sẽ bám theo 3 contract này, trừ các điểm cần push-back/clarify ở mục 9.4.

### 9.1 Telemetry Contract

CDO-02 cần thu thập/chuẩn hóa và gửi các signals sau cho AI:

| Signal | CDO responsibility | Used for |
|---|---|---|
| `service_error_rate` | Tính từ error/request counters theo cửa sổ trượt | Detect và verify lỗi service |
| `service_latency_p95` | Đọc latency p95 từ metrics source | Detect service stuck/latency spike |
| `service_throughput_rps` | Đọc RPS theo cửa sổ trượt từ Prometheus/OTel | Detect tải bất thường, hỗ trợ scale decision |
| `application_log_event` | Parse logs ERROR/stack trace sau khi scrub PII/secret | Diagnose code-level fault |
| `distributed_trace_error_event` | Parse traces có lỗi span | Diagnose lỗi liên dịch vụ |
| `container_resource_usage` | Đọc memory working set bytes theo container/pod | Detect memory pressure/OOM prevention |
| `pod_oom_event` | K8s Node lifecycle event khi container bị OOMKilled | Trigger urgent `PATCH_MEMORY_LIMIT` hoặc escalate |
| `container_restart_count` | kube-state-metrics restart counter | Detect CrashLoopBackOff → `ROLLOUT_UNDO` |
| `service_unhealthy` | K8s Kubelet probe fail event | Trigger urgent `RESTART_DEPLOYMENT` |
| `queue_backlog` | SQS/RabbitMQ message backlog metrics | Detect nghẽn hàng đợi → deferred `SCALE_REPLICAS` |
| `db_connection_pool_saturation` | Database monitor / APM agent | Detect cạn kiệt connection pool |
| `secret_expiry_warning` | Secrets Manager / Cert Manager event | Trigger deferred `ROTATE_SECRET` |

Yêu cầu chung từ AI contract:

- Mọi signal phải có `tenant_id`.
- Với CDO-02, tenant ID là `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` — **confirmed** trong deployment contract 2026-06-25.
- Timestamp dùng RFC3339 UTC với độ chính xác millisecond (ví dụ: `2026-06-25T10:00:00.123Z`).
- Trường `labels` là optional, nhưng **`labels.system` là required** khi có labels — phải khai báo tên/mã hệ thống (ví dụ: `"system": "E-COMMERCE"`). Telemetry không có `labels.system` sẽ bị AI reject 400.
- Với RE2/RE3, CDO preprocessor đọc `metrics.csv`, `logs.csv`, `traces.csv`, chuẩn hóa signal rồi đưa vào executor/AI API path. SQS chỉ là buffer nội bộ nếu CDO tự chọn, vì AI contract mới chưa cung cấp queue ARN.
- CDO phải lọc/mã hóa PII trước khi gửi log sang AI.

CDO-02 sẽ đáp ứng bằng cách:

- Thiết kế telemetry pipeline ưu tiên CloudWatch/Container Insights/Prometheus-compatible metrics.
- Với Offline Simulation Mode, thiết kế preprocessor đọc CSV RE2/RE3 và gửi signal đã chuẩn hóa vào executor. Nếu dùng SQS, CDO owns queue cho tới khi AI xác nhận queue contract.
- Chuẩn hóa metrics/logs/traces thành JSON trước khi gọi AI API.
- Gắn `tenant_id`, `correlation_id` và timestamp UTC cho mọi request.
- Với W11 Pack #1, mô tả schema và nguồn dữ liệu; W12 mới thu evidence thật từ sandbox.
- Traces được giữ trong schema theo AI contract; mức triển khai thực tế sẽ được chốt trong W12 plan và phụ thuộc thời gian tích hợp OpenTelemetry/X-Ray.

### 9.2 AI API Contract

Endpoint AI cung cấp:

```text
POST /v1/detect
POST /v1/decide
POST /v1/verify
```

Authentication và headers (bắt buộc cho mọi request):

```text
X-Tenant-Id: 6c8b4b2b-4d45-4209-a1b4-4b532d56a31c      ← confirmed chính thức (contract-new-2)
Idempotency-Key: UUID v4 (bắt buộc cho CẢ BA endpoints)
X-Dry-Run-Mode: "true" hoặc "false" (bắt buộc cho cả ba endpoints)
X-Correlation-Id: UUID v4 (tùy chọn cho detect; bắt buộc cho decide/verify)
```
Không dùng Authorization SigV4 — Auth cho AI endpoint là K8s NetworkPolicy in-cluster (Local Trust). SigV4 chỉ cần cho AWS services (S3, DynamoDB, CloudWatch).

> **Ghi chú auth (updated 2026-06-25 → new contract)**: Auth cho AI endpoint là **Local Trust + K8s NetworkPolicy** (mTLS tùy chọn) — CDO Executor không cần SigV4 signing để gọi AI in-cluster. K8s NetworkPolicy restrict chỉ pods có label `app=cdo-self-heal-controller` mới được reach port 8080 của AI Engine. IRSA/EKS Pod Identity vẫn cần cho CDO Executor gọi các AWS services (S3, DynamoDB, CloudWatch, Secrets Manager).

Luồng tích hợp (schema chốt contract-new-4, 2026-06-26):

```text
[1] POST /v1/detect
    Request:  idempotency_key, dry_run_mode, telemetry_window[], optional correlation_id
    Response: anomaly_detected, severity, anomaly_context (full object), confidence, reasoning, correlation_id

[1.5] CDO PRE-DECIDE GATE — chạy ngay sau [1], trước khi gọi [2]
    CDO tự quyết định có tiếp tục để hệ thống tự xử lý hay không.
    AI Engine là bộ não match pattern; CDO là bên quyết định mức độ tin tưởng để tự động hoá.

    Condition                                          | CDO action              | Audit reason
    ---------------------------------------------------|-------------------------|---------------------------
    anomaly_detected = false                           | Đóng quiet, no action   | no_anomaly
    confidence < 0.5                                   | Discard (likely noise)  | low_confidence_discard
    confidence 0.5–0.79 + severity LOW/MEDIUM          | Log warning, no action  | low_confidence_no_action
    confidence 0.5–0.79 + severity HIGH/CRITICAL       | Escalate ngay           | low_confidence_escalated
    Flapping: service bị detect lần 3+ trong 10 phút  | Escalate                | flapping_escalated
    Maintenance window active                          | Suppress                | maintenance_suppressed
    confidence >= 0.8 + severity MEDIUM/HIGH/CRITICAL  | Tiếp tục → gọi [2]     | proceed_to_decide

    Nguyên tắc: CDO KHÔNG tự filter theo fault type — AI Engine là bên biết pattern nào nó
    handle được. Nếu AI không match pattern → AI tự trả confidence thấp → confidence gate bắt.

[2] POST /v1/decide
    Request (bắt buộc): correlation_id, idempotency_key, dry_run_mode,
                        anomaly_context: <FULL object từ detect response — bắt buộc theo contract-new-4>
    Response: matched_runbook, pattern_type, action_plan[], blast_radius_config, verify_policy, cost_cap_exceeded,
              correlation_id, idempotency_key, dry_run_mode (echoed back)
              ⚠ AI KHÔNG trả rollback_snapshot — CDO tự capture TRƯỚC khi execute:
                urgent path → đọc K8s API lấy current state → lưu audit log
                deferred path → ghi Git commit SHA hiện tại → lưu audit log
    action_plan[] item: { action, target: "deployment/<name>", params: {namespace: "..."}, ... }

[3] CDO execute action (theo pattern_type):
    - urgent: CDO capture snapshot → execute trực tiếp K8s API (RESTART_DEPLOYMENT, PATCH_MEMORY_LIMIT, ROLLOUT_UNDO)
    - deferred: CDO capture snapshot (git SHA) → tạo Git commit/PR → ArgoCD sync (SCALE_REPLICAS, ROTATE_SECRET)
    CDO ghi lại: action, target string, status (COMPLETED | FAILED)

[4] POST /v1/verify
    Request (bắt buộc): correlation_id, idempotency_key, dry_run_mode,
                        action_executed: { action, target, status: "COMPLETED"|"FAILED",
                                           execution_time_seconds (optional) },
                        post_telemetry_window[]
    Response: success, regression_detected (boolean),
              next_action: "DONE"|"RETRY"|"ROLLBACK"|"ESCALATE",
              escalation_bundle (chỉ có khi next_action=ESCALATE)

CDO phải xử lý đầy đủ 4 giá trị next_action:
    - DONE      → close incident, ghi audit incident_closed
    - RETRY     → retry action với same pattern, ghi audit retrying
    - ROLLBACK  → chạy rollback dùng snapshot CDO đã capture trước execute (từ audit log) để khôi phục trạng thái trước action (kubectl rollout undo / revert manifest về state snapshot), ghi audit rollback_done
    - ESCALATE  → gửi escalation_bundle lên channel cảnh báo, ghi audit escalated (không execute thêm)
```

Các action AI contract định nghĩa (enum cố định):

```text
RESTART_DEPLOYMENT
PATCH_MEMORY_LIMIT
SCALE_REPLICAS
ROLLOUT_UNDO
ROTATE_SECRET
```

**Xử lý `pattern_type` (CDO bắt buộc phân biệt):**

- `pattern_type: "urgent"` → CDO execute trực tiếp qua Kubernetes API sau khi safety gate pass.
- `pattern_type: "deferred"` → CDO **không được** direct mutate Kubernetes; phải tạo Git commit hoặc PR để GitOps sync về cluster.

**Xử lý `cost_cap_exceeded: true`:** AI chuyển sang rule-based fallback. CDO vẫn execute action plan bình thường nhưng cần log cảnh báo và thông báo team.

SLA/API behavior từ contract (cập nhật W11):

- `/v1/detect` p99 < 300ms.
- `/v1/decide` p99 < 3000ms (LLM Bedrock); fallback rule-based p99 < 500ms.
- `/v1/verify` p99 < 500ms.
- Availability target 99.9%.
- Rate limit: `/v1/detect` 100 RPS/tenant; `/v1/decide` và `/v1/verify` 10 RPS/tenant.
- `400`: không retry tự động.
- `403 Forbidden`: `X-Tenant-Id` header không khớp `tenant_id` trong payload — không retry, ghi audit `tenant_mismatch`.
- `409`: trùng `Idempotency-Key`.
- `429`: exponential backoff (response có header `Retry-After`).
- `503`: CDO phải fallback bằng static runbook hoặc escalation.

CDO-02 sẽ đáp ứng bằng cách:

- Xây executor/safety gate consume `action_plan[]` từ `/v1/decide`.
- Chỉ execute các action nằm trong allow-list của contract mới: `RESTART_DEPLOYMENT`, `PATCH_MEMORY_LIMIT`, `SCALE_REPLICAS`, `ROLLOUT_UNDO`, `ROTATE_SECRET`.
- `ROTATE_SECRET` được xác nhận là **build thật** (confirmed từ AI contract). CDO implement với safety gate đầy đủ: chỉ thực thi khi signal `secret_expiry_warning` trigger, target `secret_name` phải nằm trong allow-list đã định nghĩa, và bắt buộc có `verify_policy`.
- Validate `tenant_id`, target namespace, `allowed_namespaces`, blast-radius, local rollback/runbook path và `verify_policy` trước khi execute.
- Dùng `Idempotency-Key` (bắt buộc cho cả ba endpoints, UUID v4). **DynamoDB idempotency lock chỉ áp dụng cho `/v1/decide`** — lock conditional write ngăn duplicate execution của cùng action. `/v1/detect` và `/v1/verify` dùng key cho mục đích audit trail, không có lock.
- Gửi `X-Dry-Run-Mode` header bắt buộc cho mọi request.
- Với `pattern_type: "urgent"`: execute trực tiếp qua Kubernetes API sau safety gate.
- Với `pattern_type: "deferred"`: **không direct mutate Kubernetes**; tạo Git commit/PR để ArgoCD sync.
- Khi nhận `cost_cap_exceeded: true` (AI đã chuyển sang rule-based fallback): log cảnh báo, vẫn execute action plan bình thường, thông báo team. 4 điều kiện kích hoạt rule-based fallback: (1) chi phí vượt $50/ngày/tenant; (2) Bedrock trả HTTP 429; (3) AI endpoint downtime/timeout; (4) LLM parse failure.
- Với `429`, dùng retry/backoff theo contract (header `Retry-After`).
- Với `503`, mặc định không tự ý execute; CDO sẽ escalate + audit, trừ khi static runbook fallback đã được AI/CDO thống nhất.

### 9.3 Deployment Contract

Theo contract AI:

- Theo contract AI mới nhất tại commit `08ed368`, AI Engine được triển khai theo mô hình **Self-Hosted (In-Cluster)**.
- AI team bàn giao **OCI-compliant container image** để CDO-02 tự pull và deploy trực tiếp vào EKS của mình.
- Endpoint tích hợp mục tiêu không còn là shared endpoint dùng chung, mà là service nội bộ trong cluster, ví dụ:
  `http://ai-engine.self-heal-system.svc.cluster.local:8080/`
- Auth: **Local Trust (mTLS tùy chọn)** — bảo mật bởi K8s NetworkPolicy in-cluster, không dùng IAM SigV4 cho AI endpoint.
- Tenant ID cho CDO-02: `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` (**confirmed** trong deployment contract 2026-06-25).
- AI service chạy trong namespace `self-heal-system`, port `8080`, không public Internet.
- Health endpoints: `GET /health`, `GET /ready`, `GET /metrics`.
- Logs: CloudWatch Logs.
- Metrics: Prometheus endpoint.
- Traces: OpenTelemetry -> Jaeger hoặc AWS X-Ray.
- Audit: S3 Object Lock Governance Mode, retention tối thiểu 90 ngày.

CDO-02 sẽ đáp ứng bằng cách:

- Thiết kế network path để CDO executor gọi AI endpoint nội bộ theo deployment contract.
- Đảm bảo CDO executor pod có label hợp lệ để K8s NetworkPolicy cho phép reach AI endpoint (Local Trust).
- Gắn tenant ID `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` cho requests của CDO-02.
- Ghi log request/response theo `correlation_id` để trace được end-to-end.
- Thiết kế audit storage tương thích S3 Object Lock 90 ngày.
- Tách rõ AI endpoint là decision service; CDO executor là nơi enforce safety và execute action, trừ khi AI/CDO thống nhất lại boundary khác.

### 9.4 Các điểm đã chốt với AI (resolved 2026-06-25)

Deployment contract mới đã chốt ranh giới theo hướng CDO-02 yêu cầu: **AI chỉ decide, CDO executor mới mutate Kubernetes**. AI Engine không giữ kubeconfig và không gọi Kubernetes/EKS API trực tiếp.

Tất cả các điểm dưới đây đã được xác nhận trong 3 contracts đã ký:

- ✅ Tenant UUID `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` — confirmed trong deployment contract.
- ✅ SQS là internal CDO buffer (CDO owns). AI không pull từ SQS — confirmed trong telemetry contract section 2.5.C.
- ✅ `X-Dry-Run-Mode` header bắt buộc cho cả ba endpoints.
- ✅ `Idempotency-Key` bắt buộc cho cả ba endpoints.
- ✅ `/v1/decide` SLA p99 < 3000ms (LLM Bedrock), < 500ms (fallback rule-based).
- ✅ Rate limit: `/v1/detect` 100 RPS/tenant; `/v1/decide` và `/v1/verify` 10 RPS/tenant.
- ✅ `pattern_type: "deferred"` — CDO tạo Git commit/PR, không direct mutate K8s.
- ✅ Dead-Letter Queue (DLQ) bắt buộc khi telemetry bị AI reject (400) — confirmed telemetry contract section 2.5.B.
- ✅ **CDO self-capture rollback snapshot (contract-new-4)**: AI KHÔNG trả `rollback_snapshot`. CDO phải capture TRƯỚC khi execute — urgent path: đọc K8s API lấy current state (`memory_limit`, `replica_count`, `image_tag`) → lưu audit log; deferred path: ghi Git commit SHA hiện tại → lưu audit log. Dùng để restore khi `/v1/verify` trả `next_action=ROLLBACK`.
- ✅ **Idempotency lock scope (contract-new-4 §3.D)**: DynamoDB lock CHỈ áp dụng cho `/v1/decide`. `/v1/detect` và `/v1/verify` dùng Idempotency-Key cho audit trail, không lock.
- ✅ **403 Forbidden (contract-new-4)**: Trả về khi `X-Tenant-Id` header không khớp `tenant_id` trong payload — CDO xử lý bằng audit + retry sau khi kiểm tra header.
- ✅ **CDO controller SA namespace (deployment contract-new-4 §3.D)**: Contract yêu cầu `tf3-cdo-controller` ServiceAccount nằm trong namespace `self-heal-system`. CDO hiện thiết kế executor trong `platform` — cần resolution W12 trước khi apply manifest.

## 10. Giả Định

- Team chính thức là **CDO-02**.
- CDO-02 đã chốt angle **K8s-heavy / Kubernetes Workflow Orchestration**.
- Sandbox target là AWS/EKS; cluster `cdo-eks-cluster-dev` đã ACTIVE (K8s 1.30, us-east-1, account 938145531618). Evidence thật thu được T6 W11 — xem `evidence/w11-ai-contract-sync/EKS_RUNTIME_EVIDENCE_REPORT.md`.
- Region mặc định theo client brief là `us-east-1`, trừ khi trainer/mentor yêu cầu khác.
- Observability theo contract AI gồm CloudWatch Logs, Prometheus metrics endpoint và OpenTelemetry traces về Jaeger hoặc AWS X-Ray.
- Audit storage: CDO-02 dùng S3 Object Lock **Governance Mode**, retention tối thiểu 90 ngày (theo trainer feedback W11). Deployment contract AI nói Compliance mode — CDO không theo vì Compliance không xóa được kể cả admin.
- Idempotency lock theo deployment contract AI dùng DynamoDB conditional write; TTL 24 giờ để ngăn replay attack và duplicate execution trong vòng 1 ngày. CDO-02 ưu tiên DynamoDB để khớp AWS-native design.
- CDO-02 có thể dùng mock/skeleton AI endpoint từ T6 W11 đến trước integration session W12.

## 11. Câu Hỏi Mở

Tổng hợp trạng thái các câu hỏi với AI team và trainer/mentor.

### 11.1 Đã chốt với AI team (resolved 2026-06-25)

1. ✅ **5 build patterns confirmed**: service stuck/latency spike, error rate spike/code-level fault, memory pressure/OOM, secret/cert expiry, queue/backpressure (TC-05 synthetic inject). Schema I/O chốt trong contract-new-2.
2. ✅ **0 design-only**: queue/backpressure (`SCALE_REPLICAS`) đã nâng lên build-real (TC-05) qua synthetic `queue_backlog` signal injection.
3. ✅ Signal naming đã chuẩn hóa theo telemetry contract mới (ví dụ: `service_error_rate`, không phải `istio_request_error_rate`).
4. ✅ **Offline Simulation Mode / Mock Mode** — AI contract đã định nghĩa Mock Mode cho RE2/RE3 (deployment contract section Offline Simulation Mode). Trainer confirm là đủ evidence cho W12 demo.
5. ✅ **AI skeleton endpoint URL** — endpoint nội bộ: `http://ai-engine.self-heal-system.svc.cluster.local:8080/` (confirmed deployment contract). CDO dùng endpoint này khi deploy AI image vào EKS.
6. ✅ **503 fallback**: CDO escalate + audit, không execute mặc định (static runbook fallback nếu AI/CDO đã thống nhất).
7. ✅ **SQS CDO-internal**: confirmed trong telemetry contract section 2.5.C.
8. ✅ **I/O schema chốt (contract-new-4, 2026-06-26)**: `/v1/decide` request bắt buộc `anomaly_context` (full object từ detect); response bắt buộc `matched_runbook`, `pattern_type`, `action_plan[]`, `blast_radius_config`, `verify_policy`, và echo-back `correlation_id`, `idempotency_key`, `dry_run_mode` — **AI KHÔNG trả `rollback_snapshot`** (removed in contract-new-4); `/v1/verify` request bắt buộc `action_executed` ({action, target string, status COMPLETED|FAILED}) và `post_telemetry_window` (required từ contract-new-4); response bắt buộc `next_action` (DONE|RETRY|ROLLBACK|ESCALATE) và `regression_detected`; `escalation_bundle` khi `next_action=ESCALATE`. Action target format: `"target": "deployment/<name>"` (string); namespace qua `params.namespace`. DLQ alert threshold: > 0.5% malformed trong 5 phút.

### 11.2 Cần xác nhận với trainer/mentor (W12)

1. ✅ **Resolved W11**: S3 Object Lock Governance Mode — confirmed từ trainer feedback W11. Governance cho phép admin unlock khi cần; Compliance thì không xóa được (CDO giữ Governance).
2. Trainer có yêu cầu region khác `us-east-1` không? — CDO-02 giả định `us-east-1` theo client brief.
3. ✅ **Resolved W11 T6**: CDO đã apply Terraform + manifests lên EKS thật (`cdo-eks-cluster-dev` ACTIVE). Evidence tại `evidence/w11-ai-contract-sync/` và `infra/BUILD_GUIDE_T6.md`.

## 12. Checklist Hoàn Thành Pack #1

- [x] CDO angle locked. (K8s-heavy, AI boundary: AI decides, CDO executes — locked T3 W11)
- [x] Build/design-only patterns confirmed with AI. (5 build-real, 0 design-only — confirmed 2026-06-25)
- [x] AI contract open questions documented và resolved. (Section 11.1 — tất cả 7 items đã ✅)
- [x] NFR table reviewed by team. (Section 7)
- [x] Giả định đã được xác nhận hoặc đánh dấu là rủi ro. (Section 10)
- [x] Tenant ID confirmed. (`6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` — confirmed deployment contract 2026-06-25)
- [x] 12 telemetry signals aligned với AI telemetry contract. (Section 9.1)
- [x] Auth AI endpoint: Local Trust + K8s NetworkPolicy (updated từ IAM SigV4 theo new contract). (Section 9.2)
- [x] ROTATE_SECRET confirmed build thật. (Section 6.1, Section 9.2)
- [ ] File committed as Pack #1 evidence. (chờ git commit)
