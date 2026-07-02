# 12 — Hướng dẫn Demo Self-Heal trên ONLINE BOUTIQUE (app thật)

**Cập nhật:** 2026-07-02 · Bổ trợ cho [11_demo_guide.md](11_demo_guide.md).
Guide này demo self-heal tác động lên **Online Boutique** (11 microservice thật của Google trong `tenant-a`) thay vì `cdo-sample-api` (podinfo).

> **Shell:** dùng **Git Bash** (Windows) hoặc WSL/macOS/Linux. Nếu PowerShell, xem block `(PowerShell)` hoặc bảng đối chiếu ở [11_demo_guide.md §Shell](11_demo_guide.md).

---

## 0. Điều PHẢI biết trước (đọc kỹ — quyết định demo thành/bại)

Engine V5 dùng **profile CDO** hardcode `container: "podinfo"` khi ra lệnh **PATCH_MEMORY_LIMIT**. Online Boutique có container tên `server` (không phải `podinfo`). Hệ quả **đã kiểm chứng thật**:

| Fault detect ra | Action engine trả | Trên Online Boutique |
|---|---|---|
| `mem` (memory ramp/OOM) | `PATCH_MEMORY_LIMIT` (container=podinfo) | ❌ sai container → **Kyverno #4 chặn** (thêm container lạ) → executor **escalate** (fail-safe, KHÔNG hỏng service) |
| `cpu` / `crash_loop` / `service_stuck` / `latency` / `disk` / `service_unhealthy` | **`RESTART_DEPLOYMENT`** (không cần container) | ✅ **chạy sạch trên mọi service OB** |

**Kết luận cho demo:**
- Muốn thấy **heal sạch `auto_resolved` trên OB** → gây fault kiểu **service-stuck / crashloop** (→ RESTART). Xem §2.
- Nếu gây OOM thật (→ mem → PATCH podinfo) → dùng để demo **defense-in-depth**: Kyverno chặn action sai → escalate. Xem §3.
- Muốn heal PATCH_MEMORY *sạch* thì target `cdo-sample-api` (podinfo) — xem [11_demo_guide.md §3](11_demo_guide.md).

Đây là điểm honest nên chủ động nói trong Q&A: "engine profile hiện tune cho podinfo; trên app khác, RESTART là action an toàn phổ quát, còn PATCH được Kyverno bảo vệ."

---

## 1. Chuẩn bị + màn hình theo dõi

```bash
export AWS_REGION=us-east-1
aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1

# OB đang chạy? (11+ service Running trong tenant-a)
kubectl -n tenant-a get deploy
kubectl -n tenant-a get pods -o wide | grep -vE 'cdo-sample|loadgen'

# Pre-warm engine
kubectl -n self-heal-system exec deploy/ai-engine -- \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5).read().decode())"
```

**Chọn service mục tiêu** (dùng `emailservice` cho ví dụ — không nằm trên đường checkout chính nên gãy tạm cũng ít ảnh hưởng UI):
```bash
export SVC=emailservice        # (PowerShell: $env:SVC="emailservice")
```

### Bố trí 4 cửa sổ theo dõi
| Cửa sổ | Lệnh | Thấy gì |
|---|---|---|
| **T1 — Executor log** | `kubectl -n self-heal-system logs -f deploy/cdo-executor` | vòng self-heal: alert→detect→decide→safety→execute→verify→closed |
| **T2 — Pod watch** | `kubectl -n tenant-a get pods -l app=$SVC -w` | pod OB restart/heal thật (RESTARTS tăng, rồi Running lại) |
| **T3 — Rollout/replicaset** | `kubectl -n tenant-a rollout status deploy/$SVC` | trạng thái deployment sau RESTART |
| **T4 — Grafana** | xem §5 | biểu đồ restart/memory/traffic của OB |

---

## 2. Demo A — Heal SẠCH bằng RESTART (khuyến nghị)

Gây **CrashLoop** trên service OB (không phải OOM) → detect phân loại service-stuck → **RESTART_DEPLOYMENT** → executor restart thật → `auto_resolved`. Rollback snapshot cho phép khôi phục.

### Bước 1 — gây crashloop (ghi đè command để container thoát ngay)
```bash
kubectl -n tenant-a patch deploy $SVC --type=strategic -p \
  '{"spec":{"template":{"spec":{"containers":[{"name":"server","command":["sh","-c","echo boom; exit 1"]}]}}}}'
# Pod sẽ vào CrashLoopBackOff (RESTARTS tăng dần) — xem T2.
```

### Bước 2 — quan sát self-heal tự chạy (T1)
Watcher poll 30s phát hiện `CRASH_LOOP` (sau ≥3 restart) → tự chạy vòng. Trong **T1** tìm chuỗi:
```
[watcher] phát hiện CRASH_LOOP tại tenant-a/emailservice
alert_received → prom_window_built (…points) → detect_called → detect_response_received
→ pre_decide_decision: proceed_to_decide → decide_called
→ action_plan_received: RESTART_DEPLOYMENT → safety_passed (6 checks)
→ rollback_snapshot_captured → execute_done: RESTART_DEPLOYMENT success target=deployment/emailservice
→ verify_done → incident_closed
```

> Nếu detect ra `mem` (PATCH_MEMORY) thay vì RESTART → xem §3 (Kyverno chặn). Đa số crashloop-không-do-memory sẽ ra RESTART.

### Bước 3 — KHÔI PHỤC service (bắt buộc, gỡ command lỗi)
```bash
kubectl -n tenant-a patch deploy $SVC --type=json -p \
  '[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]'
kubectl -n tenant-a rollout status deploy/$SVC     # chờ Running lại
```

> ⚠ RESTART của executor chỉ restart pod — nếu command lỗi vẫn còn thì pod crash lại (executor đã "làm đúng việc", nhưng nguồn lỗi là config). Bước 3 gỡ nguồn lỗi để OB xanh lại. Đây cũng là điểm nói: self-heal xử lý *transient*, không sửa *config sai* (đúng thiết kế → sẽ escalate nếu lặp).

---

## 3. Demo B — Defense-in-depth: OOM → PATCH sai container → Kyverno chặn → escalate

Cho thấy hệ **fail-safe**: khi engine ra action không hợp với OB, Kyverno + safety chặn thay vì làm hỏng service.

### Bước 1 — gây OOM thật (siết memory limit)
```bash
kubectl -n tenant-a set resources deploy/$SVC --limits=memory=12Mi
# server bị OOMKilled → CrashLoopBackOff (OOM). Xem T2: reason OOMKilled.
```

### Bước 2 — quan sát (T1)
```
[watcher] CRASH_LOOP … → detect → suspected_fault_type=mem
→ action_plan_received: PATCH_MEMORY_LIMIT (container=podinfo)
→ safety_passed → execute … → admission webhook "validate.kyverno" DENIED
   (restrict-executor-mutations: executor-no-image-change)  ← Kyverno chặn container lạ
→ escalated: mock_pager   ← fail-safe, service KHÔNG bị thêm container hỏng
```
→ **Chốt:** action sai bị chặn ở API Server, incident escalate cho người — không có "unsafe action" nào lọt.

### Bước 3 — KHÔI PHỤC
```bash
kubectl -n tenant-a set resources deploy/$SVC --limits=memory=128Mi
kubectl -n tenant-a rollout status deploy/$SVC
```

---

## 4. Demo C — Chỉ AI reasoning trên OB (không đụng cluster, an toàn tuyệt đối)

Nếu không muốn gây lỗi thật, chỉ chứng minh engine phân tích đúng service OB:

**(Git Bash):**
```bash
SVC=emailservice kubectl -n self-heal-system exec -i deploy/ai-engine -- python - < scripts/demo_ai_smoke_ob.py
```
**(PowerShell):**
```powershell
Get-Content scripts/demo_ai_smoke_ob.py | kubectl -n self-heal-system exec -i deploy/ai-engine -- python -
```
Kết quả: detect nhận đúng `deployment/emailservice`, severity ~0.95, fault=mem; decide ra action_plan. (Đây là bản OB của [scripts/demo_ai_smoke.py](../scripts/demo_ai_smoke.py).)

---

## 5. Theo dõi trực quan — Grafana + Prometheus cho Online Boutique

```bash
# Grafana
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
#   http://localhost:3000 (user admin) — password:
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo
```
**(PowerShell) password:** `[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String((kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}')))`

```bash
# Prometheus — xem đúng metric của service OB đang demo
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
```
Query hữu ích tại http://localhost:9090 (đổi `emailservice` theo `$SVC`):
| Mục đích | PromQL |
|---|---|
| Số lần restart (thấy crashloop) | `kube_pod_container_status_restarts_total{namespace="tenant-a",pod=~"emailservice.*"}` |
| Memory working set (thấy OOM ramp) | `container_memory_working_set_bytes{namespace="tenant-a",pod=~"emailservice.*"}` |
| Container waiting reason (CrashLoop/OOM) | `kube_pod_container_status_waiting_reason{namespace="tenant-a",pod=~"emailservice.*"}` |
| Pod ready (thấy hồi phục) | `kube_pod_status_ready{namespace="tenant-a",pod=~"emailservice.*"}` |

```bash
# Theo dõi sự kiện K8s realtime của service (OOMKilled / BackOff / Killing)
kubectl -n tenant-a get events --watch --field-selector involvedObject.name=$SVC 2>/dev/null || \
kubectl -n tenant-a get events -w | grep -i "$SVC"
```

### Audit sau demo (lấy correlation_id trong T1 rồi):
```bash
export AWS_REGION=us-east-1 MSYS_NO_PATHCONV=1
QID=$(aws logs start-query --log-group-name "/cdo/dev/audit" \
  --start-time $(($(date +%s)-3600)) --end-time $(date +%s) \
  --query-string 'fields @timestamp, correlation_id, event, result, reason | filter namespace="tenant-a" | sort @timestamp desc | limit 30' \
  --query queryId --output text)
sleep 3
aws logs get-query-results --query-id "$QID" --query 'results[].[field,value]' --output text
```
> (PowerShell: xem [11_demo_guide.md §7](11_demo_guide.md) — dùng `[DateTimeOffset]::UtcNow.ToUnixTimeSeconds()`).

---

## 6. Dọn dẹp sau demo (đưa OB về xanh)
```bash
# gỡ command lỗi nếu còn (Demo A)
kubectl -n tenant-a patch deploy $SVC --type=json -p '[{"op":"remove","path":"/spec/template/spec/containers/0/command"}]' 2>/dev/null
# trả memory limit (Demo B)
kubectl -n tenant-a set resources deploy/$SVC --limits=memory=128Mi 2>/dev/null
kubectl -n tenant-a rollout status deploy/$SVC
kubectl -n tenant-a get pods -l app=$SVC          # phải Running 1/1
```

---

## 7. Troubleshooting
| Triệu chứng | Xử lý |
|---|---|
| Lệnh lỗi cú pháp (`<<`, `export`…) | Đang ở PowerShell → mở **Git Bash** hoặc dùng block `(PowerShell)`. |
| Không thấy self-heal sau khi gây lỗi | Chờ ≥30s (watcher poll) + đủ 3 restart; hoặc service đang cooldown 5 phút (`heal_cooldown_s`). |
| Executor ra `PATCH_MEMORY` rồi Kyverno chặn (mong RESTART) | Đó là case §3 (fault=mem). Muốn RESTART → dùng §2 (crashloop không do memory). |
| OB service không xanh lại | Chạy §6 (gỡ command + trả memory). Nếu vẫn lỗi: `kubectl -n tenant-a rollout undo deploy/$SVC`. |
| Muốn heal PATCH_MEMORY sạch | Target `cdo-sample-api` (podinfo) — [11_demo_guide.md §3](11_demo_guide.md). |

> Backup luôn xanh (offline, không đụng OB): `cd executor && python run_scenarios.py` → 71.4% PASS.
