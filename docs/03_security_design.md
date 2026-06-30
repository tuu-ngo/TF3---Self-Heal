# Security Design - Task Force 3 Self-Heal Engine - CDO-02

**Doc owner:** CDO-02  
**Trạng thái:** Ready for W11 Pack #1 review  
**Cập nhật lần cuối:** 2026-06-26 (sync contract-new-4)  

## 1. Mục Tiêu Bảo Mật

Mục tiêu bảo mật của CDO-02 là cho phép self-heal tự động nhưng không gây unsafe action trên Kubernetes. AI có thể đề xuất action, nhưng mọi thao tác mutate workload phải đi qua CDO safety gate, RBAC, dry-run, rollback/verify và audit.

Security goals chính:

- Zero unsafe action trong sandbox.
- Multi-tenant isolation giữa ít nhất 2 tenants.
- Least privilege cho Kubernetes RBAC và AWS IAM.
- Audit log tamper-evident, retention tối thiểu 90 ngày.
- Không để secret/kubeconfig lộ trong repo, log hoặc container image.
- Ghi đủ evidence để trace một incident theo `correlation_id`.

## 2. Đọc nhanh: security của CDO-02 bảo vệ cái gì?

Self-heal là hệ thống tự động sửa lỗi. Điểm rủi ro là nếu tự động sai, nó có thể làm hỏng workload khác. Vì vậy security design của CDO-02 tập trung vào 4 câu hỏi:

```text
1. Ai được quyền gọi AI?
2. Ai được quyền thao tác Kubernetes?
3. Làm sao chặn action sai tenant/sai namespace?
4. Làm sao chứng minh sau này action nào đã xảy ra?
```

CDO-02 trả lời bằng 4 lớp bảo vệ:

| Lớp bảo vệ | Dùng để làm gì? |
|---|---|
| IAM/Auth | Bảo đảm chỉ service hợp lệ được gọi AI/AWS |
| Kubernetes RBAC | Giới hạn quyền executor trên Kubernetes |
| Safety Gate | Chặn action sai tenant, quá blast-radius hoặc thiếu rollback/verify |
| Audit Log | Ghi lại toàn bộ detect/decide/execute/verify để truy vết |

### 2.1 Ví dụ dễ hiểu

Nếu AI đề xuất:

```text
Restart deployment tenant-b/api-service
```

Nhưng incident thật thuộc:

```text
tenant-a
```

Thì CDO phải:

```text
1. Safety gate phát hiện sai tenant.
2. Không gọi Kubernetes API.
3. Ghi audit: denied_cross_tenant.
4. Escalate nếu cần.
```

Đây là lý do CDO-02 không để AI tự execute trực tiếp.

## 3. Bảo Mật Network

### 3.1 Sơ Đồ Network

```mermaid
graph TB
    subgraph "AWS VPC"
        subgraph "Private Subnets"
            EKS[EKS / Kubernetes Sandbox]
            EXEC[CDO Executor Pod]
            AI[AI Engine Artifact/Service do CDO tự host]
        end

        subgraph "AWS Services"
            CW[CloudWatch Logs]
            S3[S3 Object Lock Audit]
            SM[Secrets Manager]
        end
    end

    EXEC -->|HTTP in-cluster (Local Trust + K8s NetworkPolicy)| AI
    EXEC -->|Kubernetes API| EKS
    EXEC --> CW
    EXEC --> S3
    EXEC --> SM
```

### 3.2 Quy Tắc Network

- AI endpoint là internal endpoint, không public Internet. Transport là HTTP in-cluster (`http://ai-engine.self-heal-system.svc.cluster.local:8080/`); bảo mật bởi K8s NetworkPolicy (Local Trust), không yêu cầu IAM SigV4 signing.
- CDO executor gọi AI qua HTTP in-cluster — K8s NetworkPolicy restrict chỉ pods có label `app=cdo-self-heal-controller` được phép reach port 8080 của AI Engine.
- Kubernetes API access chỉ dành cho executor ServiceAccount/Role phù hợp.
- Audit/log traffic đi tới CloudWatch và S3.
- Ưu tiên VPC endpoints cho S3, CloudWatch, Secrets Manager để giảm public exposure.

**Egress NetworkPolicy (contract-new-4 §4.C):** AI Engine pod và CDO executor chỉ được phép egress HTTPS (port 443) ra ngoài cluster đến AWS VPC Endpoints. Egress đến K8s API Server từ AI Engine bị block — AI Engine không có quyền gọi Kubernetes API.

```yaml
# Egress policy cho AI Engine pod
spec:
  podSelector:
    matchLabels:
      app: ai-engine
  policyTypes:
    - Egress
  egress:
    - ports:
        - port: 443
          protocol: TCP
```

## 4. IAM Và Authentication

IAM/Auth trả lời câu hỏi: service nào được gọi service nào. Theo new contract, AI endpoint dùng **Local Trust + K8s NetworkPolicy** (mTLS tùy chọn) — CDO executor không cần SigV4 để gọi AI. Tenant UUID `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` vẫn gửi qua header `X-Tenant-Id`. IRSA vẫn cần cho CDO executor gọi các AWS services.

| Identity | Used by | Permissions |
|---|---|---|
| CDO executor AWS role | Executor pod/task | Gọi AWS services (S3 audit, DynamoDB, CloudWatch) qua IRSA; gọi AI endpoint qua Local Trust (K8s NetworkPolicy) |
| CDO telemetry preprocessor role | Preprocessor/collector | Đọc telemetry source, scrub PII/secret, validate schema, optionally ghi SQS buffer nếu CDO dùng Offline Simulation Mode |
| AI service role | AI Engine pod/service account trên EKS | Theo IRSA/EKS Pod Identity policy trong contract AI mới nhất |
| Deploy role | Terraform/CI | Tạo VPC/EKS/IAM/S3/observability theo scope |
| Readonly reviewer role | Mentor/trainer review | Read-only logs, audit, infra describe |

Contract AI mới nhất đã chốt rõ: AI only decides, CDO executor executes. AI role không giữ kubeconfig và không có quyền mutate Kubernetes/EKS API; CDO-02 giữ Kubernetes RBAC và audit boundary.

Hosting/security boundary bám theo contract mới:

- AI Engine chạy như pod trong EKS của CDO-02, namespace `self-heal-system`
- AI pod dùng IRSA hoặc EKS Pod Identity để gọi Bedrock, S3, DynamoDB
- Giao tiếp với AI qua service nội bộ cluster, không public Internet
- Network control ưu tiên K8s NetworkPolicy thay vì giả định Internal ALB kiểu cũ

## 5. Kubernetes RBAC

RBAC là lớp giới hạn quyền trong Kubernetes. Mục tiêu là executor chỉ có quyền vừa đủ để làm demo self-heal, không có quyền nguy hiểm như delete namespace hoặc sửa cluster-wide resource.

CDO-02 dùng namespace-based RBAC:

| Namespace | Purpose |
|---|---|
| `platform` | Chạy CDO executor, telemetry collector (thiết kế hiện tại) |
| `tenant-a` | Workload tenant A |
| `tenant-b` | Workload tenant B |
| `argocd` | ArgoCD controller, repo-server, application-controller |
| `self-heal-system` | AI Engine pod (do CDO deploy từ image AI bàn giao) + **CDO controller SA `tf3-cdo-controller` theo contract-new-4 §3.D** |

> **Conflict cần giải quyết W12 (contract-new-4 §3.D):** Deployment contract yêu cầu CDO controller ServiceAccount tên `tf3-cdo-controller` phải nằm trong namespace `self-heal-system`. Thiết kế hiện tại của CDO đặt executor trong namespace `platform`. Trước W12 implementation, CDO phải quyết định: (a) di chuyển executor sang `self-heal-system`, hoặc (b) push-back với AI team để giữ `platform`. Quyết định này ảnh hưởng IRSA trust policy và RBAC binding.

RBAC principles:

- Executor không dùng `cluster-admin`.
- Role theo namespace chỉ cho phép verbs cần thiết.
- Mutating verbs chỉ cấp cho resource cần demo: `deployments`, `pods`, `replicasets` nếu cần.
- Không cấp quyền delete namespace, modify IAM, modify cluster-wide resource.
- Cross-namespace action phải bị deny bởi safety gate và RBAC.

Ví dụ quyền tối thiểu dự kiến cho CDO executor:

```text
get/list/watch: pods, deployments, replicasets, events
patch/update: deployments scale/restart target
create: events hoặc configmap audit marker nếu cần
```

ArgoCD service account cần quyền cluster-level để sync resource vào namespace được chỉ định trong AppProject:

```text
get/list/watch: namespaces, deployments, configmaps, secrets, serviceaccounts, roles, rolebindings
create/patch/update: resources trong namespace tenant-a, tenant-b (scoped bởi AppProject)
KHÔNG cấp: cluster-admin, delete namespace, modify IAM
```

CDO executor cần quyền write vào Git manifest repo qua **GitHub App token** (không dùng personal access token tĩnh) để tạo commit cho deferred path.

## 6. Tenant Isolation

Tenant isolation bảo đảm tenant này không bị action nhầm sang tenant khác. Đây là hard requirement của TF3.

Tenant isolation được enforce ở 4 lớp:

1. **Request layer:** mọi request có `X-Tenant-Id` hoặc `tenant_id`.
2. **Safety layer:** action target namespace phải khớp tenant.
3. **Kubernetes layer:** ServiceAccount/RoleBinding chỉ có quyền trong namespace được phép.
4. **GitOps layer (deferred path):** ArgoCD AppProject scoped per tenant — Application của `tenant-a` chỉ được phép sync vào namespace `tenant-a`; không thể sync sang `tenant-b` hoặc `platform` dù executor tạo commit sai target.

Nếu AI trả action target `tenant-b` cho incident của `tenant-a`, CDO executor phải:

```text
deny action -> không gọi Kubernetes API -> ghi audit denied_cross_tenant -> escalate nếu cần
```

## 7. Secrets Management

Secrets management bảo đảm token, signing key, kube access và AWS credential không bị lộ.

Secrets dự kiến:

| Secret | Storage | Accessed by |
|---|---|---|
| AI endpoint auth | K8s NetworkPolicy (Local Trust) — không cần secret riêng; executor pod label là "credential" | CDO executor |
| **AI Engine Bedrock credentials** | AWS Secrets Manager path: `tf-3/ai-engine/bedrock` (contract-new-2) | AI Engine pod (IRSA) |
| Webhook signing key | AWS Secrets Manager hoặc K8s Secret | Alert ingestor |
| Kube access | Kubernetes ServiceAccount token | CDO executor |
| Audit bucket config | Terraform variables/outputs | Executor/deploy pipeline |
| Idempotency lock table config | Terraform outputs / env var | CDO executor |
| **ArgoCD Git credential** (pull manifest repo) | ArgoCD `repo` Secret trong namespace `argocd` — dùng GitHub App private key hoặc SSH deploy key | ArgoCD repo-server |
| **CDO executor Git credential** (push commit deferred path) | Kubernetes Secret trong namespace `platform` — GitHub App token, mount vào executor pod qua env var | CDO executor (deferred path only) |

**Lưu ý quan trọng về Git credential:**

- ArgoCD cần credential để **pull** manifest repo (đọc manifest để sync vào cluster).
- CDO executor cần credential riêng để **push** commit lên manifest repo (deferred path tạo Git commit).
- Hai credential này **không dùng chung** — least privilege: ArgoCD chỉ cần read, executor chỉ cần write vào `manifests/<tenant>/`.
- Không dùng personal access token tĩnh — dùng GitHub App token (short-lived, scoped per repo).
- GitHub App token phải được rotate định kỳ hoặc tạo on-demand qua GitHub App installation API.

Controls:

- Không commit secret vào Git.
- Không log bearer token, SigV4 headers đầy đủ hoặc kube token.
- Redact PII và credential-like strings trong logs.
- Ưu tiên IRSA thay vì static AWS keys trong pod.
- Idempotency lock dùng DynamoDB conditional write, TTL 24 giờ. 5 phút là quá ngắn — nếu executor restart sau 5 phút, cùng một incident có thể execute lại vì key đã expire. 24 giờ đảm bảo không có duplicate execution trong cùng một ngày vận hành.

## 8. Audit Logging

Audit là phần giúp trainer/client kiểm tra: incident nào xảy ra, AI đã quyết định gì, CDO có execute không, kết quả ra sao. Không có audit thì self-heal rất khó được tin tưởng.

Audit là hard requirement của TF3. CDO-02 thiết kế audit theo `correlation_id` để truy vết toàn bộ incident.

Mỗi incident cần ghi:

```text
alert_received
telemetry_collected
detect_called
detect_response_received
decide_called
action_plan_received
idempotency_lock_acquired / idempotency_duplicate_denied
safety_passed / safety_denied
dry_run_done
execute_done
verify_called
verify_done
rollback_done / escalated
```

Audit record tối thiểu:

| Field | Purpose |
|---|---|
| `timestamp` | Thời điểm event |
| `correlation_id` | Trace toàn incident |
| `tenant_id` | Tenant bị ảnh hưởng |
| `namespace` | Namespace target |
| `action_type` | Action AI đề xuất |
| `decision` | execute/deny/escalate |
| `result` | success/failure/denied |
| `reason` | Lý do safety deny hoặc failure |
| `idempotency_key` | Chống execute trùng action |

CDO-02 dùng **S3 Object Lock Governance Mode**, retention tối thiểu 90 ngày (theo trainer feedback W11). Lưu ý: deployment contract AI quy định Compliance mode — CDO không theo vì Compliance không xóa được kể cả admin; Governance cho phép admin unlock với `s3:BypassGovernanceRetention` khi cần trong sandbox.

## 9. Data Protection

- Logs gửi sang AI phải lọc/mã hóa PII nếu có.
- Telemetry payload chỉ nên chứa fields trong telemetry contract.
- Audit log lưu input/output hash nếu payload lớn hoặc nhạy cảm.
- Encryption at rest dùng S3 SSE-KMS nếu có thể.
- Encryption in transit dùng HTTPS/TLS.

## 10. Failure Và Abuse Cases

Phần này liệt kê các tình huống nguy hiểm và control tương ứng. Mục tiêu chung là fail-safe: khi không chắc thì không execute.

| Case | Control |
|---|---|
| AI trả action ngoài allow-list | Safety gate deny |
| AI trả namespace sai tenant | Safety gate deny + RBAC deny |
| AI timeout/503 | No execute, escalate + audit |
| Idempotency key trùng | Không execute trùng |
| Telemetry message sai schema | Reject message, chuyển DLQ; **alert nếu tỷ lệ malformed > 0.5% trong 5 phút** (telemetry contract-new-2 threshold); không gọi AI |
| Audit write fail | Stop action hoặc mark incident unsafe |
| Executor bị lỗi giữa action | Verify/rollback/escalate theo trạng thái audit |
| Secret bị lộ trong log | Redaction + không log sensitive headers |

## 11. Câu Hỏi Mở

- ~~Confirm tenant UUID chính thức của CDO-02 với AI.~~ **Resolved: `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c`** (confirmed trong deployment contract AI commit 86b32e7).
- ~~SQS ownership~~: **Resolved**: SQS là internal buffer của CDO. AI không pull từ SQS.
- ✅ Confidence threshold: `>= 0.8` → execute; `< 0.8` → escalate + audit (CDO-02 assumption, không có contract constraint cụ thể).
- ~~Confirm `ROTATE_SECRET` policy cho demo~~: **Resolved** — `ROTATE_SECRET` là build thật. Safety gate enforce: signal `secret_expiry_warning` → target `secret_name` phải trong allow-list → `pattern_type: deferred` → GitOps path, không direct mutate.
- Trainer có bắt buộc S3 Object Lock thật cho W11/T6 không, hay W12 mới cần evidence?
- Traces có bắt buộc phải triển khai đầy đủ trong W12 demo không?
- ~~`pattern_type: "deferred"` cần chốt ArgoCD~~: **Resolved** — ArgoCD cài trong cluster namespace `argocd`, AppProject per tenant enforce namespace isolation, executor tạo Git commit → ArgoCD auto-sync → CDO verify. Chi tiết tại `04_deployment_design.md` Section 3.

## Tài Liệu Liên Quan

- `01_requirements_analysis.md`
- `02_infra_design.md`
- `08_adrs.md`
