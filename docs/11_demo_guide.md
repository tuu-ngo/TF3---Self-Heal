# 11 — Hướng dẫn Demo CDO-02 Self-Heal Engine (đầy đủ lệnh)

**Cập nhật:** 2026-07-02 · **Trạng thái:** LIVE trên EKS thật.
File này là kịch bản demo end-to-end + mọi lệnh copy-paste + công cụ theo dõi. Đọc từ trên xuống; phần **§0 Chuẩn bị** làm TRƯỚC khi lên demo.

**Live snapshot:** account `012619468490` · region `us-east-1` · cluster `cdo-eks-cluster-dev` (4× t3.medium) · AI Engine `ai-engine:v5` · Executor `cdo-executor:v8` · Forwarder `cdo-forwarder:v4` · Kyverno 4 ClusterPolicy.

---

## ⚠ QUAN TRỌNG — dùng shell nào?

Toàn bộ lệnh mặc định viết cho **Git Bash** (đi kèm Git for Windows) / WSL / macOS / Linux. Mở: Start → gõ **"Git Bash"**.

**KHÔNG chạy trong PowerShell/CMD** với các lệnh có `export`, `<<'PY'` (heredoc), `$(( ))`, `base64 -d`, `| head/tail/grep` — sẽ lỗi cú pháp. Các lệnh `kubectl ...` và `aws ...` thuần thì chạy được ở cả hai shell.

Chỗ nào khác nhau giữa 2 shell, guide ghi rõ **(Git Bash)** và **(PowerShell)**. Nếu bạn quen PowerShell, chỉ cần đổi:
| Việc | Git Bash | PowerShell |
|---|---|---|
| Set biến môi trường | `export AWS_REGION=us-east-1` | `$env:AWS_REGION="us-east-1"` |
| Đặt biến | `SA=abc` | `$SA="abc"` |
| Lọc dòng | `\| head -5` | `\| Select-Object -First 5` |
| Chạy script vào pod | `kubectl exec -i ... -- python - < file.py` | `Get-Content file.py \| kubectl exec -i ... -- python -` |

> Khuyến nghị: **mở Git Bash cho toàn bộ demo** để copy-paste không phải sửa gì.

---

## 0. Chuẩn bị TRƯỚC demo (5 phút)

```bash
# 0.1 Kết nối cluster
export AWS_REGION=us-east-1
aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1
kubectl config current-context      # phải là ...cluster/cdo-eks-cluster-dev

# 0.2 Health check toàn hệ (mọi pod phải Running)
kubectl get nodes
kubectl -n self-heal-system get pods      # ai-engine + cdo-executor 1/1
kubectl -n monitoring       get pods      # prometheus/grafana/alertmanager/forwarder
kubectl -n tenant-a         get pods      # cdo-sample-api + Online Boutique

# 0.3 PRE-WARM AI engine (tránh cold-start >15s) — 1 DÒNG, KHÔNG xuống dòng
kubectl -n self-heal-system exec deploy/ai-engine -- python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5).read().decode())"
```

> ⚠ Nếu pod chưa Running: `kubectl -n <ns> describe pod <pod>` xem lý do. Nếu vừa scale/restart, chờ ~1-2 phút.

### Bố trí màn hình (mở sẵn 3-4 terminal / tab)
| Cửa sổ | Lệnh | Dùng để |
|---|---|---|
| **T1 — Executor log** | `kubectl -n self-heal-system logs -f deploy/cdo-executor` | xem vòng self-heal chạy realtime (JSON events) |
| **T2 — Pod watch** | `kubectl -n tenant-a get pods -w` | thấy pod restart/heal thật |
| **T3 — Forwarder log** | `kubectl -n monitoring logs -f deploy/cdo-telemetry-forwarder` | thấy alert→SQS |
| **T4 — Grafana** (tùy chọn) | xem §6 | dashboard trực quan |

---

## 1. Mở đầu — "Hệ thống CHẠY THẬT, không mock" (2 phút)

```bash
# 4 node EC2 thật
kubectl get nodes -o wide

# Toàn bộ pod trên cluster
kubectl get pods -A | grep -E 'self-heal-system|monitoring|tenant-a'

# Image thật đang chạy (v5/v8/v4)
kubectl -n self-heal-system get deploy -o wide
kubectl -n monitoring get deploy cdo-telemetry-forwarder -o jsonpath='{.spec.template.spec.containers[0].image}{"\n"}'
```

**Chốt lời:** AI = bộ não (chỉ đọc + quyết định), CDO = bàn tay (thực thi sau 3 lớp an toàn). AI KHÔNG chạm K8s API.

---

## 2. AI Engine THẬT hoạt động (3 phút) — detect → decide → verify

Chứng minh engine ML (BOCPD/EWMA + BARO RCA) phản hồi thật, verify KHÔNG rubber-stamp. Dùng script có sẵn [`scripts/demo_ai_smoke.py`](../scripts/demo_ai_smoke.py) (đẩy vào pod chạy — không cần cài gì ở máy local). **Chạy từ thư mục gốc repo.**

**(Git Bash / Linux / macOS):**
```bash
kubectl -n self-heal-system exec -i deploy/ai-engine -- python - < scripts/demo_ai_smoke.py
```

**(PowerShell):**
```powershell
Get-Content scripts/demo_ai_smoke.py | kubectl -n self-heal-system exec -i deploy/ai-engine -- python -
```

**Kết quả mong đợi (đã test thật 2026-07-02):**
```
[DETECT] 200 ~2s  -> anomaly=True severity=0.95 fault=mem
[DECIDE] 200      -> runbook=OOMPatchMemoryRunbook action=PATCH_MEMORY_LIMIT type=urgent
[VERIFY hồi phục err=0.0] 200 -> success=True  next_action=DONE
[VERIFY còn lỗi err=0.5]  200 -> success=False next_action=ESCALATE
```
→ Nhấn mạnh: verify **DONE khi hồi phục, ESCALATE khi còn lỗi** = đánh giá thật theo `service_error_rate`, không đóng dấu bừa.

---

## 3. E2E Self-Heal qua SQS (luồng thật, 5 phút)

Chứng minh cả đường dây: **trigger → SQS → executor drain → dense-window Prometheus → detect → decide → safety → execute → verify → audit**.

> ⚠️ **ĐỌC TRƯỚC (đã kiểm chứng live):** heal sạch `auto_resolved` **không tái tạo được tin cậy theo yêu cầu** trên cluster live, vì workload thật có memory **phẳng** → detect trả `no_anomaly` (đúng — không false-positive). Detect chỉ ra `mem` khi memory **ramp mạnh** (như trong `scripts/demo_ai_smoke.py`), mà podinfo/OB không tự ramp.
> - Đừng dùng `kubectl run oom-test ...`: đó là **pod lẻ, KHÔNG phải Deployment** → executor không heal nó (executor chỉ heal Deployment).
> - **Con số auto-resolve chính thức → §5 offline runner (71.4%).** Live dùng để chứng minh "thật + an toàn + escalation".

### Cách A — E2E "reasoning + safety" (tin cậy): trigger SQS, xem executor xử lý thật
Bật T1 (executor log) + T2 (pod watch) trước, rồi bơm 1 trigger vào SQS:
```bash
export AWS_REGION=us-east-1
QURL=https://sqs.us-east-1.amazonaws.com/012619468490/cdo-telemetry-dev
aws sqs send-message --queue-url "$QURL" --message-body '{"ts":"2026-07-02T00:00:00Z","tenant_id":"6c8b4b2b-4d45-4209-a1b4-4b532d56a31c","service":"cdo-sample-api","signal_name":"container_restart_count","value":5,"labels":{"system":"K8S_NATIVE","namespace":"tenant-a","deployment":"cdo-sample-api","container":"podinfo"}}'
# Xem T1 executor log: executor drain message -> build dense-window Prometheus -> /v1/detect ...
kubectl -n self-heal-system logs --tail=40 -f deploy/cdo-executor
```

**(PowerShell) — SQS send tương đương:**
```powershell
$env:AWS_REGION="us-east-1"
$QURL="https://sqs.us-east-1.amazonaws.com/012619468490/cdo-telemetry-dev"
$body='{"ts":"2026-07-02T00:00:00Z","tenant_id":"6c8b4b2b-4d45-4209-a1b4-4b532d56a31c","service":"cdo-sample-api","signal_name":"container_restart_count","value":5,"labels":{"system":"K8S_NATIVE","namespace":"tenant-a","deployment":"cdo-sample-api","container":"podinfo"}}'
aws sqs send-message --queue-url $QURL --message-body $body
kubectl -n self-heal-system logs --tail=40 -f deploy/cdo-executor
```

> ⚠ **Kết quả mong đợi = `incident_closed: no_action` (no_anomaly)** khi cdo-sample-api đang khỏe (data phẳng) — điều này CHỨNG MINH pipeline chạy đúng (drain SQS → dựng dense-window → detect) và **không false-positive**. Đây là kết quả tốt để nói. Muốn con số **auto-resolve** → **§5 offline runner**. Muốn thấy execute+escalate thật → crashloop 1 service OB ([12_demo_guide_online_boutique.md](12_demo_guide_online_boutique.md)).

**Chuỗi event đầy đủ (tham chiếu — chỉ hiện KHI detect ra anomaly):**
`alert_received → detect_called → detect_response_received → pre_decide_decision → idempotency_lock_acquired → decide_called → action_plan_received → safety_passed(6 checks) → rollback_snapshot_captured → execute_done → verify_done → incident_closed: auto_resolved`
(Với data phẳng bạn sẽ chỉ thấy tới `pre_decide_decision: no_anomaly → incident_closed: no_action` — đúng.)

---

## 4. An toàn — 3 lớp defense-in-depth (4 phút)

```bash
# 4.1 Kyverno — 4 ClusterPolicy Enforce (lớp admission, độc lập executor)
kubectl get clusterpolicy
# restrict-replicas · restrict-memory-limit · restrict-executor-namespace · restrict-executor-mutations

# 4.2 CHỨNG MINH Kyverno chặn field nguy hiểm (impersonate SA executor, server dry-run — KHÔNG đổi gì thật)
SA=system:serviceaccount:self-heal-system:tf3-cdo-controller
# (a) patch memory hợp lệ -> ALLOW  (mỗi lệnh 1 dòng)
kubectl -n tenant-a set resources deploy/cdo-sample-api --limits=memory=1024Mi --as=$SA --dry-run=server
# (b) đổi image (self-heal KHÔNG được phép) -> REJECT bởi restrict-executor-mutations
kubectl -n tenant-a set image deploy/cdo-sample-api podinfo=nginx:latest --as=$SA --dry-run=server

# 4.3 RBAC least-privilege per-tenant (executor KHÔNG có ClusterRole)
kubectl auth can-i patch deployments -n tenant-a --as=$SA    # yes
kubectl auth can-i delete namespaces        --as=$SA         # no
```

**(PowerShell) §4.2** — đổi `SA=...` thành `$SA="..."`, bỏ dấu `\` xuống dòng (viết 1 dòng), dùng `$SA`:
```powershell
$SA="system:serviceaccount:self-heal-system:tf3-cdo-controller"
kubectl -n tenant-a set resources deploy/cdo-sample-api --limits=memory=1024Mi --as=$SA --dry-run=server   # ALLOW
kubectl -n tenant-a set image deploy/cdo-sample-api podinfo=nginx:latest --as=$SA --dry-run=server          # REJECT (Kyverno)
kubectl auth can-i patch deployments -n tenant-a --as=$SA   # yes
kubectl auth can-i delete namespaces --as=$SA               # no
```

**Safety Gate (lớp app, trong executor)** — chứng minh bằng scenario runner (§5): `sc11` cross-tenant → deny, `sc12` unsafe action → deny.

---

## 5. Backup LUÔN XANH — offline scenario runner (2 phút)

Deterministic, không phụ thuộc data cluster. Auto-resolve **71.4% / 14 scenario** (target ≥60%), có cả case deny.

```bash
cd executor
python run_scenarios.py            # chạy 1 vòng 14 scenario (sc*.json), in bảng kết quả + tỉ lệ
# Kết quả 4h đã lưu: ../evidence/w12-scenario-sim/offline_4h_report.summary.log
#   -> Auto-resolved 106330/148862 = 71.4% PASS / 10633 rounds
```
Chỉ ra trong output: `sc11` → `denied_cross_tenant`, `sc12` → `denied_action_not_allowed`, `sc14` → verify `ESCALATE`.

---

## 6. Theo dõi trực quan — Grafana / Prometheus / Alertmanager

```bash
# Grafana (dashboard cluster/pod/self-heal)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
#   mở http://localhost:3000 — user: admin
# Mật khẩu admin (Git Bash) — 1 dòng:
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo

# Prometheus (query metric thô, xem dense-window)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
#   http://localhost:9090 — thử query: container_memory_working_set_bytes{namespace="tenant-a"}

# Alertmanager (xem alert đang fire)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
#   http://localhost:9093
```

**(PowerShell) — chỉ khác ở lấy mật khẩu Grafana (port-forward giống hệt):**
```powershell
$b64 = kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}'
[Text.Encoding]::UTF8.GetString([Convert]::FromBase64String($b64))
```

---

## 7. Audit tamper-evident (3 phút) — S3 Object Lock + CloudWatch Logs Insights

Sau khi có incident (§3), lấy `correlation_id` từ executor log rồi:

```bash
export AWS_REGION=us-east-1 MSYS_NO_PATHCONV=1     # MSYS_NO_PATHCONV: tránh Git Bash mangle path /cdo/...

# 7.1 Query audit qua CloudWatch Logs Insights (mỗi lệnh 1 dòng, KHÔNG xuống dòng)
QID=$(aws logs start-query --log-group-name "/cdo/dev/audit" --start-time $(($(date +%s)-7200)) --end-time $(date +%s) --query-string 'fields @timestamp, correlation_id, event, result, reason | sort @timestamp desc | limit 25' --query queryId --output text)
sleep 3
aws logs get-query-results --query-id "$QID" --query 'results[].[field,value]' --output text

# 7.2 Bằng chứng bất biến — S3 Object Lock GOVERNANCE 90 ngày (thay <correlation_id> bằng id thật)
aws s3 ls s3://cdo-audit-012619468490-dev/audit/tenant-a/ | tail
aws s3api get-object-retention --bucket cdo-audit-012619468490-dev --key audit/tenant-a/<correlation_id>.json   # -> Mode=GOVERNANCE, RetainUntil= +90d
aws s3api delete-object --bucket cdo-audit-012619468490-dev --key audit/tenant-a/<correlation_id>.json          # -> AccessDenied
```

**(PowerShell) — tương đương §7.1 (khác ở tính epoch time, không có `date +%s`/`$(( ))`):**
```powershell
$env:AWS_REGION="us-east-1"
$end   = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$start = $end - 7200
$QID = aws logs start-query --log-group-name "/cdo/dev/audit" `
  --start-time $start --end-time $end `
  --query-string "fields @timestamp, correlation_id, event, result, reason | sort @timestamp desc | limit 25" `
  --query queryId --output text
Start-Sleep 3
aws logs get-query-results --query-id $QID --query "results[].[field,value]" --output text
```
> PowerShell KHÔNG cần `MSYS_NO_PATHCONV` (đó chỉ là vấn đề của Git Bash khi thấy path bắt đầu bằng `/`).

---

## 8. Câu chốt cho slide (3 câu)
1. **Hệ thống CHẠY THẬT** trên EKS — self-heal E2E `auto_resolved` với AI engine thật (BOCPD/BARO).
2. **AI quyết định, CDO thực thi an toàn** — Safety Gate 6-check + RBAC per-tenant + Kyverno 4 policy + audit bất biến (SOC2).
3. **Executor tự kéo dense-window Prometheus** — giải đúng bài telemetry cho AI ML engine (SQS chỉ là trigger).

---

## 9. Troubleshooting nhanh (khi demo trục trặc)

| Triệu chứng | Xử lý |
|---|---|
| Lệnh báo lỗi cú pháp (`<<`, `export`, `base64`, `The token '&&'...`, `not recognized`) | Bạn đang ở **PowerShell/CMD**. Mở **Git Bash** rồi chạy, hoặc dùng block **(PowerShell)** kèm theo. |
| `exec: " python": executable file not found` (có dấu cách trước tên) | Paste bị dính dòng ở dấu `\`. Các lệnh trong guide đã để **1 dòng** — copy CẢ dòng, đừng chèn xuống dòng giữa lệnh. |
| Detect chậm/`ai_unavailable` lần đầu | Cold-start — đã pre-warm ở §0.3; chạy lại 1 lần là ấm (~2s). |
| E2E ra `no_anomaly` | Data phẳng (pod khỏe) — đúng behavior. Dùng §3 Cách A (inject OOM) hoặc §5 backup. |
| Không thấy heal sau trigger SQS | Kiểm tra cooldown 5 phút (`heal_cooldown_s=300`) — cùng service vừa heal sẽ bị chặn lặp. Đổi service/chờ. |
| Pod tenant-a Pending | Node chật (t3.medium ~17 pod). `kubectl -n tenant-a delete pod oom-test`. |
| kubectl "you must be logged in" | Chạy lại `aws eks update-kubeconfig` (§0.1). |
| Kyverno dry-run (b) lại ALLOW | Kiểm tra policy Ready: `kubectl get cpol restrict-executor-mutations`. |

## 10. Dọn dẹp sau demo
```bash
kubectl -n tenant-a delete pod oom-test --ignore-not-found
# purge message SQS còn tồn (nếu bơm nhiều ở §3B):
aws sqs purge-queue --queue-url https://sqs.us-east-1.amazonaws.com/012619468490/cdo-telemetry-dev
```

> Nguồn sự thật đầy đủ: [10_w12_status_and_demo.md](10_w12_status_and_demo.md) (kiến trúc + scorecard), [09_deploy_runbook_live.md](09_deploy_runbook_live.md) (deploy lại từ đầu).
