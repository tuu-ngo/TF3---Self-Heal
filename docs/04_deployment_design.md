# Deployment & CI/CD Design - Task Force 3 Self-Heal Engine - CDO-02

**Doc owner:** CDO-02  
**Trạng thái:** Ready for W11 Pack #1 review  
**Last updated:** 2026-06-26 (sync contract-new-4 — abort criteria, probe config, rollout strategy, SA namespace conflict)  

## 1. Chiến lược IaC

### 1.1 Lựa chọn công cụ

CDO-02 chọn **Terraform** là công cụ IaC chính cho thiết kế triển khai của Self-Heal Engine. Lý do chính:

- Kiến trúc mục tiêu đang xoay quanh AWS và EKS, nên Terraform phù hợp để provision VPC, EKS, IAM, S3, DynamoDB và nền tảng observability.
- Terraform giúp tách rõ hạ tầng dùng chung và phần cấu hình theo môi trường.
- Terraform phù hợp với hướng skeleton/base infra đã mô tả trong `02_infra_design.md`.
- Terraform cũng khớp với các quyết định hiện có về `S3 Object Lock`, `DynamoDB conditional write` và observability stack.

State backend dự kiến:

- **Terraform version:** >= 1.10 (bắt buộc để dùng `use_lockfile = true` với S3 backend — feature không có ở version cũ hơn)
- **Remote state:** S3
- **State lock:** S3 lockfile (`use_lockfile = true`)
- **State separation:** 1 state chính cho environment `sandbox`

Ghi chú trạng thái hiện tại của repo:

- Đây là hướng thiết kế mục tiêu.
- Tại thời điểm cập nhật tài liệu này, mã Terraform trong `infra/envs/dev` chưa cấu hình backend S3.
- Repo vẫn đang có file state local `terraform.tfstate`, nên chưa thể nói phần remote state đã được triển khai xong.

CDO-02 không chọn CloudFormation hay CDK làm hướng chính trong capstone vì mục tiêu hiện tại là có một cấu trúc triển khai để review, để chia module, để plan/apply theo environment và để giảm coupling với code runtime.

Với scope hiện tại chỉ có **1 environment sandbox**, cách làm gọn nhất là:

- 1 S3 bucket cho remote state
- 1 state file cho `sandbox`
- 1 S3 lock file đi kèm state object

Hướng này đủ cho scope nhóm hiện tại, đồng thời ít moving parts hơn so với việc thêm DynamoDB chỉ để lock state.

### 1.2 Cấu trúc module

Cấu trúc IaC thực tế của CDO-02:

```text
infra/
  modules/
    vpc/                 # VPC, subnets, route tables, security groups
    eks/                 # EKS cluster, node groups, cluster access baseline
    iam/                 # IRSA executor + AI Engine, least-privilege policies
    observability/       # CloudWatch log groups, alarms (executor errors, Kyverno deny, DLQ rate)
    audit/               # S3 Object Lock (Governance), DynamoDB idempotency, SQS + DLQ
    kyverno/             # Kyverno Helm release (admission control layer 3)
    argocd/              # ArgoCD Helm release (GitOps engine)
  envs/
    dev/                 # wiring sandbox environment, terraform.tfstate
```

Ý nghĩa của cấu trúc này:

- `modules/` giữ logic dùng chung, có thể tái sử dụng cho nhiều environment.
- `envs/dev/` giữ wiring và biến cho sandbox environment duy nhất trong capstone.
- DynamoDB idempotency và SQS telemetry buffer nằm trong module `audit/` vì cùng nhóm dữ liệu bền vững.
- Namespace, RBAC, sample workloads được quản lý qua ArgoCD manifests trong `manifests/` — không qua Terraform module riêng.

Trong scope capstone, **sandbox** là môi trường duy nhất cần implement. Không cần mở rộng sang `staging` hoặc `prod` trong bản hiện tại nếu nhóm chưa có nhu cầu thật.

### 1.3 Quản lý state

**Trạng thái hiện tại: Local state — known gap, chấp nhận cho capstone scope.**

Terraform state hiện đang lưu local tại `infra/envs/dev/terraform.tfstate`. Đây là known gap được chấp nhận có chủ đích vì:

- Capstone chỉ có 1 người chạy `terraform apply` tại một thời điểm → không có race condition thực tế.
- Setup S3 backend cần tạo bucket trước khi có infra → bootstrap chicken-and-egg problem trong giai đoạn W11.
- Ưu tiên W11 là có skeleton/evidence commit, không phải hoàn thiện pipeline.

**Quy tắc bắt buộc khi dùng local state:**

- Chỉ một người chạy `terraform apply` tại một thời điểm — thông báo team trước khi chạy.
- Commit `terraform.tfstate` lên Git sau mỗi lần apply thành công để team có state mới nhất.
- Không commit `terraform.tfstate.backup`.
- `terraform plan` bắt buộc review trước khi apply.

**Known risk:**

| Risk | Mức độ | Mitigate |
|---|---|---|
| Hai người apply cùng lúc → state conflict | Thấp (1 người apply) | Thông báo team qua standup/Slack |
| State file chứa output values (ARN, endpoint) → lộ trong Git | Trung bình | Không commit secret thật vào state; dùng placeholder cho sensitive outputs |

**Target W12 nếu kịp:** Migrate lên S3 backend (`backend "s3"` + S3 lockfile). Không block W11 delivery.

## 2. CI/CD pipeline

### 2.1 Các stage trong pipeline

CDO-02 đề xuất **GitHub Actions** làm công cụ CI/CD chính. Pipeline cần bao phủ cả:

- IaC
- Kubernetes manifests/Helm values
- Runtime components của executor, collector, webhook/mock integration nếu có

Luồng tổng quát:

```text
PR opened -> Lint -> Test -> Scan -> Terraform Validate/Plan -> Review -> Merge -> Apply/Sync -> Smoke Test
```

Bảng stage đề xuất:

| Stage | Tool | What it does | Quality gate |
|---|---|---|---|
| Lint | GitHub Actions + markdownlint/yamllint/terraform fmt check | Kiểm tra format docs, YAML, Terraform | No formatting error |
| Test | GitHub Actions + unit/integration test command của repo | Chạy test cho runtime components nếu có | Test pass |
| Scan | Gitleaks + Trivy + Checkov/tfsec | Secret scan, image scan, IaC security scan | No exposed secret, no CRITICAL issue |
| Validate | Terraform validate | Kiểm tra cú pháp và wiring IaC | Validate pass |
| Plan | Terraform plan | Preview thay đổi hạ tầng theo environment | Plan reviewed |
| Review | PR approval | Kiểm tra kỹ thuật và security | Approval required |
| Apply | Terraform apply + GitOps sync | Provision infra và sync in-cluster resources | Apply/sync success |
| Smoke | Custom scripts / kubectl / health checks | Kiểm tra sau deploy | All critical checks pass |

### 2.2 Chiến lược branch

Branch strategy đề xuất:

- `main` = production-ready hoặc final reviewed branch
- `develop` = integration branch cho team
- `feature/*` = branch cho từng hạng mục

Nguyên tắc merge:

- Mọi thay đổi deployable phải đi qua pull request.
- Merge vào `develop` dùng cho integration và test.
- Merge vào `main` cần review và approval rõ ràng.
- Không apply thay đổi hạ tầng từ branch cá nhân bỏ qua review gate.

### 2.3 Smoke test sau deploy

Smoke test là phần bắt buộc vì Self-Heal Engine không chỉ cần deploy xong, mà còn phải sẵn sàng cho detect/decide/verify flow. Các kiểm tra tối thiểu:

- EKS cluster và 3 namespace `platform`, `tenant-a`, `tenant-b` tồn tại đúng.
- RBAC deny được cross-tenant access ngoài scope.
- Prometheus, Alertmanager và Grafana đã Ready.
- CloudWatch audit log path hoạt động.
- Executor hoặc webhook receiver trả health check thành công.
- Nếu AI endpoint sẵn sàng, đường gọi private endpoint và auth flow phải được verify.

## 3. GitOps

### 3.1 Công cụ và lý do chọn ArgoCD

CDO-02 chọn **ArgoCD** là công cụ GitOps bắt buộc. Lý do:

- Phù hợp với workload Kubernetes-centric.
- Tách rõ boundary: **Terraform** provision AWS base infra; **ArgoCD** sync Kubernetes manifests và Helm releases.
- Có drift detection, rollback theo Git revision và audit trail rõ.
- **Bắt buộc** cho `pattern_type: "deferred"` theo AI contract: khi AI trả deferred action plan, CDO executor tạo Git commit/PR để ArgoCD tự động sync về cluster. CDO không được direct mutate Kubernetes trong path này.

### 3.2 Cài đặt ArgoCD

ArgoCD được cài vào cluster EKS theo quy trình:

```text
Namespace:     argocd
Cài bằng:      Helm chart (argo/argo-cd) hoặc manifest chính thức
Quản lý bởi:   Terraform module argocd/ hoặc bootstrap script
```

Các thành phần chính sau cài đặt:

| Component | Mô tả |
|---|---|
| `argocd-server` | UI + API server, internal-only (không public) |
| `argocd-repo-server` | Render manifest từ Git repo |
| `argocd-application-controller` | Reconcile cluster state so với Git |
| `argocd-dex-server` | SSO (optional trong capstone) |

ArgoCD không expose public endpoint. CDO team truy cập qua `kubectl port-forward` hoặc Internal Load Balancer trong VPC.

### 3.3 AppProject — tenant isolation

CDO-02 dùng **ArgoCD AppProject** để enforce multi-tenant isolation ở tầng GitOps. Mỗi tenant có AppProject riêng:

```yaml
# AppProject tenant-a
apiVersion: argoproj.io/v1alpha1
kind: AppProject
metadata:
  name: tenant-a
  namespace: argocd
spec:
  description: "Self-heal workloads for tenant-a"
  sourceRepos:
    - "https://github.com/<org>/tf3-self-heal-manifests"
  destinations:
    - namespace: tenant-a
      server: https://kubernetes.default.svc
  clusterResourceWhitelist: []       # không cho phép cluster-wide resource
  namespaceResourceWhitelist:
    - group: "apps"
      kind: Deployment
    - group: ""
      kind: ConfigMap
```

Tương tự cho `tenant-b`. AppProject bảo đảm Application của tenant-a không thể sync resource vào namespace `tenant-b` hoặc `platform`.

### 3.4 ArgoCD Application

Mỗi tenant có một ArgoCD Application trỏ vào thư mục manifest tương ứng trong Git:

```yaml
apiVersion: argoproj.io/v1alpha1
kind: Application
metadata:
  name: self-heal-tenant-a
  namespace: argocd
spec:
  project: tenant-a
  source:
    repoURL: https://github.com/<org>/tf3-self-heal-manifests
    targetRevision: main
    path: manifests/tenant-a/
  destination:
    server: https://kubernetes.default.svc
    namespace: tenant-a
  syncPolicy:
    automated:
      prune: false       # không xóa resource tự động
      selfHeal: false    # ← QUAN TRỌNG: tắt cho workload namespaces
    syncOptions:
      - CreateNamespace=false
```

**Tại sao `selfHeal: false` cho workload namespaces (`tenant-a`, `tenant-b`, `platform`)?**

`selfHeal: true` có nghĩa ArgoCD liên tục so sánh cluster ↔ Git, nếu cluster khác Git thì **tự động revert cluster về Git**. Điều này xung đột trực tiếp với urgent path:

```text
CDO urgent path: PATCH_MEMORY_LIMIT → cluster đổi memory limit ngay
ArgoCD selfHeal: phát hiện cluster ≠ Git → revert memory limit về cũ
→ Pod OOM lại → AI detect lại → CDO patch lại → ArgoCD revert lại → vòng lặp vô tận
```

Với `selfHeal: false`:
- ArgoCD vẫn auto-sync khi **Git thay đổi** (CI/CD bình thường, không bị ảnh hưởng)
- ArgoCD **không revert** khi cluster bị CDO urgent path thay đổi
- Sau khi incident resolved, CDO hoặc pipeline commit manifest cập nhật lên Git → ArgoCD sync lần tiếp theo là đúng

Bảng `selfHeal` theo namespace:

| Namespace | `selfHeal` | Lý do |
|---|---|---|
| `tenant-a`, `tenant-b` | `false` | CDO urgent path cần mutate cluster mà không bị revert |
| `platform` | `false` | CDO executor chạy ở đây, cũng chịu urgent action |
| `argocd` | `true` | Infrastructure — chỉ update qua pipeline, không ai sửa tay |
| `self-heal-system` | `true` | AI Engine pod — chỉ update qua deploy pipeline |

`prune: false` đảm bảo ArgoCD không tự xóa resource khi manifest bị remove — cần approval thủ công cho destructive action.

### 3.5 Luồng deferred path chi tiết

Khi AI trả `pattern_type: "deferred"` (ví dụ: `ROTATE_SECRET`, `SCALE_REPLICAS`):

```text
1. CDO Executor nhận action_plan từ /v1/decide
2. Safety gate validate: tenant, namespace, allowed_namespaces, blast-radius, verify_policy
3. Executor tạo Git commit cập nhật manifest trong tf3-self-heal-manifests/manifests/<tenant>/
   Ví dụ: patch replicas trong deployment.yaml hoặc trigger secret rotation config
4. Executor tạo PR (nếu require review) hoặc commit thẳng vào main (nếu auto-approve)
5. ArgoCD phát hiện thay đổi trong ~30-60s (polling interval)
6. ArgoCD sync Application tương ứng vào namespace tenant
7. Executor poll ArgoCD Application status qua ArgoCD API hoặc kubectl
8. Khi sync status = Synced + Health = Healthy → Executor gọi /v1/verify với post_telemetry_window
9. Ghi audit log: deferred_git_commit, argocd_sync_status, verify_result
```

Thời gian tổng thể của deferred path: ~2–5 phút (Git commit + ArgoCD polling + sync + verify).

### 3.5.1 Rollback của deferred path

Deferred path có 3 điểm có thể fail, mỗi điểm có cách rollback riêng:

**Điểm 1 — ArgoCD sync fail (ví dụ: manifest YAML sai, resource conflict)**

```text
Executor phát hiện ArgoCD sync status = SyncFailed hoặc Health = Degraded
→ Executor tạo revert commit: khôi phục manifest về nội dung trước khi patch
→ ArgoCD phát hiện revert commit → sync lại về trạng thái cũ
→ Executor ghi audit: deferred_sync_failed, revert_commit_created
→ Escalate với context bundle (commit hash, ArgoCD error, correlation_id)
```

**Điểm 2 — `/v1/verify` trả regression sau khi ArgoCD sync thành công**

```text
ArgoCD sync thành công, nhưng metrics xấu hơn sau action
→ Executor tạo revert commit: khôi phục manifest về revision trước
→ ArgoCD sync lại về cũ
→ Executor ghi audit: deferred_verify_regression, revert_commit_created
→ Escalate
```

**Điểm 3 — Executor timeout chờ ArgoCD (quá `verify_policy.window_seconds`)**

```text
ArgoCD không sync xong trong thời gian cho phép
→ Executor không gọi /v1/verify
→ Tạo revert commit để đảm bảo cluster về trạng thái safe
→ Ghi audit: deferred_sync_timeout, revert_commit_created
→ Escalate
```

**Cơ chế revert commit:**

```text
Revert commit không phải git revert lệnh — executor đọc nội dung manifest
trước khi patch (lưu trong memory hoặc audit log) và ghi lại file gốc,
sau đó commit lên Git. ArgoCD tự sync về. Không cần git history manipulation.
```

**Bảng tóm tắt:**

| Failure point | Trigger | CDO action | Kubernetes bị ảnh hưởng? |
|---|---|---|---|
| ArgoCD SyncFailed | sync status ≠ Synced trong timeout | Revert commit + escalate | Chưa bị thay đổi (sync chưa xong) |
| verify regression | /v1/verify trả regression=true | Revert commit + escalate | Đã thay đổi → revert về cũ |
| Executor timeout | window_seconds hết mà sync chưa xong | Revert commit + escalate | Tùy trạng thái ArgoCD sync |

> **Lưu ý**: Khác với urgent path (dùng `kubectl rollout undo`), deferred path rollback luôn đi qua Git commit → ArgoCD sync. CDO không bao giờ direct mutate Kubernetes trong deferred path, kể cả khi rollback.

### 3.6 Git repo manifest cho deferred path

CDO-02 dùng repo riêng (hoặc thư mục riêng trong cùng repo) để chứa manifest được quản lý bởi ArgoCD:

```text
tf3-self-heal-manifests/
  manifests/
    tenant-a/
      deployment-api.yaml
      configmap-limits.yaml
    tenant-b/
      deployment-worker.yaml
  argocd/
    appproject-tenant-a.yaml
    appproject-tenant-b.yaml
    application-tenant-a.yaml
    application-tenant-b.yaml
```

CDO executor chỉ được write vào `manifests/<tenant>/` của chính tenant đó. Quyền write vào repo được cấp qua GitHub App token hoặc deploy key, không dùng personal access token tĩnh.

### 3.7 Cấu trúc repo / sync responsibility

| Layer | Tool | Scope |
|---|---|---|
| AWS base infra | Terraform | VPC, EKS, IAM/IRSA (executor + AI Engine), S3, DynamoDB, SQS |
| ArgoCD bootstrap | Terraform Helm release | namespace `argocd`, ArgoCD install |
| Kyverno bootstrap | Terraform Helm release | namespace `kyverno`, Kyverno install |
| AppProject + Application | ArgoCD | Scoped per tenant |
| Namespace + RBAC | ArgoCD (wave 0–1) | `platform`, `tenant-a`, `tenant-b`, `self-heal-system` |
| Observability stack | ArgoCD (wave 2) | Prometheus, Alertmanager, Grafana |
| CDO executor / collector | ArgoCD (wave 3) | namespace `platform` |
| AI Engine deployment | ArgoCD (wave 3) | namespace `self-heal-system` — CDO deploy từ OCI image AI team bàn giao (W12) |
| Sample workloads | ArgoCD (wave 4) | `tenant-a`, `tenant-b` |
| Runtime deferred action | CDO executor → Git commit → ArgoCD | Per-incident manifest patch |

### 3.8 Sync waves

| Wave | Components |
|---|---|
| 0 | Namespace `platform`, `tenant-a`, `tenant-b`, `self-heal-system`; baseline labels/annotations |
| 1 | RBAC, ServiceAccounts, IRSA bindings, configmaps; NetworkPolicy (allow-executor-to-ai) |
| 2 | Observability stack: Prometheus, Alertmanager, Grafana |
| 3 | CDO executor, telemetry collector; AI Engine Deployment + HPA (sau khi AI team bàn giao OCI image) |
| 4 | Tenant sample workloads và test scenarios |

### 3.9 Drift detection

- ArgoCD phát hiện sai khác giữa Git và cluster.
- Drift được review trước khi chấp nhận destructive sync (`prune: false`).
- Thay đổi nhạy cảm như RBAC, namespace, observability routing cần approval thủ công.

## 4. Chiến lược triển khai

### 4.1 Strategy

Trong scope capstone, CDO-02 chọn **rolling update** là deployment strategy chính cho workload trong cluster. Đây là lựa chọn thực tế nhất vì:

- Đơn giản để chứng minh trong sandbox.
- Khớp với EKS/Kubernetes deployment model.
- Giảm rủi ro over-design khi repo chưa có bằng chứng cho traffic split canary.

**Rollout spec (deployment contract-new-4 §2.C):**

```yaml
strategy:
  type: RollingUpdate
  rollingUpdate:
    maxSurge: 25%
    maxUnavailable: 0
```

Áp dụng cho CDO executor, telemetry collector và AI Engine Deployment. `maxUnavailable: 0` đảm bảo không mất capacity khi rolling update.

**Canary deployment** được xem là hướng nâng cấp future-state, có thể áp dụng sau này nếu bổ sung Argo Rollouts hoặc có cơ chế traffic management rõ ràng.

### 4.2 Tiêu chí abort

Một deployment được xem là không an toàn nếu có các dấu hiệu sau:

- Error rate tăng bất thường sau deploy.
- Latency p95/p99 vượt ngưỡng đã đặt cho scenario.
- Pod không Ready trong cửa sổ startup hợp lý.
- Verify step thất bại hoặc phát hiện regression.
- Alert firing mới xuất hiện ngay sau deploy đối với thành phần vừa thay đổi.

**Abort criteria per AI API endpoint (deployment contract-new-4 §6.B):**

| Endpoint | Abort trigger | CDO action |
|---|---|---|
| `/v1/detect` | p99 > 800ms hoặc 5xx > 1% | Trigger rollback, escalate |
| `/v1/decide` | p99 > 3000ms hoặc 5xx > 1% | Trigger rollback, escalate |
| `/v1/verify` | p99 > 1000ms hoặc 5xx > 1% | Trigger rollback, escalate |

Các ngưỡng này áp dụng trong cửa sổ đo 5 phút. Nếu vượt ngưỡng, CDO dừng gọi AI endpoint đó và chuyển sang escalation path.

Với Self-Heal Engine, observability không chỉ là monitoring, mà còn là deployment gate và rollback signal.

### 4.3 Cách rollback

CDO-02 cần tách rõ hai loại rollback:

**Rollback deployment pipeline**

- Kubernetes workload rollback về manifest/Git revision trước.
- Helm release rollback hoặc `kubectl rollout undo` nếu phù hợp.
- ArgoCD có thể sync lại revision an toàn trước đó.

**Rollback self-heal runtime action**

- Tương ứng với local rollback/runbook path của CDO và `verify_policy` AI trả về trong `/v1/decide`.
- Ví dụ: rollout undo sau restart/patch nếu verify fail.
- Nếu rollback không an toàn hoặc không đủ điều kiện, hệ thống phải escalate thay vì thử mutate thêm.

**Rollback infrastructure**

- Terraform không rollback tự động theo kiểu transaction.
- Cách an toàn là review thay đổi, sửa code về trạng thái hợp lệ, plan lại, rồi apply.

Mục tiêu của deployment design là fail-safe: khi không chắc chắn, ưu tiên dừng lại, rollback hoặc escalate thay vì tiếp tục deploy/mutate.

## 5. Tách biệt môi trường

Trong scope hiện tại, CDO-02 chỉ thiết kế và triển khai **1 environment sandbox**.

| Env | Purpose | Expected use |
|---|---|---|
| Sandbox | Dev, demo, scenario simulation, evidencing | Môi trường duy nhất trong capstone hiện tại |

Trong sandbox, separation được thể hiện bằng:

- Namespace `platform` cho executor, collector và thành phần dùng chung
- Namespace `tenant-a` cho workload tenant 1
- Namespace `tenant-b` cho workload tenant 2

Nguyên tắc tách biệt:

- 1 remote state cho sandbox.
- Secrets, RBAC và workload được tách theo namespace.
- Mỗi incident phải map rõ `tenant_id` về namespace tương ứng.
- Không cho phép action cross-tenant trong `tenant-a` và `tenant-b`.

Nếu về sau nhóm mở rộng thêm `staging` hoặc `prod`, cấu trúc `modules/` vẫn có thể tái sử dụng, nhưng bản hiện tại không cần over-design cho những môi trường đó.

## 6. Secrets trong pipeline

Security design của CDO-02 yêu cầu pipeline không được đưa secret vào Git hoặc CI logs. Deployment design đề xuất:

- CI dùng **OIDC + IAM assume-role** để lấy quyền tạm thời.
- Không dùng static AWS access keys trong GitHub Actions.
- Secret runtime được giữ trong AWS Secrets Manager hoặc Kubernetes Secret theo boundary cho phép.
- Pod trên EKS ưu tiên dùng IRSA thay vì inject AWS key.
- Secret scan trên pull request bằng Gitleaks hoặc công cụ tương đương.
- Pipeline phải redact token, auth header, kube token và thông tin nhạy cảm khỏi logs.

Nếu secret bị phát hiện trong PR:

- Block merge.
- Yêu cầu rotate secret nếu đó là secret thật.
- Ghi nhận đây là security incident nhỏ, không xem như warning thông thường.

## 7. Tenant onboarding deployment

CDO-02 không đặt mục tiêu build full self-service tenant provisioning platform trong capstone. Tuy nhiên, deployment design vẫn cần mô tả cách bootstrap tenant để chứng minh multi-tenant isolation.

### 7.1 Scope capstone

Luồng onboarding tenant tối thiểu:

```text
1. Provision namespace tenant mới
2. Tạo Role/RoleBinding theo least privilege
3. Gán labels/annotations tenant_id, environment, service
4. Deploy sample workload cho tenant
5. Chạy smoke test isolation và alert flow
```

### 7.2 Deployment model đề xuất

Trong tài liệu này, CDO-02 chọn hướng:

- **Terraform module** cho baseline provisioning cần có ở tầng infra/platform
- **GitOps manifest sync** cho namespace-scoped resources và sample workloads

Mẫu luồng:

```text
tenant request
-> update environment config / tenant manifest
-> Terraform provision baseline dependencies nếu cần
-> ArgoCD sync namespace resources
-> deploy sample workload
-> smoke test isolation
-> tenant ready
```

Template gốc có gợi ý `Step Function -> Terraform module tenant-provision`. Với CDO-02, hướng đó có thể được xem là **future-state automation**, nhưng không nên khẳng định là design đã chốt nếu team chưa có bằng chứng và chưa cần đến mức độ tự động hóa đó.

Trong bản hiện tại, CDO-02 chỉ cần chứng minh onboarding cho **2 tenant trong Kubernetes**:

- `tenant-a`
- `tenant-b`

## 8. Observability stack

Observability stack phục vụ cả hai mục tiêu:

- Vận hành và debug hệ thống
- Làm bằng chứng cho deployment gate, smoke test, rollback và verify

Bảng stack đề xuất:

| Component | Tool |
|---|---|
| Metrics | Prometheus + kube-state-metrics + node-exporter |
| Alerts | Alertmanager |
| Logs | CloudWatch Logs |
| Dashboards | Grafana |
| Traces | OpenTelemetry -> AWS X-Ray hoặc Jaeger |
| Audit trail | S3 Object Lock + CloudWatch Logs |

Vai trò của stack này trong deployment:

- Sau deploy, dashboard và alerts cho biết workload có ổn định không.
- Audit logs ghi lại ai deploy, deploy gì, rollout kết quả thế nào.
- Trace/log/metric giúp phân biệt lỗi do code, do config, hay do hạ tầng.
- Các metric như latency, error rate, memory pressure được tái sử dụng cho verify step của Self-Heal flow.

CDO-02 ưu tiên hướng quan sát sau:

```text
EKS workloads
-> Prometheus / CloudWatch / OpenTelemetry
-> Alerting + dashboards + audit logs
-> deployment gate / smoke test / verify signal
```

## 8. AI Engine Deployment Spec (CDO-managed, W12)

CDO-02 chịu trách nhiệm deploy AI Engine từ OCI image do AI team bàn giao. Image sẽ có trong W12; CDO chuẩn bị manifest sẵn theo spec trong deployment contract-new-4 để apply ngay khi nhận được image.

### 8.1 Resource spec (deployment contract §2.A)

```yaml
resources:
  requests:
    cpu: "500m"
    memory: "1024Mi"
  limits:
    cpu: "1000m"
    memory: "2048Mi"
```

### 8.2 HPA spec (deployment contract §2.B)

```yaml
minReplicas: 2
maxReplicas: 10
metrics:
  - type: Resource
    resource:
      name: cpu
      target:
        type: Utilization
        averageUtilization: 70
  - type: Resource
    resource:
      name: memory
      target:
        type: Utilization
        averageUtilization: 80
```

### 8.3 IRSA + Secret

- ServiceAccount `ai-engine` trong namespace `self-heal-system` annotated với IAM role ARN do Terraform module `iam/` tạo.
- AI Engine đọc Bedrock credentials từ AWS Secrets Manager path `tf-3/ai-engine/bedrock` qua IRSA.
- IAM role `cdo-ai-engine-irsa-<cluster>` có quyền: Bedrock invoke, S3 audit write, DynamoDB idempotency, SecretsManager GetSecretValue cho path `tf-3/ai-engine/bedrock`.

### 8.4 Probes (deployment contract-new-4 §2.D)

```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3
readinessProbe:
  httpGet:
    path: /ready
    port: 8080
  initialDelaySeconds: 15
  periodSeconds: 10
  failureThreshold: 3
```

### 8.5 Labels và NetworkPolicy

AI Engine pod phải có label `app: ai-engine` — bắt buộc để NetworkPolicy `allow-executor-to-ai` trong namespace `self-heal-system` hoạt động đúng (chỉ cho phép executor pod từ namespace `platform` reach port 8080).

**Egress NetworkPolicy (contract-new-4 §4.C):** AI Engine chỉ được egress HTTPS:443 ra AWS VPC Endpoints. Egress đến K8s API Server bị block.

### 8.6 CDO Controller ServiceAccount — Conflict cần giải quyết

**Contract-new-4 §3.D** yêu cầu CDO controller ServiceAccount tên `tf3-cdo-controller` phải nằm trong namespace `self-heal-system`:

```yaml
serviceAccountName: tf3-cdo-controller
namespace: self-heal-system
```

CDO hiện thiết kế executor trong namespace `platform`. Đây là conflict cần giải quyết trước khi apply manifest W12:

| Option | Impact |
|---|---|
| Di chuyển executor sang `self-heal-system` | IRSA trust policy phải cập nhật; RBAC binding thay đổi namespace; sync wave 3 cần update |
| Push-back với AI team giữ `platform` | Cần agreement bằng văn bản trong contract revision |

CDO phải confirm quyết định này với AI team **trước W12 T1** để không block manifest apply.

## 9. Câu Hỏi Mở

Những điểm dưới đây cần tiếp tục chốt với AI team hoặc trainer trước khi chuyển từ design sang implementation đầy đủ:

- Traces có bắt buộc phải hoạt động đầy đủ trong demo, hay logs + metrics là đủ?
- Tenant onboarding có cần tự động hóa sâu hơn bằng workflow engine, hay Terraform + GitOps là đủ cho scope hiện tại?
- ✅ AI endpoint đã confirmed: `http://ai-engine.self-heal-system.svc.cluster.local:8080/` — CDO deploy từ OCI image AI bàn giao vào namespace `self-heal-system`.

## Tài Liệu Liên Quan

- `01_requirements_analysis.md` - Xác định scope, NFR và assumptions của CDO-02
- `02_infra_design.md` - Kiến trúc tổng thể, component model và workflow
- `03_security_design.md` - IAM, RBAC, secrets, audit và fail-safe controls
- `08_adrs.md` - Các quyết định kiến trúc đã được chấp nhận
