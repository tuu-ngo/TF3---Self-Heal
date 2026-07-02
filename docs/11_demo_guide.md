# 11 — Hướng dẫn Demo CDO-02 Self-Heal Engine (đầy đủ lệnh)

**Cập nhật:** 2026-07-02 · **Trạng thái:** LIVE trên EKS thật.
File này là kịch bản demo end-to-end + mọi lệnh copy-paste + công cụ theo dõi. Đọc từ trên xuống; phần **§0 Chuẩn bị** làm TRƯỚC khi lên demo.

**Live snapshot:** account `012619468490` · region `us-east-1` · cluster `cdo-eks-cluster-dev` (4× t3.medium) · AI Engine `ai-engine:v5` · Executor `cdo-executor:v8` · Forwarder `cdo-forwarder:v4` · Kyverno 4 ClusterPolicy.

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

# 0.3 PRE-WARM AI engine (tránh cold-start chậm >15s lúc demo) — gọi 1 detect nháp
kubectl -n self-heal-system exec deploy/ai-engine -- \
  python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5).read().decode())"
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

Chứng minh engine ML (BOCPD/EWMA + BARO RCA) phản hồi thật, verify KHÔNG rubber-stamp.

```bash
kubectl -n self-heal-system exec -i deploy/ai-engine -- python - <<'PY'
import urllib.request, json, uuid, datetime, time
BASE="http://127.0.0.1:8080"; TENANT=str(uuid.uuid4())
def post(path, payload):
    idem=str(uuid.uuid4()); corr=str(uuid.uuid4())
    payload=dict(payload, idempotency_key=idem, correlation_id=corr, dry_run_mode=True)
    hdr={"Content-Type":"application/json","X-Tenant-Id":TENANT,"Idempotency-Key":idem,
         "X-Dry-Run-Mode":"true","X-Correlation-Id":corr}
    req=urllib.request.Request(BASE+path, data=json.dumps(payload).encode(), headers=hdr)
    t0=time.time(); r=urllib.request.urlopen(req,timeout=60)
    return r.status, json.loads(r.read()), round(time.time()-t0,2)
now=datetime.datetime.now(datetime.timezone.utc)
# dense-window 180 điểm: baseline 200MB -> ramp 950MB (memory leak/OOM)
pts=[{"ts":(now-datetime.timedelta(seconds=(180-i)*15)).isoformat().replace("+00:00","Z"),
      "tenant_id":TENANT,"service":"cdo-sample-api","signal_name":"container_resource_usage",
      "value":(200e6+(i%5)*3e6 if i<120 else 200e6+(i-120)*12e6),
      "labels":{"system":"K8S_NATIVE","namespace":"tenant-a","deployment":"cdo-sample-api","container":"podinfo"}}
     for i in range(180)]
st,b,dt=post("/v1/detect",{"telemetry_window":pts})
print(f"[DETECT] {st} {dt}s -> anomaly={b.get('anomaly_detected')} severity={b.get('severity')} fault={b.get('anomaly_context',{}).get('suspected_fault_type')}")
st2,b2,_=post("/v1/decide",{"anomaly_context":b["anomaly_context"]})
print(f"[DECIDE] {st2} -> runbook={b2.get('matched_runbook')} action={b2['action_plan'][0]['action']} type={b2.get('pattern_type')}")
def win(err):
    return [{"ts":now.isoformat().replace('+00:00','Z'),"tenant_id":TENANT,"service":"cdo-sample-api",
             "signal_name":"service_error_rate","value":err,
             "labels":{"system":"K8S_NATIVE","namespace":"tenant-a","deployment":"cdo-sample-api"}} for _ in range(60)]
act={"action":"PATCH_MEMORY_LIMIT","target":"deployment/cdo-sample-api","status":"COMPLETED","execution_time_seconds":5}
for name,err in [("hồi phục err=0.0",0.0),("còn lỗi err=0.5",0.5)]:
    stv,bv,_=post("/v1/verify",{"action_executed":act,"post_telemetry_window":win(err)})
    print(f"[VERIFY {name}] {stv} -> success={bv.get('success')} next_action={bv.get('next_action')}")
PY
```

**Kết quả mong đợi:**
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

### Cách A — Inject lỗi THẬT rồi để hệ tự heal (ấn tượng nhất)
```bash
# Bật T1 (executor log) + T2 (pod watch) trước.
# Tạo OOM thật trên tenant-a để Prometheus ghi nhận anomaly:
kubectl run oom-test -n tenant-a --image=polinux/stress --restart=Never -- \
  --vm 1 --vm-bytes 250M --vm-hang 0

# Alertmanager fire PodOOMKilled -> forwarder -> SQS -> executor tự xử.
# Xem T1: alert_received -> detect_called -> ... -> execute_done -> verify_done -> incident_closed
# Dọn sau demo:
kubectl -n tenant-a delete pod oom-test --ignore-not-found
```

### Cách B — Bơm trigger trực tiếp vào SQS (chủ động, không cần chờ Alertmanager)
```bash
export AWS_REGION=us-east-1
QURL=https://sqs.us-east-1.amazonaws.com/012619468490/cdo-telemetry-dev
aws sqs send-message --queue-url "$QURL" --message-body '{
  "ts":"2026-07-02T00:00:00Z",
  "tenant_id":"6c8b4b2b-4d45-4209-a1b4-4b532d56a31c",
  "service":"cdo-sample-api",
  "signal_name":"container_restart_count",
  "value":5,
  "labels":{"system":"K8S_NATIVE","namespace":"tenant-a","deployment":"cdo-sample-api","container":"podinfo"}
}'
# Xem T1 executor log: executor drain message -> build dense-window Prometheus -> /v1/detect ...
kubectl -n self-heal-system logs --tail=40 -f deploy/cdo-executor
```

> ⚠ **Detect phụ thuộc DATA THẬT:** SQS chỉ là *trigger* — executor tự kéo dense-window từ Prometheus cho `cdo-sample-api`. Nếu pod đang khỏe (data phẳng) → engine trả `no_anomaly` (đúng, không false-positive) → `incident_closed: no_action`. Muốn chắc chắn thấy **heal thật** → dùng **Cách A** (inject OOM) hoặc backup **§5** (offline luôn xanh).

**Các event chính cần chỉ trong log (T1):**
`alert_received → detect_called → detect_response_received → pre_decide_decision → idempotency_lock_acquired → decide_called → action_plan_received → safety_passed(6 checks) → rollback_snapshot_captured → execute_done → verify_done → incident_closed: auto_resolved`

---

## 4. An toàn — 3 lớp defense-in-depth (4 phút)

```bash
# 4.1 Kyverno — 4 ClusterPolicy Enforce (lớp admission, độc lập executor)
kubectl get clusterpolicy
# restrict-replicas · restrict-memory-limit · restrict-executor-namespace · restrict-executor-mutations

# 4.2 CHỨNG MINH Kyverno chặn field nguy hiểm (impersonate SA executor, server dry-run — KHÔNG đổi gì thật)
SA=system:serviceaccount:self-heal-system:tf3-cdo-controller
# (a) patch memory hợp lệ -> ALLOW
kubectl -n tenant-a set resources deploy/cdo-sample-api --limits=memory=1024Mi \
  --as=$SA --dry-run=server
# (b) đổi image (self-heal KHÔNG được phép) -> REJECT bởi restrict-executor-mutations
kubectl -n tenant-a set image deploy/cdo-sample-api podinfo=nginx:latest \
  --as=$SA --dry-run=server

# 4.3 RBAC least-privilege per-tenant (executor KHÔNG có ClusterRole)
kubectl auth can-i patch deployments -n tenant-a --as=$SA    # yes
kubectl auth can-i delete namespaces        --as=$SA         # no
```

**Safety Gate (lớp app, trong executor)** — chứng minh bằng scenario runner (§5): `sc11` cross-tenant → deny, `sc12` unsafe action → deny.

---

## 5. Backup LUÔN XANH — offline scenario runner (2 phút)

Deterministic, không phụ thuộc data cluster. Auto-resolve **71.4% / 15 scenario** (target ≥60%), có cả case deny.

```bash
cd executor
python run_scenarios.py            # chạy 1 vòng 15 scenario, in bảng kết quả + tỉ lệ
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
kubectl -n monitoring get secret kube-prometheus-stack-grafana \
  -o jsonpath='{.data.admin-password}' | base64 -d; echo    # mật khẩu admin

# Prometheus (query metric thô, xem dense-window)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-prometheus 9090:9090
#   http://localhost:9090 — thử query: container_memory_working_set_bytes{namespace="tenant-a"}

# Alertmanager (xem alert đang fire)
kubectl -n monitoring port-forward svc/kube-prometheus-stack-alertmanager 9093:9093
#   http://localhost:9093
```

---

## 7. Audit tamper-evident (3 phút) — S3 Object Lock + CloudWatch Logs Insights

Sau khi có incident (§3), lấy `correlation_id` từ executor log rồi:

```bash
export AWS_REGION=us-east-1 MSYS_NO_PATHCONV=1     # MSYS_NO_PATHCONV: tránh Git Bash mangle path /cdo/...

# 7.1 Query audit qua CloudWatch Logs Insights
QID=$(aws logs start-query --log-group-name "/cdo/dev/audit" \
  --start-time $(($(date +%s)-7200)) --end-time $(date +%s) \
  --query-string 'fields @timestamp, correlation_id, event, result, reason | sort @timestamp desc | limit 25' \
  --query queryId --output text)
sleep 3
aws logs get-query-results --query-id "$QID" --query 'results[].[field,value]' --output text

# 7.2 Bằng chứng bất biến — S3 Object Lock GOVERNANCE 90 ngày
aws s3 ls s3://cdo-audit-012619468490-dev/audit/tenant-a/ | tail
#   với 1 object cụ thể:
aws s3api get-object-retention --bucket cdo-audit-012619468490-dev \
  --key audit/tenant-a/<correlation_id>.json          # -> Mode=GOVERNANCE, RetainUntil= +90d
#   thử xóa -> AccessDenied (không bypass được):
aws s3api delete-object --bucket cdo-audit-012619468490-dev \
  --key audit/tenant-a/<correlation_id>.json           # -> AccessDenied
```

---

## 8. Câu chốt cho slide (3 câu)
1. **Hệ thống CHẠY THẬT** trên EKS — self-heal E2E `auto_resolved` với AI engine thật (BOCPD/BARO).
2. **AI quyết định, CDO thực thi an toàn** — Safety Gate 6-check + RBAC per-tenant + Kyverno 4 policy + audit bất biến (SOC2).
3. **Executor tự kéo dense-window Prometheus** — giải đúng bài telemetry cho AI ML engine (SQS chỉ là trigger).

---

## 9. Troubleshooting nhanh (khi demo trục trặc)

| Triệu chứng | Xử lý |
|---|---|
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
