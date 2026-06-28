# CẨM NANG QUY TẮC LÀM VIỆC NHÓM — CDO-02

**Dự án:** Capstone Phase 2 — TF3 Self-Heal Engine — **Team CDO-02**
**Angle:** K8s-heavy / Kubernetes Workflow Orchestration
**Trạng thái:** Luật làm việc của repo. Mọi thành viên tuân thủ để không phá code khi merge, cô lập blast-radius khi deploy, và giữ ranh giới an toàn (zero unsafe action, multi-tenant isolation).

> Tài liệu này bám theo **contract-new-4** (đã FREEZE) và các design doc trong `docs/`. Khi doc và file này mâu thuẫn → ưu tiên contract-new-4, rồi tới design doc, rồi sửa file này cho khớp.
>
> Chỗ có `«...»` là giá trị team phải điền (tên người, ECR URI, repo URL, Slack channel). Đừng để nguyên placeholder khi vận hành.

---

## 0. Hằng số bất biến của CDO-02 (học thuộc)

| Hạng mục | Giá trị | Nguồn |
|---|---|---|
| Tenant ID (CDO-02) | `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` | deployment-contract |
| Tenant namespaces | `tenant-a`, `tenant-b` | 02_infra_design |
| Namespaces hệ thống | `platform`, `self-heal-system`, `argocd`, `kyverno`, `kube-system` | 02/03/04 |
| AI Engine endpoint | `http://ai-engine.self-heal-system.svc.cluster.local:8080/` | deployment-contract §2.C |
| Auth tới AI | **Local Trust + K8s NetworkPolicy** (mTLS optional) — **KHÔNG SigV4** | ai-api §2 |
| Action allow-list | `RESTART_DEPLOYMENT`, `PATCH_MEMORY_LIMIT`, `SCALE_REPLICAS`, `ROLLOUT_UNDO`, `ROTATE_SECRET` | ai-api §3.2 |
| Region | `us-east-1` | client brief |
| AWS account | `938145531618` | evidence W11 |
| Audit storage | S3 Object Lock **GOVERNANCE** 90 ngày (KHÔNG Compliance) | trainer feedback W11 |
| Idempotency lock | DynamoDB conditional write, TTL 24h, **CHỈ cho `/v1/decide`** | contract §4.A |

**5 bất biến an toàn — vi phạm là FAIL capstone:**
1. AI chỉ *decide*, CDO mới *execute*. AI Engine không giữ kubeconfig, không gọi K8s API.
2. `pattern_type: "deferred"` → **CẤM** direct mutate K8s; phải đi Git commit → ArgoCD.
3. Action chỉ chạy sau khi qua Safety Gate. Không chắc chắn → escalate, **không execute**.
4. Cross-tenant target → deny + audit `denied_cross_tenant`. Không bao giờ thao tác nhầm tenant.
5. AI **không** trả `rollback_snapshot` → CDO **tự capture trước execute** (urgent: đọc K8s state; deferred: ghi git SHA).

---

## I. QUY TẮC GIT & PULL REQUEST

### 1. Branching strategy
- **`main`** = Single Source of Truth, luôn deployable. **CẤM** direct push và force push.
- Nhánh làm việc tạo từ `main`, đặt tên theo vùng:

| Prefix | Dùng cho | Ví dụ |
|---|---|---|
| `infra/*` | Terraform trong `infra/` | `infra/eks-nodegroup`, `infra/audit-s3-lock` |
| `executor/*` | Code executor trong `executor/` | `executor/k8s-restart-impl`, `executor/safety-gate-fix` |
| `gitops/*` | Manifests/Helm/ArgoCD/Kyverno trong `manifests/` | `gitops/kyverno-replicas`, `gitops/argocd-appproject` |
| `docs/*` | Tài liệu trong `docs/` | `docs/sync-contract-v4` |
| `fix/*`, `hotfix/*` | Sửa lỗi gấp | `fix/predecide-flapping` |

### 2. Quality Gate — 4 cửa ải bắt buộc trước khi merge

**Cửa 1 — Static analysis & secret scan (CI tự động):**
- Terraform: `terraform fmt -check`, `terraform validate`, scan `tfsec` hoặc `checkov`.
- Python (executor): `ruff check .`, scan secret bằng `gitleaks`.
- K8s YAML: `kube-linter` hoặc `kubeconform`; YAML parse pass.

**Cửa 2 — Unit test & contract verification:**
- Code nghiệp vụ trong `executor/` phải có `pytest` test. Mục tiêu coverage logic safety/gate/loop **≥ 70%**.
- Chạy với mock (mock AI server, `CDO_K8S_MOCK=true`) — không gọi cloud thật trong CI.
- Bắt buộc pass `executor/tests/test_safety_gate.py` (các nhánh deny TC-07/08/10/blast).

**Cửa 3 — Peer review (đánh giá chéo):**
- Tối thiểu **2 approval**, trong đó ≥1 người **ngoài** vùng code của PR.
- CODEOWNERS theo thư mục (xem mục I.3).

**Cửa 4 — Lead approval & Squash merge:**
- Chỉ **Repo Lead «tên»** bấm **Squash and Merge** sau khi cửa 1–3 xanh.
- 1 PR = 1 commit gọn trên `main`, message rõ scope.

### 3. CODEOWNERS (theo thư mục)

```
/infra/        → @«owner-infra»        # Terraform, AWS base
/executor/     → @«owner-executor»     # runtime executor + safety gate
/manifests/    → @«owner-gitops»       # K8s/ArgoCD/Kyverno
/docs/         → @«owner-docs»
/contract*/    → @«repo-lead»          # contract là FROZEN — đổi phải qua RFC (mục VI)
/WORK_RULE.md  → @«repo-lead»
```

> CDO-02 không có nhiều người như mẫu 9-người/3-subteam. Nếu 1 người ôm nhiều vùng, vẫn giữ luật **PR + ≥1 reviewer khác** để tránh single-point lỗi và phục vụ Individual Defense (mỗi người walk-through được commit của mình).

---

## II. CẤU TRÚC REPO (đặt file đúng chỗ)

```
docs/                  # design docs (01..08) — viết WHY, sync contract
infra/
  modules/             # vpc, eks, iam, audit, observability, kyverno, argocd
  envs/dev/            # wiring sandbox (state hiện ở local — xem mục IV)
manifests/             # ArgoCD-managed: namespaces, kyverno, argocd, networkpolicies, workloads
executor/              # CDO Self-Heal Executor (runtime) — xem executor/README.md
evidence/              # bằng chứng runtime W11/W12
contract - new 4/      # contract đã ký (FROZEN) — read-only trừ RFC
WORK_RULE.md           # file này
```

**Luật đặt file:**
- App/runtime code → `executor/`. KHÔNG để code Python lẫn trong `infra/`.
- Manifest K8s do ArgoCD quản → `manifests/`. KHÔNG `kubectl apply` tay manifest đã có trong ArgoCD scope (gây drift).
- AWS base (VPC/EKS/IAM/S3/DDB/SQS) → Terraform `infra/`. KHÔNG tạo các tài nguyên này bằng Console/CLI tay.
- **AI Engine**: image + manifest do **AI team bàn giao**. CDO **không tự viết nội dung AI engine**; chỉ chuẩn bị Deployment/HPA/Probe wrapper theo deployment-contract §2 và deploy khi nhận image (W12).

---

## III. CHIẾN LƯỢC DEPLOY TỪNG PHẦN (INCREMENTAL)

Deploy chia lớp để cô lập blast-radius. **Hai cơ chế:** Terraform (AWS base) chạy theo thứ tự module; ArgoCD (in-cluster) sync theo wave.

### 1. Thứ tự Terraform (AWS base — `infra/envs/dev`)
Áp dụng theo cụm phụ thuộc, không apply nhảy cóc:

```
1) vpc            → mạng nền
2) eks            → cluster + node group   (phụ thuộc vpc)
3) iam            → IRSA executor + AI engine, least-privilege
4) audit          → S3 Object Lock (Governance), DynamoDB idempotency, SQS + DLQ
5) observability  → CloudWatch log groups, alarms
6) kyverno        → Helm release (admission layer 3)
7) argocd         → Helm release (GitOps engine)
```
- Output của module trước (vpc_id, subnet_ids, cluster name, IRSA ARN...) truyền qua biến/`outputs.tf`, **không khai báo lại** tài nguyên đã có ở module khác.

### 2. ArgoCD Sync Waves (in-cluster — `manifests/`)

| Wave | Thành phần |
|---|---|
| 0 | Namespaces `platform`, `tenant-a`, `tenant-b`, `self-heal-system` + labels |
| 1 | RBAC, ServiceAccounts, IRSA binding, NetworkPolicy (`allow-executor-to-ai`) |
| 2 | Observability: Prometheus, Alertmanager, Grafana |
| 3 | CDO executor + telemetry collector; **AI Engine Deployment+HPA (sau khi AI bàn giao image)** |
| 4 | Tenant sample workloads + test scenarios |

### 3. Quy tắc bật/tắt selfHeal (chống vòng lặp revert)

| Namespace | `selfHeal` | `prune` | Lý do |
|---|---|---|---|
| `tenant-a`, `tenant-b`, `platform` | **false** | false | urgent path mutate cluster, KHÔNG để ArgoCD revert lại |
| `argocd`, `self-heal-system` | true | false | infra/AI engine chỉ đổi qua pipeline |

> Đây là điểm dễ sai nhất: bật `selfHeal: true` cho tenant namespace sẽ tạo vòng lặp patch↔revert vô tận với urgent path. Giữ đúng bảng trên.

---

## IV. QUY TẮC DEPLOY & TERRAFORM STATE

**Trạng thái hiện tại: local state (`infra/envs/dev/terraform.tfstate`) — known gap, chấp nhận cho capstone.**

Luật bắt buộc khi còn dùng local state:
- **Chỉ 1 người chạy `terraform apply` tại một thời điểm.** Báo team qua standup/Slack trước khi apply.
- `terraform plan` **bắt buộc** review trước `apply`. Không apply khi plan có thay đổi ngoài dự kiến.
- Commit `terraform.tfstate` sau mỗi apply thành công để team có state mới nhất. **KHÔNG** commit `*.tfstate.backup`.
- KHÔNG commit secret/ARN nhạy cảm vào state public — dùng placeholder cho sensitive output.
- Target W12 (nếu kịp): migrate S3 backend + S3 lockfile. Không block delivery.

Luật deploy chung:
- **Terraform** provision AWS base; **ArgoCD** sync K8s. Không lẫn vai (đừng tạo Deployment app bằng Terraform, đừng tạo S3 bằng kubectl).
- Mọi thay đổi deployable đi qua PR. **Cấm** apply hạ tầng từ branch cá nhân bỏ qua review.
- Smoke test sau deploy: 3 namespace tồn tại, RBAC deny cross-tenant, observability Ready, executor `/health` OK, (nếu có) đường gọi AI endpoint verify được.
- Rollback: workload `kubectl rollout undo` / ArgoCD sync revision cũ; Terraform sửa code → plan → apply (không có auto-rollback transaction).
- **Cost/teardown**: node group có thể scale `0` sau demo. EKS bật public endpoint chỉ giới hạn `«IP»/32`, **đóng lại sau demo**.

---

## V. SECURITY (RANH GIỚI CỨNG)

### 1. Mô hình auth & boundary
- Tới AI endpoint: **Local Trust + K8s NetworkPolicy**. Executor pod phải có label `app=cdo-self-heal-controller` mới reach được port 8080. **Không** ký SigV4 cho AI.
- Tới AWS services (S3/DynamoDB/CloudWatch/Secrets Manager): **IRSA / EKS Pod Identity**. **CẤM** static AWS access key trong pod, code, hay manifest.
- CI dùng **OIDC + assume-role**, không dùng static key trong GitHub Actions.

### 2. RBAC least-privilege (executor)
- Executor ServiceAccount: chỉ `get/list/watch/patch` `deployments`, `pods`, `replicasets`, `pods/log`; `get/create/delete` `secrets` (cho ROTATE_SECRET). Scope theo từng tenant namespace bằng Role/RoleBinding.
- **CẤM**: `cluster-admin`, `delete` deployment/namespace, mọi verb trên `kube-system`, patch `replicas: 0`, tạo/sửa clusterrole(binding).
- SA name `tf3-cdo-controller` ở namespace `self-heal-system` (contract §3.D). Nếu giữ `platform` → phải có **agreement văn bản** với AI team (config `CDO_EXECUTOR_NS`).

### 3. Ba lớp bảo vệ (không bỏ lớp nào)
1. **Safety Gate** (app, `executor/safety_gate.py`): tenant match, allow-list, blast-radius, routing, verify_policy.
2. **K8s RBAC** (verb-level): được làm action gì.
3. **Kyverno** (value-level, Enforce): replicas ≤ 10, memory ≤ 4Gi, namespace allowlist. Test dry-run trước khi set `Enforce`.

### 4. Secrets & PII
- **KHÔNG** commit secret vào Git; **KHÔNG** log bearer token / kube token / SigV4 header đầy đủ.
- Scrub PII/credential/connection-string khỏi `application_log_event` **trước** khi gửi telemetry sang AI (telemetry-contract §2.5.A).
- Git credential deferred path: GitHub App token (short-lived), **không** dùng PAT tĩnh. ArgoCD (read) và executor (write) dùng credential **tách biệt**.
- Nếu lộ secret trong PR: block merge, rotate secret, ghi nhận là security incident nhỏ.

### 5. Image
- Pin image theo tag + commit SHA, không dùng `:latest`. Scan Trivy/Snyk trước khi dùng (0 CRITICAL, HIGH phải có mitigation).
- (Nếu chuyển sang cụm private/NAT-less) mirror image về **ECR private** `«ECR_URI»` rồi mới reference. Hiện CDO-02 dùng public image (vd `podinfo`) — vẫn phải scan trước khi đưa vào demo.

---

## VI. KỶ LUẬT CONTRACT (FROZEN)

- 3 contract trong `contract - new 4/` đã **FREEZE** từ T5 W11. **CẤM** sửa schema/field/error-code/SLA tùy tiện.
- Cần đổi → **RFC**: nêu lý do, họp impact với AI Lead + CDO Leads, breaking change phải lên `/v2` dual-support; non-breaking bump minor sau khi thông báo. Ghi quyết định vào ADR.
- Mỗi lần đổi contract → cập nhật đồng bộ **toàn bộ** docs (header "sync contract-new-X" + bảng I/O + SLA + error table) trong cùng PR. Không để doc lệch contract.
- Deviation đã được duyệt phải ghi rõ: **S3 Governance thay Compliance** (trainer-approved) — sẵn sàng defend trong Q&A.

---

## VII. INVARIANTS NGHIỆP VỤ (executor)

1. **Pre-Decide Gate** (sau `/v1/detect`, trước `/v1/decide`): confidence < 0.5 → discard; 0.5–0.79 + severity cao → escalate; flapping (≥3 lần/10 phút) → escalate; ≥0.8 + severity vừa/cao → proceed. CDO **không** filter theo fault_type.
2. **Idempotency**: lock DynamoDB conditional write **chỉ** quanh `/v1/decide`. Trùng key → `409`, **không** execute lại. `/v1/detect`, `/v1/verify` dùng key cho audit, không lock.
3. **Snapshot trước execute** (CDO tự capture): urgent → đọc K8s state (memory_limit, replica_count, image_tag); deferred → git SHA. Lưu vào audit log.
4. **Dry-run trước execute thật** (urgent): server-side dry-run fail → KHÔNG execute.
5. **next_action**: xử đủ 4 — DONE (close), RETRY (retry), ROLLBACK (dùng snapshot đã capture), ESCALATE (gửi bundle, không execute thêm).
6. **Error policy** (ai-api §4): 400/401/403/409 → không retry; 429 → backoff theo `Retry-After`; 500 → retry tối đa 2 lần (1s, 3s); 503/timeout → escalate, **không execute**.
7. **Audit bất biến**: mỗi incident ghi đủ chuỗi event theo `correlation_id` (xem `executor/audit.py`), flush vào S3 Object Lock. Audit write fail → stop action / mark unsafe.
8. **DLQ**: telemetry bị AI reject (400) → route vào DLQ; alert nếu malformed > 0.5% trong 5 phút.

---

## VIII. PHÂN LẬP MULTI-TENANT

- Mọi request mang `X-Tenant-Id` = `6c8b4b2b-...`; mọi telemetry point có `tenant_id`.
- Action target namespace **phải** khớp tenant của incident và nằm trong `allowed_namespaces`. Lệch → deny `denied_cross_tenant`.
- Isolation 4 lớp: request (header) → safety gate (namespace match) → K8s RBAC (RoleBinding theo ns) → ArgoCD AppProject (deferred path scoped per tenant).
- Bất kỳ cross-tenant mutation nào execute thành công = **SEV1**, cả test suite coi như fail.

---

## IX. QUY TẮC CODE EXECUTOR

- Chạy local trước khi PR: `python tests/test_safety_gate.py` + 1 lượt loop qua `mock_ai_server.py` (xem `executor/README.md`).
- Tách module rõ: thêm action mới → cập nhật `ALLOWED_ACTIONS` + `URGENT/DEFERRED_ACTIONS` trong `config.py` + executor tương ứng + safety check + Kyverno policy nếu là value mới.
- Mọi giá trị config qua env (`config.py`), không hardcode tenant/endpoint/cap trong logic.
- Fail-safe mặc định: nhánh không chắc chắn → escalate + audit, không execute.
- Không gọi cloud thật trong unit test (`CDO_K8S_MOCK=true`, mock AI).

---

## X. DEFINITION OF DONE (DoD)

Một ticket chỉ **Done** khi:
- [ ] `terraform fmt`/`validate` sạch (nếu chạm infra); `ruff` sạch (nếu chạm executor).
- [ ] Không hardcode secret/AWS key; `gitleaks` local sạch.
- [ ] Có unit test pass; logic safety/gate coverage ≥ 70%.
- [ ] Plan/CI xanh trên PR; không lỗi OIDC/IAM/KMS.
- [ ] Doc liên quan đã cập nhật khớp contract-new-4 (nếu chạm interface).
- [ ] Có evidence link khi close ticket (commit SHA / PR URL / screenshot / audit log).
- [ ] ≥2 approval (≥1 ngoài vùng), Lead squash-merge.

---

## XI. ESCALATION & STANDUP

- Standup 14h hằng ngày, log vào `docs/standup_notes.md` (append-only).
- Escalate mentor ngay khi: 2 ngày cùng 1 blocker chưa gỡ; AI–CDO bất đồng cách hiểu contract; build < 50% kỳ vọng giữa tuần.
- Escalation path runtime (executor): AI 503 / circuit-breaker / execute fail → gửi `escalation_bundle` (reason, logs, metrics) lên Slack `«#channel»` / mock pager. Không tự động execute tiếp.
