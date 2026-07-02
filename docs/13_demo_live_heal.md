# 13 — Demo LIVE Self-Heal (chiếu khi thuyết trình)

**Cập nhật:** 2026-07-02 · **Shell:** Git Bash, chạy `bash scripts/...` (không `./`), `cd` vào repo trước.

> ## ⭐ ĐỌC TRƯỚC — chọn demo theo ĐỘ TIN CẬY
> Live executor→engine `auto_resolved` **đã chạy được thật** (log bằng chứng: [`evidence/w12-scenario-sim/live_auto_resolved_20260702.log`](../evidence/w12-scenario-sim/live_auto_resolved_20260702.log)) **NHƯNG không tái tạo 100% theo yêu cầu** — engine ML nhạy cảm hình dạng memory (OOM→conf 0.9→auto_resolved; giữ-cao→conf 0.5→escalate; crashloop→no_anomaly). Đây là hành vi ĐÚNG (không báo động bừa) nhưng khó canh live.
>
> **=> Thứ tự demo khuyến nghị (từ chắc chắn nhất):**
> | # | Lệnh | Chứng minh | Tin cậy |
> |---|---|---|---|
> | **1** | `kubectl -n self-heal-system exec -i deploy/ai-engine -- python - < scripts/demo_ai_smoke.py` | **AI engine THẬT** detect 0.95 → decide → verify DONE/ESCALATE | ✅ 100% |
> | **2** | `cd executor && python run_scenarios.py` | Auto-resolve **71.4%** | ✅ 100% |
> | **3** | `bash scripts/live_heal_demo.sh demo` (§dưới) | Executor E2E `auto_resolved` | 🟡 ~50% — dùng làm "đinh" nếu may, hoặc nói "data-sensitive + có log evidence" |
> | 4 | crashloop OB (guide 12) | Escalate an toàn (defense-in-depth) | ✅ |
>
> **Lời thoại nếu #3 ra escalate/no_anomaly:** "Engine ML chỉ hành động khi tín hiệu đủ mạnh — data phẳng/mơ hồ thì nó **escalate cho người** thay vì làm bừa. Đây là zero-unsafe. Bằng chứng auto_resolved thật có trong log evidence." → biến "flaky" thành điểm mạnh an toàn.

Script `live_heal_demo.sh` dưới đây: gây memory-spike có kiểm soát → engine chẩn đoán → executor PATCH_MEMORY → verify. Chạy được, nhưng đọc cảnh báo tin cậy ở trên.

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
| **A — LỚN (chính)** | `bash scripts/live_heal_demo.sh demo` | Tự spike → chờ → trigger → **log self-heal realtime**: detect → decide → safety → execute → verify → **auto_resolved** |
| **B — nhỏ (tùy chọn)** | `kubectl -n tenant-a get pods -l app=$(cat /tmp/.heal_demo_name) -w` | Pod thay đổi khi PATCH áp dụng (bằng chứng action thật) |
| **C — Grafana (tùy chọn)** | xem §4 | Đồ thị memory: baseline phẳng → spike |

> Cửa sổ **A** làm hết (spike + trigger + theo dõi). Cửa sổ B/C chỉ để minh hoạ thêm.

---

## 2. Kịch bản demo — CHỈ 1 LỆNH (bấm live + lời thuyết trình)

**Điều kiện:** đã `deploy` ở §0 và `status` báo `Baseline đủ: YES`.

### Bấm 1 lệnh ở cửa sổ A:
```bash
bash scripts/live_heal_demo.sh demo
```
Lệnh này tự chạy 3 pha (tổng ~3-4 phút, để nguyên cho nó chạy):
```
>> [1/3] SPIKE memory 635MB ...          ← gây sự cố memory thật
>> [2/3] Chờ spike vào Prometheus (~150s)...   ← trong lúc này thuyết trình kiến trúc
>> [3/3] Gửi trigger + theo dõi self-heal:      ← log bắt đầu chạy
```
> **[NÓI khi pha 1-2 chạy]** "Em vừa đẩy memory một workload lên ~635MB (mô phỏng memory leak) trên nền baseline phẳng 11 phút. Executor sẽ tự kéo chuỗi metric dày từ Prometheus và hỏi AI engine."

### Chuỗi self-heal hiện ở pha [3/3] (cùng một `correlation_id`):
```
prom_window_built ... points deployment=heal-demo-...       ← executor tự kéo dense-window Prometheus
detect_response_received anomaly=true confidence=0.9 severity=0.95    ← AI DETECT
action_plan_received PATCH_MEMORY_LIMIT (OOMPatchMemoryRunbook)       ← AI DECIDE
safety_passed checks=pattern_type_valid,verify_policy_present,action_allow_list,pattern_routing,tenant_match,blast_radius   ← 6-CHECK
execute_done PATCH_MEMORY_LIMIT result=success                       ← THỰC THI THẬT trên K8s
verify_done next_action=DONE success=true                           ← VERIFY (không rubber-stamp)
incident_closed result=auto_resolved                                ← ⭐ AUTO_RESOLVED
[...] heal-demo-... → auto_resolved
```
> **[NÓI — chỉ vào từng dòng]** "Executor kéo dense-window Prometheus → AI `/v1/detect` (severity 0.95) → `/v1/decide` ra runbook PATCH_MEMORY → **6 kiểm tra an toàn độc lập** → snapshot rollback → **thực thi thật trên K8s** → `/v1/verify` xác nhận hồi phục → **auto_resolved**. AI quyết định, nhưng CDO mới thực thi sau kiểm soát."

Ấn **Ctrl-C** để dừng theo dõi khi đã thấy `auto_resolved`.

---

## 3. Xem KẾT QUẢ (chốt bằng chứng)

**a) Kết quả loop** — dòng cuối: `incident_closed result=auto_resolved`.

**b) Pod đã được xử lý** (PATCH đổi resources → rolling update → pod mới = bằng chứng action thật):
```bash
DEP=$(cat /tmp/.heal_demo_name)
kubectl -n tenant-a get deploy $DEP -o jsonpath='{.spec.template.spec.containers[0].resources}{"\n"}'
# thấy limits.memory + requests.memory đã bị PATCH (request 64Mi -> 256Mi)
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
Trong Grafana → Explore → query (thấy baseline phẳng rồi spike; thay tên theo `cat /tmp/.heal_demo_name`):
```
container_memory_working_set_bytes{namespace="tenant-a",pod=~"heal-demo-.*"}
```
> Đường phẳng ~35MB (baseline) rồi vọt lên ~635MB (spike) — minh hoạ đúng cái engine phát hiện.

---

## 5. Dọn dẹp + QUY TẮC

```bash
bash scripts/live_heal_demo.sh clean     # xóa deployment demo sau khi xong
```

⚠️ **Quy tắc:**
1. **Chỉ chạy `demo` 1 lần / 1 lần deploy.** Sau heal có **cooldown 5 phút** — chạy `demo` lại ngay → `escalate` (low confidence).
2. **Muốn demo LẠI**: `clean` → `deploy` (tên MỚI, cửa sổ SẠCH) → chờ ~11' baseline → `demo`. Mỗi `deploy` tạo tên duy nhất nên KHÔNG bị lẫn data pod cũ.
3. Đừng `deploy` chồng khi đang chờ baseline (tên mới ⇒ baseline mới đếm lại từ 0).

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
