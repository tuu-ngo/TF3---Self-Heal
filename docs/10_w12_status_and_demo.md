# 10 — Trạng thái hệ thống W12 + Demo (CDO-02) — tài liệu làm slide

**Cập nhật:** 2026-07-01 · **Trạng thái:** LIVE trên EKS thật, E2E `auto_resolved` đã verify.
Doc này tổng hợp toàn bộ để team đọc + dựng slide. Nguồn sự thật: repo + cluster live.

---

## 1. Trạng thái LIVE (đang chạy thật)

| Hạng mục | Giá trị |
|---|---|
| AWS account / region | `012619468490` / `us-east-1` |
| EKS cluster | `cdo-eks-cluster-dev` (K8s 1.30), **4 node t3.medium** |
| AI Engine | **V4** (`ai-engine:v4`) — BOCPD + BARO RCA, real |
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
3. **Kyverno admission** (3 ClusterPolicy Enforce): replicas≤10 · mem≤4Gi · namespace-allowlist. Chặn tại API Server, ngoài code executor.

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
| Auto-resolve ≥60% / ≥10 scenario | ✅ `run_scenarios.py` 15 scenario, ~76.9% (deterministic, offline) |
| Scenario sim ≥4h | 🟡 có `--duration 4h` (chạy khi cần) |
| Zero unsafe action | ✅ safety-gate + RBAC + Kyverno; `sc11` cross-tenant deny, `sc12` DELETE_NS deny |
| Audit tamper-evident ≥90d | ✅ S3 Object Lock Governance 90d + CloudWatch Logs Insights |
| 5 safety sub-checkpoint | ✅ dry-run · blast-radius · verify · rollback · circuit-breaker |
| Multi-tenant ≥2 + RBAC isolation | ✅ tenant-a/b |
| Escalation AI-gen + context bundle | ✅ `escalation.py` bundle + mock pager |

ADR: **11** (`docs/08_adrs.md`) — phủ 5 chủ đề: decision-engine, audit-storage, runbook-DSL, alert-source, deployment-topology.

---

## 5. AI + Data integration (bàn giao AI team)

- **AI Engine V4** deploy live, 3 endpoint, profile CDO (`platform_profile_cdo.json`).
- **Dense-window Prometheus** giải bài "engine cần chuỗi metric dày" (không phải signal rời).
- **Dataset thật cho AI team** (`data-export/`): Online Boutique metric+log+nhãn nhất quán (khớp profile online-boutique) + podinfo có anomaly nhãn.
- **Verify KHÔNG rubber-stamp**: executor gửi `service_error_rate` thật → verify DONE khi hồi phục, ESCALATE khi còn lỗi (đã chứng minh).

---

## 6. So sánh đối thủ CDO-01

| | CDO-02 (mình) | CDO-01 |
|---|---|---|
| **Deploy** | ✅ **LIVE trên EKS thật, E2E proven** | ⚠ local/mock (LocalStack/Kind), chưa deploy |
| AI engine | ✅ thật (BOCPD/BARO) tích hợp | mock |
| Safety-gate độc lập | ✅ 6 check code-enforce | chủ yếu Kyverno+RBAC |
| ADR/runbook | ✅ 11 ADR + runbook lib | không có |
| Dataset thật | ✅ | chaos framework (chưa chạy) |
| Alert-storm | ✅ SQS decouple(primary)+DLQ | ✅ SQS |
| Deferred GitOps | 🟡 designed-only stub | ✅ implement (Fast+Slow lane) |
| Mạng | NAT + endpoint (sandbox) | NAT-less + 12 VPC endpoint |
| Audit mode | Governance | COMPLIANCE (mạnh hơn) |
| Team | ~solo (PM+tech-lead) | 9 người |

**Chốt:** thắng rõ ở **bằng chứng thực thi (demo chạy thật)**; họ nhỉnh ở **chiều sâu thiết kế trên giấy**. Capstone chấm working-demo → lợi thế thuộc mình.

---

## 7. Demo runbook (tóm tắt — chi tiết lệnh trong session)

1. **Mở đầu**: `kubectl get nodes / pods -A` → "chạy thật trên EKS, không mock".
2. **E2E self-heal**: trigger crash (`/panic`) + SQS message → xem executor log (loop) + `kubectl -n tenant-a get pods -w` (restart thật) → `auto_resolved`.
3. **Safety + Audit**: `run_scenarios.py` (deny cross-tenant) + CloudWatch Logs Insights query `/cdo/dev/audit`.
4. **Backup luôn xanh**: `run_scenarios.py --duration 600` (offline, ≥60%).
5. **Pre-warm engine** trước demo (tránh cold-start).

⚠ Detect phụ thuộc data: data phẳng có thể `no_anomaly`. Muốn chắc fire → inject anomaly thật trước, hoặc dùng backup.

---

## 8. Điểm nhấn cho slide (3 câu)
1. **Hệ thống CHẠY THẬT** trên EKS — self-heal E2E `auto_resolved` với AI engine thật (đối thủ còn mock).
2. **AI quyết định, CDO thực thi an toàn** — safety-gate 6 lớp độc lập + Kyverno + audit bất biến (SOC2).
3. **Executor tự kéo dense-window Prometheus** — giải đúng bài telemetry cho AI ML engine.
