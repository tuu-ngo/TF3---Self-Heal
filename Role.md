# PHÂN CÔNG VAI TRÒ & TRÁCH NHIỆM — CDO-02

**Dự án:** TF3 Self-Heal Engine — Team CDO-02 (10 người, 3 subteam)
**Angle:** K8s-heavy / Kubernetes Workflow Orchestration
**Kèm theo:** [WORK_RULE.md](WORK_RULE.md) (luật làm việc), `docs/` (design), `executor/` (runtime), `contract - new 4/` (FROZEN).

> `«tên»` = điền tên thành viên. Bạn là **Lead** — ở Subteam A (Core) và review kết quả của cả 3 team.

---

## 1. Nguyên tắc chia việc

Chia theo **critical path của demo**, không chia theo đầu người cho đều:

- **Demo sống hay chết nằm ở Executor** (vòng detect→decide→safety→execute→verify→audit). Hiện **chưa có code chạy thật** (mới có skeleton). → đội mạnh nhất + Lead vào đây.
- **Infra phải có trước** thì Core và QA mới chạy được trên EKS thật. → đội Platform mở đường.
- **Bằng chứng mới ra điểm** (auto-resolve rate ≥60%, ≥10 scenario/4h, zero unsafe, audit query). → đội Telemetry/QA biến code thành evidence.

| Subteam | Tên gọi | Người | Vai trò cốt lõi | Thư mục sở hữu |
|---|---|:---:|---|---|
| **A** | Self-Heal Core (Executor & Safety) ⭐ | 4 | Trái tim runtime: vòng tự chữa lành + safety | `executor/` |
| **B** | Platform & Infrastructure | 3 | AWS base, EKS, GitOps, security baseline | `infra/`, `manifests/` |
| **C** | Telemetry, QA & Evidence | 3 | Telemetry pipeline, test/scenario, evidence, slides | `docs/`, `evidence/`, scripts test |

---

## 2. SUBTEAM A — SELF-HEAL CORE ⭐ (4 người) — *team quan trọng nhất*

**Sứ mệnh:** Biến skeleton `executor/` thành runtime chạy thật, an toàn, audit đầy đủ. Đây là thứ panel chấm trực tiếp.

### A1 — Bạn «tên» — Team Lead + Reviewer toàn repo
- **Sở hữu:** orchestration loop ([executor/main.py](executor/main.py)) + ranh giới tích hợp AI ↔ CDO + quyết định kiến trúc cuối.
- Chốt boundary "AI decide / CDO execute"; giữ 5 invariant an toàn (WORK_RULE §0).
- **Reviewer duy nhất bấm Squash-Merge** cho PR của cả 3 team (WORK_RULE §I cửa 4).
- Resolve conflict liên team, ưu tiên cut-scope khi trễ (hạ deferred/load-test trước).
- Chốt **SA namespace conflict** với AI team trước W12 T1.

### A2 — «tên» — Safety & Decision Gates
- **Sở hữu:** [safety_gate.py](executor/safety_gate.py), [pre_decide_gate.py](executor/pre_decide_gate.py), [idempotency.py](executor/idempotency.py).
- Hoàn thiện 7-condition Pre-Decide Gate + Safety Gate (tenant match, allow-list, blast-radius, routing, verify_policy).
- DynamoDB conditional write lock (chỉ `/v1/decide`), TTL 24h.
- Viết unit test deny (TC-07/08/10/11/blast) — giữ `tests/test_safety_gate.py` xanh.

### A3 — «tên» — K8s Execution Layer ("bàn tay")
- **Sở hữu:** [k8s_client.py](executor/k8s_client.py), [executors/urgent.py](executor/executors/urgent.py), [snapshot.py](executor/snapshot.py).
- Implement thật: `RESTART_DEPLOYMENT`, `PATCH_MEMORY_LIMIT`, `ROLLOUT_UNDO` + **server-side dry-run** (`dry_run="All"`).
- CDO self-capture snapshot trước execute (đọc K8s state).
- Đây là MUST #1 của W12 → TC-01..04 chạy thật trên EKS.

### A4 — «tên» — AI Integration & Audit Trail
- **Sở hữu:** [ai_client.py](executor/ai_client.py), [audit.py](executor/audit.py), [models.py](executor/models.py), [errors.py](executor/errors.py).
- Error/retry policy §4 (400/401/403/409/429/500×2/503), header bắt buộc.
- Audit writer → S3 Object Lock (Governance) theo `correlation_id`, flush mỗi incident.
- Phối A3 deploy **AI Engine image** (wrapper manifest/probe/HPA) khi AI team bàn giao — **không viết nội dung AI engine**.

---

## 3. SUBTEAM B — PLATFORM & INFRASTRUCTURE (3 người)

**Sứ mệnh:** EKS + AWS base + GitOps + security baseline sẵn sàng để Core/QA chạy thật. Mở đường, không block.

### B1 — «tên» — Infra Lead (Network & Compute)
- **Sở hữu:** [infra/modules/vpc](infra/modules/vpc), [eks](infra/modules/eks), [iam](infra/modules/iam), [envs/dev](infra/envs/dev).
- EKS cluster + node group lifecycle (bật lại sau teardown), IRSA executor + AI engine.
- Quản state local (1 người apply, plan-before-apply, commit tfstate — WORK_RULE §IV).
- Đóng public endpoint sau demo, chỉ mở `«IP»/32`.

### B2 — «tên» — Data & Audit Infra + Cost
- **Sở hữu:** [infra/modules/audit](infra/modules/audit) (S3 Object Lock **Governance**, DynamoDB, SQS+DLQ), [observability](infra/modules/observability), `docs/05_cost_analysis.md`.
- Cung cấp bucket/table/queue ARN cho Core (audit, idempotency, telemetry buffer).
- CloudWatch log groups + alarms (executor error, Kyverno deny, DLQ rate). Đo cost thật W12.

### B3 — «tên» — GitOps & Admission Control
- **Sở hữu:** [manifests/argocd](manifests/argocd), [manifests/kyverno](manifests/kyverno), [networkpolicies](manifests/networkpolicies), [namespaces](manifests/namespaces), Helm install ArgoCD + Kyverno.
- Sync waves 0–4, `selfHeal`/`prune` đúng bảng (WORK_RULE §III.3).
- Dựng **deferred path** (Git repo manifest → ArgoCD sync) cho A3 dùng — hoặc báo Lead hạ về designed-only nếu trễ.
- 3 Kyverno policy (replicas ≤10, memory ≤4Gi, namespace allowlist) — test dry-run trước `Enforce`.

---

## 4. SUBTEAM C — TELEMETRY, QA & EVIDENCE (3 người)

**Sứ mệnh:** Biến executor chạy được thành **bằng chứng chấm điểm**. Không có evidence = không có điểm.

### C1 — «tên» — QA Lead (Test & Eval)
- **Sở hữu:** `docs/07_test_eval_report_v1.0_Duc.md`, scenario simulation runner.
- Chạy 21 test case (TC-01..21), ≥10 scenario / ≥4h window → **auto-resolve rate ≥60%**.
- Multi-tenant isolation test (cross-tenant deny = SEV1 gate), security test, load test (k6 — defer được).
- Điền SLO measured, failure analysis (không điền số giả).

### C2 — «tên» — Telemetry Pipeline & Observability
- **Sở hữu:** RE2/RE3 preprocessor, inject scripts (`queue_backlog`, OOM...), SQS forwarder, Grafana/Prometheus dashboard.
- Chuẩn hóa 12 signal theo telemetry contract, scrub PII trước khi gửi AI, gắn tenant_id/correlation_id/ts.
- Cung cấp `telemetry_window` + `post_telemetry_window` cho Core/QA (Offline/Mock Mode).

### C3 — «tên» — Evidence, Docs & Demo
- **Sở hữu:** `docs/` (sync contract-new-4), `docs/08_adrs.md`, `evidence/`, SLIDES, demo video.
- Giữ docs khớp contract khi có thay đổi (header + I/O + SLA + error table trong cùng PR).
- Audit query (Athena/inspect) theo `correlation_id`; gói evidence pack; curveball-responses; individual-pitches.

---

## 5. Ma trận sở hữu thư mục (→ `.github/CODEOWNERS`)

```
/executor/     → Subteam A   (review: A1 Lead)
/infra/        → Subteam B   (review: B1)
/manifests/    → Subteam B   (review: B3)
/docs/         → Subteam C   (review: C3)
/evidence/     → Subteam C
/contract*/    → A1 Lead only (FROZEN — đổi qua RFC)
/WORK_RULE.md, /Role.md → A1 Lead
```
PR luôn cần **≥2 approval (≥1 ngoài subteam)** + **A1 squash-merge**.

---

## 6. Phụ thuộc & handoff (critical path)

```
B1 (EKS + IRSA) ──┬─► A3/A4 chạy executor thật trên cluster
B2 (S3/DDB/SQS) ──┘
B3 (ArgoCD/Kyverno/NetworkPolicy) ──► A (deferred path + 3-lớp safety)
AI team (image) ──► A4 + B3 deploy AI Engine (wave 3)   ← rủi ro #1, theo dõi sát
A (executor chạy) ──► C1 (chạy scenario) ──► C3 (evidence/slides)
C2 (telemetry/inject) ──► A (có data detect/verify) + C1 (chạy test)
```
**Quy tắc:** B không block A — nếu EKS chưa sẵn, A dùng `CDO_K8S_MOCK=true` + `mock_ai_server.py` phát triển song song.

---

## 7. Lịch 5 ngày W12 (29/06 → 02/07, freeze 8h T5)

| Ngày | Subteam A (Core) | Subteam B (Platform) | Subteam C (Telemetry/QA) |
|---|---|---|---|
| **T2 29/06** | A3 implement k8s_client restart+patch; A2 hoàn thiện gate; A1 chốt SA namespace | B1 bật EKS+IRSA; B2 apply audit infra; B3 ArgoCD+Kyverno | C2 preprocessor + inject script; C3 dựng khung evidence |
| **T3 30/06** ⭐ integration | A4 audit→S3 + idempotency thật; chạy TC-01..04 trên EKS thật | B3 deferred path (hoặc báo hạ scope); B1 hỗ trợ debug | C1 bắt đầu chạy scenario; C2 dashboard |
| **T4 01/07** | A xử curveball #3; vá bug; (nếu kịp) deferred TC-05/06 | B đóng gap infra, cost measured | C1 chạy đủ ≥10 scenario/4h; C3 slides draft + audit query |
| **T5 02/07 sáng** | 🛑 8h freeze. A1 review lần cuối, git tag `final` | B verify smoke test, đóng public endpoint | C3 demo video + curveball-responses + individual-pitches |

---

## 8. Vai trò Reviewer của Lead (Bạn — A1)

- **Mọi PR** vào `main` do bạn squash-merge sau khi đủ 2 approval + CI xanh (WORK_RULE §I).
- Ưu tiên review theo critical path: `executor/` > `infra/` (EKS/IRSA/audit) > `manifests/` > scenario/test > docs.
- Quyền cut-scope: khi trễ tiến độ, bạn quyết hạ **deferred path / load test / full traces** về designed-only để bảo vệ lõi demo.
- Gác 5 invariant an toàn + kỷ luật contract FROZEN: chặn PR nào phá boundary "AI decide / CDO execute", direct-mutate ở deferred path, hoặc sửa contract không qua RFC.
- Chuẩn bị Individual Defense: mỗi thành viên phải walk-through được commit của mình (chống free-rider).
