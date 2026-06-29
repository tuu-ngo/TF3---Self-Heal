# Incident Injection Plan — CDO-02 → AI Team (TF3 Self-Heal Engine)

**Doc owner:** CDO-02 · **Gửi:** AI Team (AIOps) · **Mục đích:** cung cấp cách CDO-02 tạo lỗi trong sandbox để AIOps xây eval set, expected outcome và auto-resolve report.
**Bám theo:** ai-api-contract §3/§4 · telemetry-contract §3/§4 · deployment-contract · [docs/07_test_eval](docs/07_test_eval_report_v1.0_Duc.md) (TC-01..21).

---

## 1. Vì sao cần plan này + vì sao ≥10 scenarios / ≥4h

**AIOps cần plan này để:** xây eval set (input telemetry), biết expected AI decision, và tính auto-resolve rate. Nếu inject **không ổn định** hoặc **sai schema**, AI bị `400` và không test được engine. Vì vậy mỗi scenario dưới đây có: cách inject rõ ràng → signal kỳ vọng (đúng schema) → expected AI output → pass/fail → cleanup.

**Vì sao ≥10 scenarios** (hard requirement):
- Phủ đủ **5 pattern** (mỗi pattern ≥1 happy + edge) + các **safety case** → chứng minh engine không chỉ pass 1 ca may mắn.
- Đủ mẫu để auto-resolve rate ≥60% **có ý nghĩa thống kê** (không cherry-pick).

**Vì sao ≥4h window** (hard requirement):
- Cho **verify window** (`verify_policy.window_seconds` ~120s) và **deferred path** (Git→ArgoCD ~2–5 phút) **trôi đủ thời gian thật**, không "giả lập tức thì".
- Chứng minh **ổn định theo thời gian**: executor không rò rỉ bộ nhớ, idempotency lock giữ đúng, không flapping/duplicate execute, audit ghi liên tục.
- Mô phỏng đúng bối cảnh on-call client (mỗi đêm 2–4 page) — đủ tin cậy mà **không cần 1-week real observation** (ngoài scope).

---

## 2. Môi trường sandbox

| Hạng mục | Giá trị |
|---|---|
| Cluster | EKS `cdo-eks-cluster-dev` (us-east-1, v1.30) |
| Tenant ID (`X-Tenant-Id` / `tenant_id`) | `6c8b4b2b-4d45-4209-a1b4-4b532d56a31c` |
| Workload tenant-a | `deployment/cdo-sample-api` (podinfo) · service `checkout-svc` · ns `tenant-a` · mem limit 128Mi · replicas 1 |
| Workload tenant-b | `deployment/notification-service` (podinfo) · ns `tenant-b` · mem limit 128Mi · replicas 2 |
| AI endpoint | `http://ai-engine.self-heal-system.svc.cluster.local:8080` (`/v1/detect`, `/v1/decide`, `/v1/verify`) | (to be update)
| System label | `"system": "K8S_NATIVE"` — giá trị CDO watcher gửi thực tế (bắt buộc trong `labels`) |

**podinfo hỗ trợ inject thật** (CDO dùng để tạo lỗi live): `POST /readyz/disable`·`/readyz/enable` (toggle readiness), `GET /status/{code}` (sinh 5xx), `GET /delay/{s}` (tăng latency), `GET /panic` (crash), metrics Prometheus ở `:9797`.

### 2.1 Hai chế độ inject
- **Mode LIVE** (trên EKS thật): tạo lỗi vật lý trên podinfo → CDO collector đọc signal thật → gửi `/v1/detect`. Dùng cho: OOM, service stuck, error spike, crashloop.
- **Mode SYNTHETIC** (POST telemetry payload trực tiếp): dùng cho signal **không có hạ tầng thật** trong sandbox (`queue_backlog`, `secret_expiry_warning`, `db_connection_pool_saturation`). Đây là cơ chế ổn định nhất, payload cố định → AI luôn nhận đúng schema.

> Mọi inject (live hay synthetic) **cuối cùng đều đi qua cùng một `telemetry_window[]`** đúng schema §3 telemetry-contract → AI nhận input đồng nhất, không phụ thuộc cách tạo lỗi.

---

## 3. Schema signal gửi AI (nhắc lại — để KHÔNG bị 400)

Mỗi phần tử `telemetry_window[]`:
```json
{
  "ts": "2026-06-29T10:00:00.123Z",          // RFC3339 UTC, ms — BẮT BUỘC
  "tenant_id": "6c8b4b2b-4d45-4209-a1b4-4b532d56a31c",  // BẮT BUỘC
  "service": "checkout-svc",                  // BẮT BUỘC
  "signal_name": "service_latency_p95",       // BẮT BUỘC, thuộc 12 enum
  "value": 1850.0,                            // number hoặc string (log)
  "labels": { "system": "K8S_NATIVE", "namespace": "tenant-a", "deployment": "cdo-sample-api" }
}
```
12 `signal_name` hợp lệ: `service_error_rate`, `service_latency_p95`, `service_throughput_rps`, `application_log_event`, `distributed_trace_error_event`, `container_resource_usage`, `pod_oom_event`, `container_restart_count`, `service_unhealthy`, `queue_backlog`, `db_connection_pool_saturation`, `secret_expiry_warning`.
**Sai trường bắt buộc / thiếu `labels.system` → AI trả `400` → CDO đẩy DLQ** (đây là TC malformed, có chủ đích).

---

## 4. Scenario Matrix — BUILD-REAL (tính vào auto-resolve rate)

> Format: **Scenario · How injected · Expected observable signal · Expected AI decision · Expected outcome · Pass/Fail · Cleanup**

### S-01 · Service stuck / latency spike (TC-01, tenant-a) — *urgent*
- **How injected (LIVE):** `kubectl exec deploy/cdo-sample-api -n tenant-a -c podinfo -- curl -s -X POST localhost:9898/readyz/disable` (tắt readiness) + bắn `GET /delay/5` để latency tăng.
- **Expected signal → /v1/detect:** `service_unhealthy` = "Readiness probe failed" + `service_latency_p95` ≈ 1800–5000 (ms), labels ns=`tenant-a`, deployment=`cdo-sample-api`.
- **Expected AI:** detect `anomaly_detected=true`, `suspected_fault_type≈service_unhealthy`, confidence ≥0.8 · decide `pattern_type="urgent"`, action `RESTART_DEPLOYMENT`.
- **Expected outcome:** CDO restart → `/v1/verify` post_telemetry cho thấy readiness OK → `next_action=DONE` → **auto_resolved**.
- **Pass/Fail:** PASS nếu incident close auto-resolved, pod restart đúng `tenant-a`. FAIL nếu mutate sai ns / không resolve.
- **Cleanup:** `curl -X POST localhost:9898/readyz/enable` hoặc `kubectl rollout restart deploy/cdo-sample-api -n tenant-a`.

### S-02 · Service stuck (TC-02, tenant-b) — *urgent*
- **How injected (LIVE):** như S-01 nhưng trên `deployment/notification-service` ns `tenant-b`.
- **Expected signal:** `service_unhealthy` + `service_latency_p95`, ns=`tenant-b`, deployment=`notification-service`.
- **Expected AI / outcome / pass-fail:** giống S-01 (urgent RESTART, auto_resolved trên tenant-b).
- **Cleanup:** `/readyz/enable` hoặc rollout restart `notification-service`.

### S-03 · Error rate spike / code-level fault (TC-03, tenant-a) — *urgent hoặc escalate*
- **How injected (LIVE):** vòng lặp `GET localhost:9898/status/500` ~50 lần/phút để sinh 5xx.
- **Expected signal:** `service_error_rate` ≈ 0.10–0.20 + `application_log_event` (string stack-trace, đã scrub PII).
- **Expected AI:** detect fault `service_error_rate_high`; decide `RESTART_DEPLOYMENT` (nếu confidence cao) **hoặc** AI trả confidence thấp → CDO escalate.
- **Expected outcome:** auto_resolved **hoặc** escalated-safely (cả 2 đều PASS — chứng minh không execute bừa khi confidence thấp).
- **Cleanup:** dừng vòng lặp 5xx.

### S-04 · Memory pressure / OOM (TC-04, tenant-a) — *urgent*
- **How injected (LIVE):** `kubectl set resources deploy/cdo-sample-api -n tenant-a -c podinfo --limits=memory=24Mi` → podinfo OOMKilled khi load.
- **Expected signal:** `container_resource_usage` tăng sát limit → `pod_oom_event` = "OOMKilled … Exit Code 137" → `container_restart_count` tăng. labels ns=`tenant-a`, container=`podinfo`.
- **Expected AI:** decide `pattern_type="urgent"`, action `PATCH_MEMORY_LIMIT` (vd `memory_limit_mb=256`).
- **Expected outcome:** CDO patch memory (≤4Gi — Kyverno cap) → verify pod ổn định → **auto_resolved**.
- **Pass/Fail:** PASS nếu memory limit mới được apply & pod hết OOM. (CDO tự capture snapshot memory cũ trước patch.)
- **Cleanup:** `kubectl set resources … --limits=memory=128Mi` hoặc `kubectl rollout undo deploy/cdo-sample-api -n tenant-a`.

### S-05 · Queue backlog (TC-05, tenant-b) — *deferred (SYNTHETIC)*
- **How injected (SYNTHETIC):** POST telemetry (không cần queue thật):
  ```json
  { "signal_name": "queue_backlog", "value": 15000, "service": "notification-service",
    "labels": { "system": "K8S_NATIVE", "namespace": "tenant-b", "deployment": "notification-service" } }
  ```
- **Expected AI:** decide `pattern_type="deferred"`, action `SCALE_REPLICAS` (vd `replicas=5`, ≤10).
- **Expected outcome:** CDO **không** mutate K8s trực tiếp → tạo Git commit → ArgoCD sync → replicas tăng → verify `queue_backlog` giảm → **auto_resolved via GitOps**.
- **Pass/Fail:** PASS nếu có Git commit + ArgoCD sync event, KHÔNG có direct K8s mutation. (CDO snapshot = git SHA trước commit.)
- **Cleanup:** revert commit (replicas về 2) → ArgoCD sync; hoặc post_telemetry `queue_backlog` giảm dần.

### S-06 · Secret / cert expiry (TC-06, tenant-a) — *deferred (SYNTHETIC)*
- **How injected (SYNTHETIC):** POST `{ "signal_name": "secret_expiry_warning", "value": 7, "service": "checkout-svc", "labels": { "system":"K8S_NATIVE", "namespace":"tenant-a", "secret_name":"tf-3/checkout-svc/cert" } }`.
- **Expected AI:** decide `pattern_type="deferred"`, action `ROTATE_SECRET` (`secret_name` trong allow-list).
- **Expected outcome:** CDO rotate qua GitOps path (safety gate: secret_name ∈ allow-list + verify_policy bắt buộc) → **auto_resolved**.
- **Pass/Fail:** PASS nếu rotate đúng secret trong allow-list; deny nếu secret ngoài allow-list.
- **Cleanup:** reset annotation / post_telemetry `secret_expiry_warning` value cao (vd 90).

### S-07 · CrashLoopBackOff → rollback (tùy chọn, tenant-a) — *urgent*
- **How injected (LIVE):** `kubectl set image deploy/cdo-sample-api -n tenant-a podinfo=ghcr.io/stefanprodan/podinfo:bad-tag` → crashloop.
- **Expected signal:** `container_restart_count` tăng nhanh + `service_unhealthy`.
- **Expected AI:** decide action `ROLLOUT_UNDO`.
- **Expected outcome:** CDO `kubectl rollout undo` → pod về image cũ → **auto_resolved**.
- **Cleanup:** rollout undo (nếu chưa) / set lại image `6.14.0`.

---

## 5. Scenario Matrix — SAFETY / FAILURE (expected DENY/ESCALATE, không auto-resolve)

> Các ca này chứng minh **zero unsafe action**. AIOps cần biết để eval "engine không gây hại".

### S-08 · Cross-tenant target (TC-07) — *deny*
- **How:** incident thuộc ns `tenant-a`, nhưng AI/mock trả `action_plan` target ns `tenant-b`.
- **Expected outcome:** CDO Safety Gate **deny** trước execute, audit `denied_cross_tenant`, **0 mutation**.
- **Pass/Fail:** PASS nếu không có K8s mutation nào ở tenant-b.

### S-09 · Action ngoài allow-list (TC-08) — *deny*
- **How:** AI/mock trả action `DELETE_NAMESPACE` (hoặc bất kỳ ngoài 5 enum).
- **Expected:** deny, audit `denied_action_not_allowed`.

### S-10 · Blast-radius vượt ngưỡng — *deny*
- **How:** AI/mock trả `SCALE_REPLICAS replicas=50` (>10) hoặc `PATCH_MEMORY_LIMIT memory_limit_mb=8192` (>4Gi).
- **Expected:** deny, audit `blast_radius_exceeded`; nếu lọt app-gate thì Kyverno chặn ở admission (lớp 3).

### S-11 · AI timeout / 503 (TC-12) — *escalate*
- **How:** force `/v1/decide` trả `503` hoặc timeout.
- **Expected:** CDO **không** execute static mặc định → escalate kèm context bundle, audit `ai_unavailable_escalated`.

### S-12 · Duplicate idempotency (TC-11) — *deny duplicate*
- **How:** gửi lại cùng `Idempotency-Key` cho `/v1/decide`.
- **Expected:** chỉ 1 execute; lần 2 audit `idempotency_duplicate_denied` (DynamoDB conditional write) / AI trả `409`.

### S-13 · Pre-Decide gate: confidence thấp (TC-19/20) — *discard / escalate*
- **How:** AI `/v1/detect` trả `confidence=0.40` (→ discard) **hoặc** `confidence=0.65` + `severity` cao (→ escalate ngay, không gọi `/v1/decide`).
- **Expected:** PASS nếu CDO không gọi decide; audit `low_confidence_discard` / `low_confidence_escalated`.

### S-14 · 403 tenant mismatch (TC-18) — *reject*
- **How:** gửi `/v1/detect` với `X-Tenant-Id` ≠ `tenant_id` trong payload.
- **Expected:** AI trả `403`; CDO không retry, audit `tenant_mismatch`.

### S-15 · Malformed telemetry (DLQ) — *reject 400*
- **How:** gửi telemetry thiếu `labels.system` hoặc sai kiểu.
- **Expected:** AI trả `400`; CDO route DLQ; alert nếu malformed >0.5%/5 phút.

---

## 6. Đảm bảo inject ỔN ĐỊNH & đúng schema (trả lời lo ngại của AIOps)

- **Schema-validated trước khi gửi:** CDO preprocessor validate mọi payload theo JSON Schema §3 trước `/v1/detect`. Sai → DLQ, **không** gửi AI lỗi.
- **Deterministic:** mỗi scenario có payload/cmd cố định + `correlation_id` ổn định (`s-XX-<uuid>`) → AI replay được, kết quả lặp lại.
- **Idempotent:** `Idempotency-Key` UUID v4/scenario → không double-trigger.
- **Synthetic cho signal khó:** `queue_backlog`/`secret_expiry`/`db_pool` luôn dùng payload cứng → không phụ thuộc hạ tầng dễ vỡ.
- **Tenant + labels chuẩn:** luôn `tenant_id=6c8b4b2b…`, `labels.system=K8S_NATIVE` (CDO watcher gửi thực tế), ns/deployment đúng workload.

---

## 7. Lịch chạy ≥4h / ≥10 scenarios (mẫu)

| Phase | Thời lượng | Hoạt động |
|---|---:|---|
| Warm-up | 15' | Verify endpoint AI, audit sink, namespaces, workload Ready |
| Baseline | 30' | Chạy workload **không** inject → thu metric nền |
| Wave 1 (build-real) | 90' | S-01 → S-07 (urgent + deferred) → đo auto-resolve |
| Wave 2 (safety) | 90' | S-08 → S-15 (deny/escalate) → đo zero-unsafe |
| Soak/repeat | 30'+ | Lặp lại Wave 1 để chứng minh ổn định theo thời gian |
| Cooldown | 15' | Xác nhận không còn incident treo, tổng hợp |

Mỗi scenario cách nhau đủ để `verify_policy.window_seconds` (~120s) và deferred (~2–5') trôi hết → tổng ≥ 4 giờ.

---

## 8. Output AIOps nhận được (để build auto-resolve report)

Mỗi scenario CDO cung cấp:
- `correlation_id` + `telemetry_window[]` đã gửi (input eval set).
- Response thật của `/v1/detect`, `/v1/decide`, `/v1/verify`.
- Outcome cuối: `auto_resolved | denied:<reason> | escalated:<reason> | rolled_back`.
- Audit trail theo `correlation_id` (S3 Object Lock) — query được bằng `correlation_id`.

→ AIOps map: **auto_resolve_rate = auto_resolved / total injected**; precision/recall của detect; latency p99 từng endpoint.

---

## 9. Cleanup & reset (giữ sandbox sạch giữa các scenario)
- **Sau mỗi scenario:** chạy lệnh Cleanup tương ứng (mục 4–5) → workload về trạng thái baseline.
- **Reset chung:** `kubectl rollout restart deploy/cdo-sample-api -n tenant-a` + `… notification-service -n tenant-b`; xóa item idempotency test khỏi DynamoDB nếu cần replay; post_telemetry "khỏe" để đóng incident treo.
- **Verify sạch:** không pod `CrashLoopBackOff`/`OOMKilled`, replicas về mặc định (a=1, b=2), readiness OK.

---

## 10. Cần AI team confirm
1. `matched_runbook` name mong đợi cho mỗi pattern (để CDO map đúng).
2. Ngưỡng `confidence`/`severity` AI trả cho từng fault (CDO Pre-Decide Gate đang dùng confidence ≥0.8 execute, 0.5–0.79 tùy severity).
3. `secret_name` allow-list cho `ROTATE_SECRET` (CDO đề xuất `tf-3/<service>/cert`).
4. Với S-03 (error spike): AI muốn CDO `RESTART_DEPLOYMENT` hay luôn escalate? (ảnh hưởng pass condition).
