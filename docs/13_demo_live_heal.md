# 13 — Demo LIVE Self-Heal `auto_resolved` (chiếu khi thuyết trình)

**Cập nhật:** 2026-07-02 · **Đã VERIFY bằng log thật.** Dùng script [`scripts/live_heal_demo.sh`](../scripts/live_heal_demo.sh).
Đây là kịch bản để **bấm live trước mentor**: gây memory-spike có kiểm soát → AI engine thật chẩn đoán → executor PATCH_MEMORY an toàn → verify → **`auto_resolved`**.

> **Shell:** mở **Git Bash** (Windows) và chạy bằng `bash scripts/...` (KHÔNG dùng `./`). `cd` vào thư mục repo trước.

> **Vì sao pattern này:** engine ML (BOCPD) chỉ báo `mem` khi có **baseline phẳng ≥40 điểm (~11 phút) RỒI spike**. Workload thật phẳng → không tự fire (đúng, không false-positive). Script tạo `mem-demo` (container tên `podinfo` để `PATCH_MEMORY` khớp) giữ baseline rồi spike theo lệnh → heal sạch.

---

## 0. Chuẩn bị (làm ĐẦU BUỔI, trước khi tới lượt ≥12 phút)

```bash
cd ~/Documents/capstone-huutai/TF3-Self-Heal-Agent-AWS
aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1

# Pre-warm engine (tránh cold-start >15s) — 1 dòng
kubectl -n self-heal-system exec deploy/ai-engine -- python -c "import urllib.request;print(urllib.request.urlopen('http://127.0.0.1:8080/health',timeout=5).read().decode())"

# Khởi tạo baseline (đồng hồ bắt đầu chạy ~11 phút)
bash scripts/live_heal_demo.sh deploy
```
> Sau lệnh `deploy`, baseline tích luỹ. **KHÔNG chạy `deploy` lại** (mỗi lần deploy = pod mới = baseline reset về 0).

Trong lúc trình bày slide/kiến trúc (~11 phút), thỉnh thoảng kiểm tra:
```bash
bash scripts/live_heal_demo.sh status
```
Chờ tới khi thấy: **`Baseline đủ (>=40 điểm): YES`** → sẵn sàng demo.

---

## 1. Bố trí màn hình khi demo (để mentor THẤY rõ)

Mở **2 cửa sổ Git Bash cạnh nhau** (+ 1 tab Grafana tùy chọn):

| Cửa sổ | Lệnh | Hiển thị gì cho mentor |
|---|---|---|
| **A — LỚN (chính)** | `bash scripts/live_heal_demo.sh watch` | Log self-heal chạy realtime: detect → decide → safety → execute → verify → **auto_resolved** |
| **B — nhỏ** | `kubectl -n tenant-a get pods -l app=mem-demo -w` | Pod thay đổi khi PATCH áp dụng (bằng chứng action thật) |
| **C — Grafana (tùy chọn)** | xem §4 | Đồ thị memory: baseline phẳng → spike (trực quan) |

> Mở cửa sổ **A** (`watch`) TRƯỚC, rồi mới sang cửa sổ khác bấm `spike` — để mentor thấy log chạy ngay khi spike.

---

## 2. Kịch bản 3 bước (bấm live + lời thuyết trình)

### Bước 1 — Cửa sổ A: bật theo dõi
```bash
bash scripts/live_heal_demo.sh watch
```
> **[NÓI]** "Đây là log của CDO executor. Em sẽ tạo một sự cố memory thật trên workload `mem-demo`, và hệ sẽ tự chẩn đoán + xử lý."

### Bước 2 — Cửa sổ B (hoặc tab khác): gây spike
```bash
bash scripts/live_heal_demo.sh spike
```
> **[NÓI]** "Vừa bơm memory workload nhảy vọt lên ~635MB (mô phỏng memory leak). Baseline phẳng 11 phút trước đó đã có sẵn — giờ engine sẽ thấy điểm bất thường."

### Bước 3 — Nhìn cửa sổ A: self-heal chạy (~30–90s)
Chuỗi event sẽ hiện (cùng một `correlation_id`):
```
[watcher] phát hiện OOM_KILL/CRASH_LOOP tại tenant-a/mem-demo
prom_window_built ... points deployment=mem-demo          ← executor tự kéo dense-window Prometheus
detect_response_received ... anomaly=true confidence=0.9 severity=0.95    ← AI DETECT
action_plan_received PATCH_MEMORY_LIMIT (OOMPatchMemoryRunbook)           ← AI DECIDE
safety_passed checks=pattern_type_valid,verify_policy_present,action_allow_list,pattern_routing,tenant_match,blast_radius   ← 6-CHECK
rollback_snapshot_captured
execute_done PATCH_MEMORY_LIMIT result=success target=deployment/mem-demo ← THỰC THI THẬT
verify_done next_action=DONE success=true                                ← VERIFY (không rubber-stamp)
incident_closed result=auto_resolved                                     ← ⭐ AUTO_RESOLVED
[watcher] tenant-a/mem-demo → auto_resolved
```
> **[NÓI — chỉ vào từng dòng]** "Executor tự kéo chuỗi metric dày từ Prometheus → gọi AI `/v1/detect` (severity 0.95) → `/v1/decide` ra runbook PATCH_MEMORY → **qua 6 kiểm tra an toàn độc lập** → chụp snapshot rollback → **thực thi thật trên K8s** → `/v1/verify` xác nhận → **auto_resolved**. Toàn bộ tự động, AI quyết định nhưng CDO mới là bên thực thi sau kiểm soát."

---

## 3. Xem KẾT QUẢ (chốt bằng chứng)

**a) Kết quả loop** — dòng cuối ở cửa sổ A: `incident_closed result=auto_resolved`.

**b) Pod đã được xử lý** (cửa sổ B): sau `execute_done`, pod `mem-demo` được tạo lại (PATCH đổi resources → rolling update) → bằng chứng action đã áp dụng thật:
```bash
kubectl -n tenant-a get deploy mem-demo -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
# thấy limits.memory + requests.memory đã bị PATCH
```

**c) Audit bất biến** — lấy `correlation_id` ở cửa sổ A rồi query (1 dòng mỗi lệnh):
```bash
export AWS_REGION=us-east-1 MSYS_NO_PATHCONV=1
QID=$(aws logs start-query --log-group-name "/cdo/dev/audit" --start-time $(($(date +%s)-1800)) --end-time $(date +%s) --query-string 'fields @timestamp, correlation_id, event, result | filter event="incident_closed" | sort @timestamp desc | limit 10' --query queryId --output text)
sleep 3
aws logs get-query-results --query-id "$QID" --query 'results[].[field,value]' --output text
```
> **[NÓI]** "Mọi bước được ghi audit vào S3 Object Lock (GOVERNANCE 90 ngày, xóa → AccessDenied) và query được qua CloudWatch Logs Insights theo correlation_id."

---

## 4. (Tùy chọn) Grafana — hình ảnh trực quan memory

```bash
kubectl -n monitoring port-forward svc/kube-prometheus-stack-grafana 3000:80
# http://localhost:3000  (user: admin)
kubectl -n monitoring get secret kube-prometheus-stack-grafana -o jsonpath='{.data.admin-password}' | base64 -d; echo
```
Trong Grafana → Explore → query (thấy baseline phẳng rồi spike):
```
container_memory_working_set_bytes{namespace="tenant-a",pod=~"mem-demo-.*"}
```
> Đường phẳng ~35MB (baseline) rồi vọt lên ~635MB (spike) — minh hoạ đúng cái engine phát hiện.

---

## 5. Dọn dẹp + QUY TẮC one-shot

```bash
bash scripts/live_heal_demo.sh clean     # xóa mem-demo sau demo
```

⚠️ **3 quy tắc bắt buộc:**
1. **Chỉ `spike` 1 lần.** Sau heal có **cooldown 5 phút** — spike lần 2 → `escalate` (low confidence), không phải auto_resolved.
2. **Đừng `deploy` lại** khi đang chờ baseline (reset về 0).
3. Sau heal, PATCH tạo lại pod → baseline reset → nếu muốn demo lại phải chờ ~11 phút baseline mới.

---

## 6. Troubleshooting (khi demo trục trặc)

| Triệu chứng | Xử lý |
|---|---|
| `status` báo `Baseline đủ: CHUA` | Chờ thêm 1–3 phút (cần ≥40 điểm ~11'). Đừng spike sớm → sẽ `no_anomaly`. |
| Spike rồi mà ra `no_anomaly` | Baseline chưa đủ điểm lúc trigger, hoặc pod vừa bị tạo lại (reset). `status` kiểm tra rồi thử lại. |
| Ra `escalate:low_confidence` | Đang trong cooldown/đã heal trước đó. Chờ 5' hoặc `clean` + `deploy` lại (chờ baseline). |
| `exec " python" not found` / lỗi cú pháp | Đang ở PowerShell hoặc paste dính dòng → mở **Git Bash**, copy lệnh 1 dòng. |
| Pod cứ Terminating | Có heal vừa chạy (PATCH → pod mới) — bình thường. Đảm bảo KHÔNG có script nền nào đang spike lặp. |
| Cần con số auto-resolve tổng | Backup luôn xanh: `cd executor && python run_scenarios.py` → **71.4%**. |

---

## 7. Fallback KHÔNG cần chờ baseline (nếu hết giờ)

Muốn cho thấy **AI engine thật** chạy detect/decide/verify **tức thì** (không qua executor, không chờ 11'):
```bash
kubectl -n self-heal-system exec -i deploy/ai-engine -- python - < scripts/demo_ai_smoke.py
```
→ In: `[DETECT] anomaly=True severity=0.95` · `[DECIDE] PATCH_MEMORY_LIMIT` · `[VERIFY] DONE / ESCALATE`.

> Tổng kết 3 mức demo: **(1) live auto_resolved** (file này) · **(2) AI engine tức thì** (`demo_ai_smoke.py`) · **(3) số auto-resolve 71.4%** (`run_scenarios.py`).
