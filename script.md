# Script thuyết trình — TF3 CDO-02 Self-Heal Engine

**Mục đích:** kịch bản trình bày trước mentor (~15–20 phút demo + Q&A). Đọc theo thứ tự; phần **[NÓI]** là lời thuyết trình, **[LÀM]** là thao tác, **[LƯU Ý]** là điều cần nhớ.
**Nguồn lệnh demo:** [docs/11_demo_guide.md](docs/11_demo_guide.md) (cdo-sample-api) · [docs/12_demo_guide_online_boutique.md](docs/12_demo_guide_online_boutique.md) (Online Boutique). Trạng thái: [docs/10_w12_status_and_demo.md](docs/10_w12_status_and_demo.md).

---

## 0. Elevator pitch (30 giây)

> **[NÓI]** "CDO-02 là nền tảng **tự chữa lành Kubernetes**: khi một service trong cluster gặp sự cố, AI engine chẩn đoán và đề xuất hành động, còn CDO executor **thực thi an toàn sau 3 lớp kiểm soát**, verify kết quả và ghi audit bất biến. Điểm khác biệt: hệ **đang chạy thật trên EKS**, self-heal end-to-end với AI thật — không phải mô phỏng."

**Ranh giới cốt lõi (nhắc lại nhiều lần):** **AI = bộ não (chỉ đọc + quyết định). CDO = bàn tay (thực thi sau kiểm soát). AI KHÔNG bao giờ chạm K8s API.**

---

## 1. Bài toán & phạm vi (1 phút)

> **[NÓI]** "Client vận hành 200+ microservice trên EKS. On-call bị 2–4 alert/đêm, 80% là sự cố quen thuộc (OOM, service stuck, queue backlog). Mục tiêu: tự động hoá xử lý các pattern quen thuộc một cách **an toàn, có kiểm toán (SOC2)**, giảm burnout."

**Phạm vi CDO-02:** thu telemetry → gọi AI → **kiểm tra an toàn → execute → verify → rollback/escalate → audit**. AI engine do team AI xây; CDO deploy + runtime-own.

**Hard requirements (8/8 đạt):** ≥3 pattern implement + ≥2 designed · auto-resolve ≥60% · sim ≥4h · zero unsafe · audit bất biến ≥90d · 5 safety sub-checkpoint · multi-tenant + RBAC · escalation có context bundle.

---

## 2. Kiến trúc — closed loop (2 phút)

> **[LÀM]** Mở sơ đồ kiến trúc (docs/02) + chạy `kubectl get nodes` và `kubectl get pods -A` → "chạy thật, 4 node EC2".

```
pod lỗi → Prometheus scrape + Alertmanager → Forwarder (PII-scrub) → SQS (+DLQ)
   → CDO EXECUTOR:
       [0] dựng DENSE-WINDOW từ Prometheus (~241 điểm memory)  ← DATA thật để detect
       [1] /v1/detect (BOCPD/BARO) → [1.5] Pre-Decide Gate → [1.6] Circuit Breaker
       [2] idempotency lock (DynamoDB) → /v1/decide → action_plan
       [3] SAFETY GATE 6-check (độc lập AI)
       [4] snapshot → execute (urgent: K8s API / deferred: GitOps stub)
       [5] /v1/verify (service_error_rate thật) → DONE/RETRY/ROLLBACK/ESCALATE
       [6] audit: S3 Object Lock + CloudWatch Logs
```

> **[LƯU Ý — điểm hay bị hỏi]** **SQS chỉ là "chuông báo" (trigger)**. DATA để AI phân tích là **dense-window** executor **tự kéo từ Prometheus** (`container_memory_working_set_bytes` ~241 điểm). Vì engine ML (BOCPD/EWMA + BARO RCA) cần **chuỗi metric dày**, không phải signal rời. Đây là quyết định kỹ thuật quan trọng nhất của CDO.

---

## 3. Các quyết định thiết kế & TRADE-OFF (4 phút — phần mentor chấm nặng)

| # | Quyết định | VÌ SAO chọn | TRADE-OFF chấp nhận | ADR |
|---|---|---|---|---|
| 1 | **K8s-native orchestration** (không serverless) | Sát bài self-heal K8s, dễ chứng minh RBAC/blast-radius/audit, demo restart/scale thật | Ops phức tạp hơn, cost cao hơn serverless-first | ADR-001 |
| 2 | **AI decide / CDO execute** (tách não–tay) | AI không tự chạm K8s → CDO enforce namespace, blast-radius, rollback, audit trước mọi action | Thêm 1 hop (executor) → latency nhỉnh hơn gọi thẳng | ADR-002 |
| 3 | **Dense-window PULL từ Prometheus** (không dùng signal rời trong SQS) | ML cần chuỗi dày mới detect được; signal rời → luôn `no_anomaly` | Executor query Prometheus mỗi incident (thêm ~vài trăm ms + tải nhẹ) | — |
| 4 | **Deferred path = designed-only stub** (SCALE/ROTATE qua Git→ArgoCD) | Hard-req chỉ cần "≥2 designed"; auto Git-ops trước demo là **rủi ro** | Mất điểm "GitOps thật" so với làm đầy đủ | ADR-008, [w12-scope] |
| 5 | **Audit S3 Object Lock GOVERNANCE 90d** (+ CloudWatch Logs Insights query) | Tamper-evident đủ SOC2, rẻ, đơn giản hơn Glue+Athena/OpenSearch | GOVERNANCE cho admin bypass (production sẽ COMPLIANCE) | ADR-004, ADR-010 |
| 6 | **In-cluster Prometheus** (không Amazon Managed Prometheus) | Tiết kiệm ~$20/10 ngày cho sandbox | Tự vận hành, không HA managed | ADR-005 |
| 7 | **SQS decouple (primary) + watcher poll K8s 30s (fallback)** | Chịu được alert-storm + vẫn hoạt động nếu SQS lỗi (defense-in-depth) | At-least-once → phải có idempotency lock chống double-execute | ADR-006 |
| 8 | **Kyverno** (không OPA/Gatekeeper) | 1 file/policy, viết nhanh, đủ cho value/field-level check | Ít mạnh về logic phức tạp so với Rego | ADR-009 |

> **[NÓI]** "Mỗi quyết định chúng tôi đều ghi ADR với alternatives + lý do. Triết lý: **ưu tiên an toàn và bằng chứng chạy thật hơn là tính năng đẹp trên giấy**."

---

## 4. 3 lớp an toàn — defense-in-depth (2 phút — luận điểm SOC2)

> **[NÓI]** "Zero-unsafe-action **không phụ thuộc đơn lẻ vào code executor** — có 3 lớp độc lập:"

1. **Safety Gate** (app, trong executor): 6 check — pattern_type · verify_policy · action-allowlist · pattern-routing · **tenant-match** · **blast-radius**.
2. **RBAC** least-privilege **per-tenant** (Role riêng từng namespace, KHÔNG ClusterRole).
3. **Kyverno admission** — **4 ClusterPolicy Enforce**: replicas≤10 · mem≤4Gi · namespace-allowlist · **field-level mutation-allowlist** (executor chỉ được sửa replicas+resources; cấm đổi image/privileged/hostPath). Chặn tại API Server, ngoài tầm code.

> **[LÀM]** Chứng minh live (server dry-run, không đổi gì): impersonate SA executor → patch memory **ALLOW**, đổi image **REJECT** bởi Kyverno. + `run_scenarios.py`: sc11 cross-tenant **deny**, sc12 unsafe **deny**.

---

## 5. Demo (5–6 phút) — thứ tự đề xuất

> **[LƯU Ý]** Mở bằng **Git Bash** (không PowerShell). Pre-warm engine trước.

1. **Hệ LIVE** — `kubectl get nodes / pods -A` → "thật, không mock".
2. **AI engine thật** — chạy `scripts/demo_ai_smoke.py` → detect (anomaly 0.95, BARO z-score) → decide (runbook + action) → verify (**DONE khi hồi phục, ESCALATE khi còn lỗi** = không rubber-stamp). *Theo dõi: terminal script + log `ai-engine` lọc `v1`.*
3. **Self-heal E2E an toàn trên Online Boutique** — gây crashloop 1 service OB → hệ **escalate an toàn** (action không hợp workload → không làm hỏng → escalate cho người). *Theo dõi: log `cdo-executor` + `kubectl get pods -w`.*
4. **Auto-resolve sạch** — `run_scenarios.py` → **71.4% / 14 scenario PASS** (deterministic). Đây là con số auto-resolve chính thức.
5. **Audit bất biến** — CloudWatch Logs Insights query theo `correlation_id` + S3 Object Lock (`delete-object` → AccessDenied).

> **[LƯU Ý — điều thật quan trọng phải nói]** Con số **auto-resolve 71.4% lấy từ offline runner** (deterministic). Trên **cluster live**, kết quả **phụ thuộc data thật**: data phẳng → `no_anomaly` (đúng, không false-positive); workload lạ → **escalate an toàn**. Đây là **hành vi đúng**, không phải lỗi.

---

## 6. Kết quả & bằng chứng (1 phút)

- ✅ **LIVE** EKS `cdo-eks-cluster-dev` (K8s 1.30, 4× t3.medium, us-east-1). AI **V5** (BOCPD/BARO) · Executor **v8** (dense-window) · Forwarder **v4** (PII-scrub).
- ✅ **E2E `auto_resolved` proven**: detect → decide → safety 6/6 → RESTART thật → verify DONE.
- ✅ **Auto-resolve 71.4%** (offline: 106330/148862 incidents, 10633 rounds, 4h) — target ≥60%.
- ✅ **Latency**: detect ~2.2s (BARO thật), decide <0.1s.
- ✅ **Cost đo thật** (Cost Explorer 30d): gross **$19.28**, **net ~$0** (AWS credits).
- ✅ **11 ADR**, audit S3 Object Lock 90d + Logs Insights, PII-scrub 7 regex + key-name.

---

## 7. ĐIỂM MẠNH (nêu tự tin)

1. **Bằng chứng chạy thật** — self-heal E2E trên EKS thật với AI thật (nhiều hệ khác dừng ở mock/thiết kế).
2. **An toàn độc lập, đa lớp** — Safety Gate + RBAC + Kyverno 4 policy; zero-unsafe được chứng minh (deny cross-tenant, deny unsafe, Kyverno chặn image).
3. **Giải đúng bài telemetry cho ML** — dense-window Prometheus (không phải signal rời).
4. **Verify không rubber-stamp** — đánh giá `service_error_rate` thật → DONE/ESCALATE theo dữ liệu.
5. **Fail-safe** — action không hợp workload → **escalate an toàn**, không bao giờ làm hỏng service.
6. **Kỷ luật kỹ thuật** — 11 ADR có trade-off, cost đo thật, audit bất biến, CI 4 gate.

---

## 8. ĐIỂM YẾU & cách chúng tôi xử lý (chủ động NÓI TRƯỚC — mentor đánh giá cao sự trung thực)

| Điểm yếu | Ngữ cảnh / vì sao | Đã làm gì / kế hoạch |
|---|---|---|
| **Engine profile hardcode container `podinfo`** → PATCH_MEMORY chỉ heal sạch trên `cdo-sample-api`; workload khác (Online Boutique) → escalate | Profile do team AI tune cho reference workload | **Biến thành điểm mạnh**: workload lạ → escalate an toàn (defense-in-depth). RESTART thì container-agnostic. Production: engine đọc container động từ context |
| **Deferred path (SCALE/ROTATE) mới là stub** | Có chủ đích: auto Git-ops trước demo rủi ro (ADR-008) | Có playbook + diagram + ADR (đủ "designed"); implement ở giai đoạn sau |
| **Add-ons cài ngoài Terraform** (Kyverno policies, ArgoCD, LB controller, app manifests) | Helm cần cluster ACTIVE → tách phase-2 | Đã **tài liệu hoá** boundary + 3 bước reproduce ([04 §1.4]) |
| **Live clean-heal phụ thuộc data** | Data thật phẳng → no_anomaly | Dùng **offline runner deterministic** cho con số auto-resolve; live cho câu chuyện "thật + an toàn" |
| **Audit GOVERNANCE < COMPLIANCE** | Sandbox: rẻ, đơn giản, vẫn tamper-evident 90d | Production nâng COMPLIANCE (đổi 1 tham số) |
| **Sandbox trade-off**: single NAT, local Terraform state, endpoint 0.0.0.0/0 (vẫn IAM+RBAC) | Cost + tốc độ cho capstone | Production: per-AZ NAT, S3 backend, siết CIDR |

---

## 9. Q&A — câu mentor hay hỏi + trả lời ngắn

- **"Auto-resolve 71.4% đo thế nào?"** → Offline runner deterministic, 14 scenario (sc*.json), lặp 4h/10633 rounds; mỗi scenario có expected outcome, so khớp. Live phụ thuộc data nên không lấy làm số chính.
- **"Sao live lại ra escalate/no_anomaly, không phải auto_resolved?"** → Đúng thiết kế: pod khỏe (data phẳng) → no false-positive; workload lạ (container mismatch) → escalate an toàn thay vì làm bừa.
- **"AI có tự chạm K8s không?"** → Không. AI chỉ trả `action_plan`. CDO executor mới execute, sau safety gate (ADR-002).
- **"Chứng minh zero-unsafe?"** → 3 lớp: safety gate 6-check (sc11/sc12 deny), RBAC (can-i delete namespaces = no), Kyverno (đổi image = REJECT). + live tenant-b cross-tenant deny.
- **"Audit có thật bất biến?"** → S3 Object Lock GOVERNANCE 90d; `delete-object` → **AccessDenied**; query qua Logs Insights theo `correlation_id`.
- **"Chi phí vận hành?"** → gross $19.28/30d (Cost Explorer), net ~$0 nhờ credits; forecast production ~$700/tháng/2-tenant.
- **"`terraform apply` dựng lại toàn bộ không?"** → Không đơn thuần: phase-1 (IaC) → phase-2 (Helm) → runbook 09 (app + policies). Đã tài liệu hoá — là lựa chọn scope, không phải thiếu sót.
- **"Vì sao dense-window?"** → Engine BOCPD/BARO cần chuỗi metric dày; gửi signal rời → luôn no_anomaly. Executor tự kéo ~241 điểm từ Prometheus.
- **"Multi-tenant?"** → tenant-a/b, RBAC Role per-namespace (không ClusterRole), cross-tenant mutation bị deny (đã chứng minh live + sc11).
- **"So với nhóm khác thì sao?"** → *(trả lời miệng)* Điểm mạnh nhất của mình là **bằng chứng thực thi** — chấm working-demo thì lợi thế thuộc hệ chạy thật; mình cũng thẳng thắn về các gap và trade-off có chủ đích.

---

## 10. Chốt (30 giây)

> **[NÓI]** "Tóm lại 3 ý: (1) hệ **chạy thật** trên EKS với AI thật, self-heal E2E; (2) **AI quyết định — CDO thực thi an toàn** qua 3 lớp độc lập + audit bất biến; (3) chúng tôi **trung thực về trade-off**: ưu tiên an toàn và bằng chứng hơn tính năng phô trương. Cảm ơn, em sẵn sàng nhận câu hỏi."

---

### Phụ lục — nếu demo trục trặc
- Lệnh lỗi cú pháp → đang ở PowerShell, mở **Git Bash**.
- Detect chậm lần đầu → cold-start, đã pre-warm; chạy lại là ~2s.
- Không có heal live → dùng **offline runner** (luôn xanh) làm backup: `cd executor && python run_scenarios.py`.
- Chi tiết lệnh + theo dõi: [docs/11_demo_guide.md](docs/11_demo_guide.md), [docs/12_demo_guide_online_boutique.md](docs/12_demo_guide_online_boutique.md).
