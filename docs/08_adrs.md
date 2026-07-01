# Architecture Decision Records - Task Force 3 Self-Heal Engine - CDO-02

**Doc owner:** CDO-02  
**Trạng thái:** Ready for W11 Pack #1 review  
**Cập nhật lần cuối:** 2026-07-01 (thêm ADR-010 alert-source, ADR-011 runbook-DSL)  

ADR là nơi ghi lại các quyết định kiến trúc quan trọng, lý do chọn và trade-off. File này append-only; nếu decision thay đổi ở W12 thì thêm ADR mới hoặc đánh dấu ADR cũ là superseded.

---

## ADR-001 - Chọn K8s-heavy / Kubernetes Workflow Orchestration

- **Status:** Accepted
- **Date:** 2026-06-23

### Context

TF3 là bài toán Self-Heal Engine cho hệ thống hơn 200 microservices chạy trên Kubernetes/EKS. Các action cần demo như restart deployment, scale worker, adjust memory limit, verify pod/metrics đều liên quan trực tiếp đến Kubernetes workload.

### Decision

CDO-02 chọn angle **K8s-heavy / Kubernetes Workflow Orchestration**. CDO executor sẽ chạy gần Kubernetes workload, nhận action plan từ AI, enforce safety gate và execute action qua Kubernetes API.

### Consequences

- Pro: Sát đề TF3 và dễ demo self-heal thật trên Kubernetes.
- Pro: Dễ chứng minh RBAC, namespace isolation, blast-radius và audit.
- Trade-off: Chi phí và độ phức tạp cao hơn serverless-first.
- Trade-off: Team cần kiểm soát tốt Kubernetes manifests, RBAC và observability.

### Alternatives considered

- Serverless-first: ít vận hành hơn nhưng không sát thao tác Kubernetes.
- Managed-services heavy: dùng nhiều AWS service hơn nhưng khó thể hiện operator/workflow control trong cluster.
- Event-driven hybrid: mạnh về retry/queue nhưng dễ over-engineer trong thời gian capstone.

---

## ADR-002 - AI là decision service, CDO executor là execution boundary

- **Status:** Accepted (contracts confirmed 2026-06-25)
- **Date:** 2026-06-23

### Context

AI contract định nghĩa `/v1/detect`, `/v1/decide`, `/v1/verify` và trả `action_plan[]`. Deployment contract mới đã chốt AI Engine không giữ kubeconfig và không gọi Kubernetes/EKS API trực tiếp. Điều này khớp boundary CDO-02 chọn: AI là decision service, CDO là execution control plane.

### Decision

CDO-02 chọn boundary: **AI chỉ decide, CDO executor mới execute**. AI trả action plan; CDO validate tenant, namespace, `allowed_namespaces`, blast-radius, local rollback/runbook path, `verify_policy` rồi mới execute hoặc deny/escalate.

Khi AI trả `pattern_type: "urgent"`, CDO executor gọi Kubernetes API trực tiếp sau safety gate (RTO target < 60s). Khi AI trả `pattern_type: "deferred"`, CDO tạo Git commit hoặc PR để GitOps (ArgoCD) sync về cluster, không direct mutate Kubernetes.

### Consequences

- Pro: Rõ ownership giữa AI và CDO.
- Pro: CDO kiểm soát được zero unsafe action.
- Pro: Audit log tập trung qua CDO executor.
- Trade-off: CDO phải build executor/safety gate đầy đủ.
- Trade-off: CDO phải chịu trách nhiệm đầy đủ cho RBAC, safety gate và audit khi execute.

### Alternatives considered

- AI trực tiếp gọi Kubernetes API: nhanh hơn cho AI demo nhưng rủi ro quyền hạn và audit boundary.
- Shared execution giữa AI và CDO: linh hoạt nhưng dễ mơ hồ ownership.

---

## ADR-003 - Chọn namespace-based tenant isolation và RBAC least privilege

- **Status:** Accepted
- **Date:** 2026-06-23

### Context

TF3 yêu cầu multi-tenant ít nhất 2 tenants với RBAC isolation và zero unsafe action. CDO cần chứng minh tenant A không bị action nhầm sang tenant B.

### Decision

CDO-02 dùng namespace-based isolation:

```text
tenant-a
tenant-b
platform
```

Executor chạy trong `platform` namespace và chỉ được cấp quyền theo Role/RoleBinding cần thiết để thao tác target namespace đã cho phép.

### Consequences

- Pro: Dễ demo và dễ test cross-tenant deny.
- Pro: Phù hợp Kubernetes RBAC native.
- Pro: Scope vừa đủ cho capstone.
- Trade-off: Không mạnh bằng account/cluster-per-tenant isolation.
- Trade-off: Cần cẩn thận RoleBinding để tránh cấp quyền quá rộng.

### Alternatives considered

- Cluster-per-tenant: isolation mạnh nhưng quá nặng cho capstone.
- Shared namespace + label isolation: đơn giản nhưng khó chứng minh deny cross-tenant.

---

## ADR-004 - Chọn S3 Object Lock cho audit trail

- **Status:** Accepted, pending trainer confirmation for implementation depth
- **Date:** 2026-06-23

### Context

TF3 yêu cầu audit log tamper-evident, retention tối thiểu 90 ngày. AI deployment contract ghi audit target là S3 Object Lock; CDO-02 dùng **Governance Mode** (confirmed trainer feedback W11) — Governance cho phép admin với quyền `s3:BypassGovernanceRetention` unlock khi cần cho sandbox, trong khi Compliance hoàn toàn không xóa được ngay cả admin.

### Decision

CDO-02 chọn S3 Object Lock làm audit storage target. Audit record sẽ được ghi theo `correlation_id`, bao gồm alert, detect, decide, safety, dry-run, execute, verify, rollback/escalate.

### Consequences

- Pro: Khớp hard requirement và AI contract.
- Pro: Dễ query bằng Athena hoặc inspect object.
- Pro: Có retention rõ ràng.
- Trade-off: Setup Object Lock cần tạo bucket đúng cấu hình từ đầu.
- Trade-off: Cost cao hơn log local hoặc CloudWatch-only.

### Alternatives considered

- CloudWatch Logs only: dễ triển khai nhưng tamper-evident yếu hơn.
- Append-only database: query tốt nhưng cần build thêm storage logic.

---

## ADR-005 - Chọn CloudWatch + Prometheus-compatible metrics + OpenTelemetry schema

- **Status:** Accepted
- **Date:** 2026-06-23

### Context

AI telemetry contract yêu cầu metrics, logs và traces: `service_error_rate`, `service_latency_p95`, `container_resource_usage`, `application_log_event`, `distributed_trace_error_event`.

### Decision

CDO-02 chọn observability stack theo hướng:

- CloudWatch Logs cho logs.
- Container Insights/Prometheus-compatible metrics cho metrics.
- OpenTelemetry schema tương thích Jaeger hoặc AWS X-Ray cho traces.
- SQS là **CDO-internal buffer** — telemetry contract-new-2 (Section 2.5.C) đã chốt AI không pull từ SQS. CDO Forwarder/Worker batch-push từ SQS sang `/v1/detect`. AI không giữ queue ARN và không cần biết SQS tồn tại.
- Với Offline Simulation Mode, dùng telemetry preprocessor đọc dataset, inject tenant UUID, chuẩn hóa signal và đưa vào executor/AI API path qua SQS buffer nội bộ.

W11 Pack #1 tập trung design/schema; W12 mới thu evidence thật từ sandbox hoặc simulation.

### Consequences

- Pro: Khớp telemetry contract của AI.
- Pro: Dễ tích hợp với AWS/EKS.
- Pro: Có thể demo logs/metrics trước, traces bổ sung nếu kịp.
- Trade-off: Triển khai đủ traces có thể tốn thời gian.
- Trade-off: Cần normalize telemetry trước khi gọi AI.
- Trade-off: Cần build preprocessor và có thể thêm SQS buffer nội bộ nếu replay volume cao.

### Alternatives considered

- CloudWatch-only: đơn giản hơn nhưng không đáp ứng trace signal đầy đủ.
- Full Prometheus/Grafana/Jaeger stack: mạnh nhưng nhiều moving parts cho capstone.

---

## ADR-006 - Chọn DynamoDB conditional write cho idempotency lock

- **Status:** Accepted
- **Date:** 2026-06-24

### Context

AI API Contract yêu cầu `Idempotency-Key` cho các request thay đổi trạng thái như `/v1/decide` và `/v1/verify`. Deployment Contract cũng mô tả nhu cầu idempotency lock để tránh execute cùng một action nhiều lần khi có retry hoặc lỗi mạng.

### Decision

CDO-02 chọn **DynamoDB conditional write** làm cơ chế idempotency lock mặc định. Mỗi action sẽ ghi lock theo `Idempotency-Key`; nếu key đã tồn tại, CDO từ chối execute trùng và ghi audit.

### Consequences

- Pro: AWS-native, phù hợp với kiến trúc trên AWS.
- Pro: Conditional write rõ ràng để chống race condition.
- Pro: Dễ audit và debug theo key.
- Trade-off: Cần thêm DynamoDB table và IAM permission.
- Trade-off: Với demo nhỏ, Redis/local lock có thể đơn giản hơn nhưng kém bền hơn.

### Alternatives considered

- Redis lock TTL: nhanh, đơn giản nhưng cần thêm runtime dependency.
- In-memory lock: dễ làm nhất nhưng không an toàn khi executor restart hoặc scale nhiều replicas.

---

## ADR-007 - Chấp nhận Mock Mode cho RE2/RE3 Offline Simulation

- **Status:** Accepted, pending trainer evidence confirmation
- **Date:** 2026-06-24

### Context

AI API Contract và Deployment Contract xác định RE2/RE3 là dataset offline tĩnh. Vì vậy luồng execute action như `RESTART_DEPLOYMENT` hoặc `SCALE_REPLICAS` sẽ chạy ở dạng giả lập: CDO ghi nhận action giả định, sau đó gửi `post_telemetry_window` từ dataset sang `/v1/verify`.

### Decision

CDO-02 chấp nhận **Mock Mode** cho luồng RE2/RE3 offline simulation để align với AI contract. Nếu trainer yêu cầu demo action thật, CDO-02 sẽ bổ sung một sandbox Kubernetes scenario riêng, nhưng không xem đó là nguồn verify chính cho RE2/RE3 dataset.

### Consequences

- Pro: Khớp contract AI và dataset offline.
- Pro: Giảm rủi ro build khi chưa có full live telemetry.
- Pro: Dễ tạo repeatable test scenario.
- Trade-off: Demo có thể bị xem là ít "real" hơn action thật trên Kubernetes.
- Trade-off: Cần giải thích rõ difference giữa simulation evidence và live sandbox evidence.

### Alternatives considered

- Action thật trên Kubernetes cho toàn bộ flow: thuyết phục hơn nhưng khó khớp RE2/RE3 offline telemetry.
- Chỉ dùng mock endpoint không có dataset: dễ làm nhưng evidence yếu hơn.

---

## ADR-008 - Chọn GitOps path (ArgoCD PR) cho `pattern_type: deferred`

- **Status:** Accepted
- **Date:** 2026-06-25

### Context

AI API Contract (commit 86b32e7) chốt rõ hai luồng xử lý dựa trên `pattern_type`:
- `"urgent"`: action khẩn cấp, CDO execute trực tiếp Kubernetes API.
- `"deferred"`: action tích lũy cấu hình (ví dụ SCALE_REPLICAS do queue_backlog), CDO **bắt buộc** không direct mutate Kubernetes mà phải tạo Git commit/PR để ArgoCD sync.

CDO-02 cần quyết định cụ thể cách implement path `"deferred"`.

### Decision

CDO-02 implement `pattern_type: "deferred"` bằng cách executor tự động tạo Git commit (hoặc PR nếu cần review) cập nhật manifest/Helm values, sau đó ArgoCD phát hiện thay đổi và sync về cluster. CDO không gọi Kubernetes API trực tiếp trong path này.

### Consequences

- Pro: Khớp AI contract, tránh state drift giữa Git và cluster.
- Pro: ArgoCD drift detection đảm bảo cluster luôn khớp Git.
- Pro: Có audit trail rõ (Git commit history + ArgoCD sync history).
- Trade-off: Latency cao hơn path `"urgent"` (Git commit + ArgoCD sync ~2-5 phút).
- Trade-off: CDO executor cần có quyền write vào Git repo và ArgoCD phải được cấu hình watch manifest repo.

### Alternatives considered

- Không implement deferred path: đơn giản hơn nhưng vi phạm AI contract.
- Manual PR workflow: có approval gate nhưng quá chậm cho self-heal automation.

---

## ADR-009 - Chọn Kyverno thay vì Gatekeeper cho Admission Control Layer

- **Status:** Accepted
- **Date:** 2026-06-25

### Context

Safety gate trong CDO executor là app-level check chạy trong process — nếu executor có bug, request vẫn đến Kubernetes API và được execute. RBAC kiểm soát verb nhưng không kiểm soát value: executor có thể `patch` Deployment với `replicas: 1000` hoặc `memory: 100Gi` mà RBAC không chặn được vì verb `patch` đã được cấp phép.

Cần lớp thứ 3 độc lập ở cluster level: Kubernetes Admission Webhook. API Server gọi webhook trước khi persist bất kỳ resource nào vào etcd, hoàn toàn nằm ngoài executor code path. CDO-02 phải chọn giữa 2 framework: **Kyverno** và **Gatekeeper (OPA)**.

### Decision

CDO-02 chọn **Kyverno** để implement Admission Control Layer với 3 ClusterPolicy:

1. `restrict-replicas-tenant-namespaces` — replicas ≤ 10 trong tenant-a, tenant-b
2. `restrict-memory-limit-tenant-namespaces` — memory limit ≤ 4Gi per container
3. `restrict-workload-mutation-namespace` — Deployment mutation chỉ trong namespace allowlist

### Why Kyverno

- **YAML-native policy**: Policy viết bằng Kubernetes YAML chuẩn. Team đã quen với YAML, không phải học ngôn ngữ riêng. Tốc độ viết và review nhanh hơn đáng kể.
- **Single-file per policy**: Mỗi rule là 1 `ClusterPolicy` CRD — deploy, edit, debug bằng `kubectl` như resource Kubernetes bình thường. Không có abstraction layer thêm.
- **Authoring speed**: 3 policy Kyverno tốn ~30 phút viết và test trong W12. Ưu tiên trong context 6 ngày build.
- **`validationFailureAction: Enforce`**: Block ngay tại admission, không phải audit-only — phù hợp với hard requirement "Zero unsafe action".
- **`background: false`**: Chỉ kiểm tra request mới, không scan existing resources liên tục — giảm noise trong demo environment.
- **Lightweight**: `admissionController.replicas=1` đủ cho sandbox. Không cần HA setup.

### Why NOT Gatekeeper (OPA)

- **Rego language**: Gatekeeper yêu cầu viết policy bằng Rego — functional language với cú pháp và tư duy hoàn toàn khác YAML/Go. CDO-02 không có Rego experience; learning curve không khả thi trong W12.
- **2-file structure**: Mỗi policy cần `ConstraintTemplate` (chứa Rego logic) + `Constraint` (instantiate). 3 policy = 6 files, gấp đôi so với Kyverno. ConstraintTemplate cũng yêu cầu hiểu CRD schema.
- **Verbose ConstraintTemplate**: Phần Rego không self-documenting — khó đọc lại trong buổi chấm khi panel hỏi "policy này làm gì".
- **OPA audit controller**: Gatekeeper chạy audit background scan định kỳ, có thể tạo confusion khi policy enforce chưa nhất quán ngay sau deploy.
- **Heavier default footprint**: Gatekeeper deploy nhiều component hơn (controller-manager, audit, webhook). Tốn node resource hơn Kyverno single-replica cho cùng mức coverage trong sandbox.

### Consequences

- **Pro:** 3 lớp bảo vệ độc lập — Safety Gate (app-level) → RBAC (verb-level) → Kyverno (value-level). "Zero unsafe action" không còn phụ thuộc đơn lẻ vào executor code path.
- **Pro:** Policy as code — commit vào Git cùng manifests, version-controlled, reviewable.
- **Pro:** Block tại API Server trước etcd — không bypass được kể cả khi executor có bug.
- **Trade-off:** 3 policy hiện tại chỉ cover `Deployment` resource. Nếu cần enforce trên `StatefulSet` hay `DaemonSet`, phải extend `kinds` list trong mỗi policy.
- **Trade-off:** `admissionController.replicas=1` không có HA — nếu Kyverno pod crash trong quá trình test, webhook fail-open (request đi qua không bị chặn). Chấp nhận cho sandbox scope.
- **Trade-off:** Policy misconfiguration (ví dụ block nhầm namespace hệ thống) có thể làm ArgoCD hoặc executor không deploy được. Cần test policy trên dry-run trước khi set `Enforce`.

### Alternatives considered

- **OPA Gatekeeper**: Admission webhook mạnh hơn, có audit controller và separation giữa policy schema và logic. Nhưng Rego learning curve quá cao cho W12 timeline. Rejected.
- **Custom ValidatingWebhookConfiguration**: Linh hoạt nhất nhưng phải viết webhook server, TLS cert, registration từ đầu. Không hợp lý cho scope 6 ngày. Rejected.
- **Chỉ dùng Safety Gate + RBAC (không có Layer 3)**: Đủ cho happy path demo nhưng không bịt được gap executor bug bypass và RBAC value blindness. Rejected — vi phạm trainer feedback về "Zero unsafe action" tại cluster level.

---

## ADR-010 - Chọn Alertmanager webhook → Forwarder → SQS làm alert source (poll K8s là fallback)

- **Status:** Accepted
- **Date:** 2026-07-01

### Context

Telemetry-contract §2.5.C chốt kiến trúc thu tín hiệu: Collector (Prometheus/OTel/Fluentd) ghi vào **SQS buffer nội bộ CDO**, rồi Forwarder/Worker batch-push sang `/v1/detect`; AI không biết SQS tồn tại. CDO-02 cần chọn **cụ thể nguồn phát alert real-time** đẩy vào SQS.

Bản build ban đầu dùng **Option-1: executor poll K8s pod-status mỗi 30s** (`executor/watcher.py`). Cách này đơn giản, near-real-time, chạy được không cần thêm component — nhưng lệch contract (không đi qua SQS buffer, không tách collector khỏi executor) và không bắt được signal chỉ có ở tầng metric (latency p95, error-rate, working-set memory) mà kube-state pod-status không thấy.

### Decision

CDO-02 chọn **Alertmanager webhook → Alert Forwarder → SQS** làm **nguồn chính**:

1. `kube-prometheus-stack` scrape kube-state-metrics / node-exporter / podinfo; `PrometheusRule` fire alert (`PodOOMKilled`, `ContainerCrashLooping`, `ImagePullBackOff`, `HighContainerMemory`, `HighLatencyP95`, `HighErrorRate`).
2. Alertmanager route mọi alert `firing` → webhook `POST /alerts` tới **Alert Forwarder** (`forwarder/`).
3. Forwarder chuẩn hóa alert → telemetry signal (12 enum, `labels.system=K8S_NATIVE`) → `sqs:SendMessage` vào `cdo-telemetry-*`.
4. Executor SQS consumer (`executor/sqs_source.py`) long-poll drain → `handle_incident` → `/v1/detect`.

**Poll K8s 30s (`watcher.py`) giữ làm fallback** (defense-in-depth): khi `CDO_TELEMETRY_QUEUE_URL` rỗng hoặc SQS lỗi, executor tự poll. `heal_cooldown_s` chống double-fire giữa 2 nguồn.

### Consequences

- **Pro:** Khớp đúng telemetry-contract §2.5.C — collector tách khỏi executor, đi qua SQS buffer (chịu tải burst, có DLQ `maxReceiveCount=3`).
- **Pro:** Bắt được signal tầng metric (latency/error-rate/memory working-set) mà pod-status poll không thấy.
- **Pro:** alertname ↔ signal_name ánh xạ 1-1, khai báo trong `PrometheusRule` (versioned), dễ audit tại buổi chấm.
- **Pro:** Fallback poll đảm bảo vẫn self-heal khi monitoring stack down → không single-point-of-failure.
- **Trade-off:** Thêm 3 thành phần vận hành (kube-prometheus-stack, Forwarder, SQS wiring) + IRSA `sqs:SendMessage` cho Forwarder.
- **Trade-off:** Alert latency phụ thuộc `for:` của PrometheusRule + scrape interval (~15–60s) — cho urgent OOM vẫn đạt RTO < 60s vì `pod_oom_event` fire gần tức thì.

### Alternatives considered

- **Chỉ poll K8s pod-status (Option-1)**: đơn giản nhất nhưng lệch contract, mù signal metric. Giữ làm fallback thay vì nguồn chính.
- **CloudWatch Alarms → SNS → SQS**: AWS-native nhưng metric K8s phải qua Container Insights (độ trễ + cost cao), khó map về 12 signal enum, và cột chặt vào CloudWatch thay vì Prometheus-compatible mà ADR-005 đã chọn.
- **Alertmanager webhook gọi thẳng `/v1/detect`**: bỏ SQS → vi phạm §2.5.C (mất buffer/DLQ, ghép collector vào AI path), không chịu được burst alert.

---

## ADR-011 - Runbook là catalog khai báo qua `action_plan[]` JSON, KHÔNG dùng DSL riêng

- **Status:** Accepted
- **Date:** 2026-07-01

### Context

Self-heal cần biểu diễn "runbook" — chuỗi bước chữa lành cho từng loại lỗi (OOM→patch memory, crashloop→restart, bad-deploy→rollback...). Câu hỏi kiến trúc: **runbook được viết bằng gì?** Một DSL/scripting riêng (YAML workflow, Rego, Python plugin, Argo Workflow) hay tái dùng schema contract sẵn có?

Rủi ro của DSL riêng: mỗi runbook mới là một đơn vị code/policy phải review về mặt an toàn; DSL đủ mạnh để rẽ nhánh/lặp thì cũng đủ mạnh để làm điều nguy hiểm (Turing-complete = không thể chứng minh "zero unsafe action" tĩnh). Ranh giới ADR-002 (AI decide, CDO execute) sẽ mờ nếu runbook chứa logic thực thi.

### Decision

CDO-02 **không xây DSL runbook riêng**. Runbook được biểu diễn thuần bằng **schema `action_plan[]` của ai-api-contract §3.2**:

- AI `/v1/decide` trả `matched_runbook` (tên định danh, vd `OOMPatchMemoryRunbook`) + `action_plan[]`, mỗi step là `{action ∈ 5 enum, target, params}`.
- "Ngôn ngữ runbook" = **enum action cố định** (`RESTART_DEPLOYMENT`, `PATCH_MEMORY_LIMIT`, `SCALE_REPLICAS`, `ROLLOUT_UNDO`, `ROTATE_SECRET`) + `pattern_type` (`urgent`/`deferred`) + `verify_policy` + `blast_radius_config`. Không rẽ nhánh, không vòng lặp, không biểu thức tùy ý.
- Catalog runbook là **dữ liệu** (bảng trong `06_runbook_library.md`; reference trong `mock_ai_server.py`), không phải code. Thêm runbook = thêm entry ánh xạ signal→action, không cần compiler/interpreter mới.
- Điều khiển vòng lặp (retry/rollback/escalate) do `/v1/verify.next_action` quyết định (4 giá trị enum), CDO thực thi — không nhúng trong runbook.

### Consequences

- **Pro:** Mọi runbook rút gọn về 5 action enum → safety gate kiểm tra tĩnh được (6 check), chứng minh "zero unsafe action" khả thi. Không có DSL Turing-complete để bypass.
- **Pro:** Ranh giới ADR-002 sạch: runbook chỉ mô tả *cái gì* (declarative), CDO quyết định *làm thế nào* (execute). AI không nhúng logic thực thi.
- **Pro:** Không phải build + test + version một DSL engine trong 6 ngày; tái dùng JSON schema đã FREEZE.
- **Pro:** Runbook mới không cần deploy code — chỉ cần AI trả tên + action_plan hợp lệ; CDO validate bằng enum có sẵn.
- **Trade-off:** Runbook đa bước phức tạp (điều kiện, phụ thuộc chéo service) không biểu diễn được — chấp nhận vì self-heal scope là các pattern nguyên tử; case phức tạp → `ESCALATE` cho người.
- **Trade-off:** Thêm loại action mới (ngoài 5 enum) cần sửa contract + safety gate + Kyverno, không "cắm nóng" bằng runbook. Đây là *chủ ý* — mọi khả năng thực thi mới phải qua review contract.

### Alternatives considered

- **YAML workflow DSL (kiểu Argo Workflows / Ansible playbook)**: biểu đạt mạnh, quen thuộc, nhưng thành bề mặt thực thi tùy ý → phải sandbox + review từng runbook; quá nặng và rủi ro an toàn cho capstone. Rejected.
- **Rego/OPA policy làm runbook**: đã loại vì learning curve ở ADR-009; và Rego hợp cho *validate* hơn *orchestrate*. Rejected.
- **Python plugin per runbook**: linh hoạt tối đa nhưng mỗi plugin là code thực thi tùy ý trong executor — phá vỡ "zero unsafe action" và ranh giới AI/CDO. Rejected.
- **Argo Workflows CRD**: mạnh cho multi-step orchestration nhưng thêm một control plane, một CRD engine phải vận hành/audit; thừa cho pattern nguyên tử. Rejected.
