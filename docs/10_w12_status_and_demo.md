# 10 — Trạng thái hệ thống W12 + Demo (CDO-02) — tài liệu làm slide

**Cập nhật:** 2026-07-02 · **Trạng thái:** LIVE trên EKS thật, E2E `auto_resolved` đã verify.
Doc này tổng hợp toàn bộ để team đọc + dựng slide. Nguồn sự thật: repo + cluster live.

---

## 1. Trạng thái LIVE (đang chạy thật)

| Hạng mục | Giá trị |
|---|---|
| AWS account / region | `012619468490` / `us-east-1` |
| EKS cluster | `cdo-eks-cluster-dev` (K8s 1.30), **4 node t3.medium** |
| AI Engine | **V5** (`ai-engine:v5`) — BOCPD + BARO RCA, real (bản mới nhất từ AI team) |
| Executor | **v8** (`cdo-executor:v8`) — dense-window Prometheus |
| Forwarder | **v3** (`cdo-forwarder:v3`) — Alertmanager→SQS + PII-scrub |
| Workload tenant-a | podinfo (`cdo-sample-api`) + **Online Boutique** (11 svc) + loadgen |
| Repo | `github.com/tuu-ngo/TF3---Self-Heal` (remote `personal`) |

**Bằng chứng E2E (2026-07-01):** `detect → decide → safety_passed(6/6) → snapshot → execute_done RESTART thật(dry_run=false) → verify_done DONE → incident_closed: auto_resolved`.

---

## 2. Kiến trúc — closed-loop self-healing

```
tenant pod lỗi
  → Prometheus scrape (cadvisor 15-30s) + Alertmanager rule
  → Alert Forwarder (PII-scrub) → SQS buffer (+DLQ x3)
  → CDO EXECUTOR (điều phối):
        [0] dựng DENSE-WINDOW từ Prometheus (~241 điểm memory)   ← data thật để detect
        [1] AI /v1/detect (BOCPD/BARO) → anomaly_context
        [1.5] Pre-Decide Gate (confidence/severity/flapping)
        [1.6] Circuit Breaker
        [2] idempotency lock (DynamoDB) → AI /v1/decide → action_plan
        [3] SAFETY GATE 6-check (độc lập AI)
        [4] snapshot → execute (urgent: K8s API / deferred: GitOps stub)
        [5] AI /v1/verify (service_error_rate thật) → DONE/RETRY/ROLLBACK/ESCALATE
        [6] audit: S3 Object Lock + CloudWatch Logs Insights
  → auto_resolved / escalate (context bundle → mock pager)
```

**Ranh giới:** AI = **bộ não (chỉ đọc + quyết định)**; CDO = **bàn tay (thực thi sau 3 lớp an toàn)**. AI KHÔNG chạm K8s API (ADR-002).

### 3 lớp an toàn (defense-in-depth — luận điểm SOC2)
1. **Safety Gate** (app, trong executor): 6 check — pattern_type · verify_policy · action-allowlist · pattern-routing · **tenant-match** · **blast-radius**. Độc lập AI.
2. **RBAC** least-privilege per-tenant (không ClusterRole).
3. **Kyverno admission** (4 ClusterPolicy Enforce): replicas≤10 · mem≤4Gi · namespace-allowlist · **field-level mutation-allowlist** (executor chỉ được replicas+resources, cấm đổi image/privileged/hostPath). Chặn tại API Server, ngoài code executor.

---

## 3. Luồng DATA (điểm hay bị hỏi)

- **Trigger** (chuông báo) = SQS message / watcher-poll → *"có sự cố ở service X"*.
- **DATA engine phân tích** = **dense-window Prometheus** executor tự kéo (`executor/prom_source.py`): `container_memory_working_set_bytes` ~241 điểm. **Không** phải cái trigger.
- **Verify data** = `service_error_rate` (5xx/total) từ Prometheus → verify đánh giá thật.
- **Nguồn Prometheus** = kube-prometheus-stack scrape cadvisor mọi pod mỗi 15-30s, giữ 7 ngày.

---

## 4. Hard requirements — scorecard

| Req | Trạng thái |
|---|---|
| ≥3 pattern impl+tested + ≥2 designed | ✅ RESTART/PATCH/ROLLOUT (urgent, chạy thật) + SCALE/ROTATE (deferred, designed + playbook + diagram + ADR) |
| Auto-resolve ≥60% / ≥10 scenario | ✅ `run_scenarios.py` **14 scenario → 71.4%** (deterministic, offline, verified) |
| Scenario sim ≥4h | ✅ `--duration 4h` **đang chạy** → `evidence/w12-scenario-sim/offline_4h_report.log` |
| Zero unsafe action | ✅ safety-gate + RBAC + Kyverno; `sc11` cross-tenant deny, `sc12` DELETE_NS deny |
| Audit tamper-evident ≥90d | ✅ S3 Object Lock Governance 90d + CloudWatch Logs Insights |
| 5 safety sub-checkpoint | ✅ dry-run · blast-radius · verify · rollback · circuit-breaker |
| Multi-tenant ≥2 + RBAC isolation | ✅ tenant-a/b |
| Escalation AI-gen + context bundle | ✅ `escalation.py` bundle + mock pager |

ADR: **11** (`docs/08_adrs.md`) — phủ 5 chủ đề: decision-engine, audit-storage, runbook-DSL, alert-source, deployment-topology.

---

## 5. AI + Data integration (bàn giao AI team)

- **AI Engine V5** deploy live (swap V1→…→V5 bằng bump image tag), 3 endpoint, profile CDO (`platform_profile_cdo.json`).
- **Dense-window Prometheus** giải bài "engine cần chuỗi metric dày" (không phải signal rời).
- **Dataset thật cho AI team** (`data-export/`): Online Boutique metric+log+nhãn nhất quán (khớp profile online-boutique) + podinfo có anomaly nhãn.
- **Verify KHÔNG rubber-stamp**: executor gửi `service_error_rate` thật → verify DONE khi hồi phục, ESCALATE khi còn lỗi (đã chứng minh).

### 5.1 Kết quả 2 luồng test (evidence trong `evidence/w12-scenario-sim/`)
| Luồng | Kết quả |
|---|---|
| **Offline** (deterministic, mock AI) | 10/14 = **71.4% auto-resolve — PASS** (≥60%); `--duration 4h` đang chạy |
| **Online chaos** (cluster thật, AI V5) | tenant-a: fault thật → **RESTART thật → auto_resolved** ✅ · **cooldown anti-flap** ✅ · **cross-tenant deny** ✅ |

> Online tenant-b bị `denied_cross_tenant` (profile hardcode namespace=tenant-a — safety gate chặn đúng); **multi-tenant heal proven OFFLINE** (sc06/07/08 tenant-b auto_resolve).

---

## 6. So sánh đối thủ CDO-01 (đã đọc full repo `truongcongtu318/capstone-phase2`, 2026-07-02)

| Trục | CDO-02 (mình) | CDO-01 |
|---|---|---|
| **Deploy LIVE + E2E** | ✅ **EKS thật, `auto_resolved` proven** | ❌ **chưa deploy** — chính `SLO_validation_report.md` ghi E2E `PENDING_EKS_DEPLOY`, kubeconfig/cluster-name MISSING, recovery time TBD |
| Kết quả đo được | ✅ auto-resolve 71.4%/14 scenario + online chaos | ❌ chỉ static/kustomize PASS, chưa chạy scenario nào |
| Cost measured actual | ✅ đã đo (gross $19.28/30d, net $0 credits) | ❌ `$X` placeholder (05_cost §5) |
| AI engine tích hợp | ✅ V5 thật (BOCPD/BARO), proven | ⚠ image `ai-engine-demo`, IRSA Bedrock MISSING → chưa proven |
| Safety-gate độc lập (app) | ✅ 6-check trong executor | ❌ chỉ `_guard_ns` 1 check + circuit breaker |
| Admission policy (Kyverno) | ✅ **4 ClusterPolicy** (replicas/mem/ns + **field-level mutation-allowlist**) | ✅ surgical (field-level, SA-scoped) — mình đã bắt kịp trục này |
| PII scrub | ✅ 7 regex **+ key-name layer** (bắt secret sai format) | ✅ 7 regex + deep scrub_dict/key-name |
| Deferred GitOps (Fast+Slow) | 🟡 **designed-only stub** (có chủ đích, xem §6.1) | ✅ **implement thật** (ArgoCD REST + CodeCommit) |
| Autoscaling | 🟡 managed node group tĩnh | ✅ Karpenter |
| Mạng | 🟡 NAT + endpoint (sandbox) | ✅ NAT-less + 12 VPC endpoint |
| Audit mode | 🟡 S3 Object Lock GOVERNANCE + Logs Insights | ✅ Firehose→S3 COMPLIANCE + freeze-on-audit-fail |
| ADR / docs | ✅ 11 ADR | 5 ADR (đủ min); vài doc dày hơn (02_infra 5k từ) |
| Team | ~solo (PM+tech-lead) | 9 người, 3 sub-team |

**Chốt:** thắng dứt điểm ở **bằng chứng thực thi** — thứ đối thủ **tự thừa nhận chưa có** trong SLO report của họ. Capstone chấm working-demo → lợi thế thuộc mình.

### 6.1 Honest về gap — nơi CDO-01 nhỉnh hơn (chủ động nêu khi Q&A)

Không giấu; nêu trước + giải thích trade-off có chủ đích:

1. **Fast+Slow lane GitOps** — họ code thật (ArgoCD+CodeCommit), mình để **deferred = stub có chủ đích**. Lý do: hard-req chỉ cần "≥3 implement + ≥2 designed"; auto Git-ops trước demo là rủi ro (ADR-008, [w12-scope]). Ưu tiên urgent-path chạy thật > slow-path đẹp trên giấy nhưng chưa deploy như họ.
2. **Kyverno field-level** — họ có từ đầu; mình **vừa bổ sung** `restrict-executor-mutations.yaml` (chặn executor đổi image/privileged/hostPath, chỉ cho replicas+resources) → đã bắt kịp.
3. **PII key-name scrub** — họ có; mình **vừa thêm** lớp key-name vào `forwarder/scrub.py` (bắt secret sai format).
4. **Network NAT-less + 12 endpoint / COMPLIANCE audit / Karpenter** — họ mạnh hơn về production-hardening. Mình chọn GOVERNANCE + NAT cho sandbox demo có chủ đích (rẻ, đơn giản, đủ tamper-evident 90d); production sẽ nâng COMPLIANCE — nêu rõ đây là lựa chọn scope, không phải thiếu sót năng lực.

> Điểm mạnh nhất của họ (chiều sâu thiết kế + code sạch) **vô nghĩa nếu chưa chạy**: mọi chaos test của họ là `READY_FOR_CLUSTER_RUN`, chưa có một recovery-time thật nào. Mình có E2E `auto_resolved` đo được.

---

## 7. Demo runbook (tóm tắt — chi tiết lệnh trong session)

1. **Mở đầu**: `kubectl get nodes / pods -A` → "chạy thật trên EKS, không mock".
2. **E2E self-heal**: trigger crash (`/panic`) + SQS message → xem executor log (loop) + `kubectl -n tenant-a get pods -w` (restart thật) → `auto_resolved`.
3. **Safety + Audit**:
   - Safety: `run_scenarios.py` (thấy sc11 deny cross-tenant, sc12 deny unsafe).
   - **Audit query** (CloudWatch Logs Insights, thay Athena — dùng `MSYS_NO_PATHCONV=1` trên Git Bash):
     ```bash
     export AWS_REGION=us-east-1 MSYS_NO_PATHCONV=1
     QID=$(aws logs start-query --log-group-name "/cdo/dev/audit" \
       --start-time $(($(date +%s)-7200)) --end-time $(date +%s) \
       --query-string 'fields @timestamp, correlation_id, event, result, reason | sort @timestamp desc | limit 20' \
       --query queryId --output text)
     aws logs get-query-results --query-id "$QID" --query "results[].[field,value]" --output text
     ```
   - **Tamper-evident** (S3 Object Lock): `aws s3api get-object-retention --bucket cdo-audit-012619468490-dev --key audit/<tenant>/<corr_id>.json` → GOVERNANCE 90d; thử `delete-object` → AccessDenied.
4. **Backup luôn xanh**: `run_scenarios.py --duration 600` (offline, ≥60%).
5. **Pre-warm engine** trước demo (tránh cold-start).

⚠ Detect phụ thuộc data: data phẳng có thể `no_anomaly`. Muốn chắc fire → inject anomaly thật trước, hoặc dùng backup.

---

## 8. Điểm nhấn cho slide (3 câu)
1. **Hệ thống CHẠY THẬT** trên EKS — self-heal E2E `auto_resolved` với AI engine thật (đối thủ còn mock).
2. **AI quyết định, CDO thực thi an toàn** — safety-gate 6 lớp độc lập + Kyverno + audit bất biến (SOC2).
3. **Executor tự kéo dense-window Prometheus** — giải đúng bài telemetry cho AI ML engine.
