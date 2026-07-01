# Standup Notes — Task Force 3: Self-Heal Engine — CDO

Format: 14h00 daily · 15 phút strict  
Per người: Done / Doing / Blocker (≤30 giây)  
File này append-only — không xoá entry cũ.

Red flags → ping mentor ngay, không chờ thêm:
- 2 ngày liên tiếp cùng 1 blocker chưa resolve
- AI và CDO disagree contract interpretation, không thống nhất được
- Build progress dưới 50% expected mid-week

---

## W11 T1 — Thứ Hai 23/06/2026

**Attendees:** Hữu Tài (PM) · Hà Nguyên (Techlead) · CDO-02 members

---

**Hữu Tài (PM)**
- **Done:** Đọc capstone brief, phân công task cho team, tạo repo và folder structure
- **Doing:** Setup tracking, xác nhận timeline W11-W12 với team
- **Blocker:** Không có blocker

---

**Hà Nguyên (Techlead)**
- **Done:** Đọc brief, chọn angle K8s-heavy / Kubernetes Workflow Orchestration — locked T3 W11. Xác định boundary CDO: AI chỉ decide, CDO execute + safety gate
- **Doing:** Draft `01_requirements_analysis.md`, xác định NFR table và pattern scope
- **Blocker:** Chờ AI team bàn giao image/tag cụ thể để deploy vào namespace `self-heal-system` trên EKS

---

**CDO-02 members**
- **Done:** Đọc 3 contract template, xác định dependency với AI team. Setup EKS cluster dev (`cdo-eks-cluster-dev`, account `012619468490`, us-east-1, K8s 1.30)
- **Doing:** Draft `08_adrs.md`. Apply namespace `tenant-a`, `tenant-b`, `platform` — deploy sample workload `podinfo` vào `tenant-a`
- **Blocker:** EKS public endpoint tạm bật cho workstation IP `14.224.236.94/32` — cần đóng lại sau khi xong setup

---

**Action items:**
- [ ] Hà Nguyên confirm angle locked vào `01_requirements_analysis.md`
- [ ] Members đóng EKS public endpoint sau khi xong kubeconfig setup
- [ ] Draft ADR gửi trước EOD T2

---

## W11 T2 — Thứ Ba 24/06/2026

**Attendees:** Hữu Tài (PM) · Hà Nguyên (Techlead) · CDO-02 members

---

**Hữu Tài (PM)**
- **Done:** Review progress T1, cập nhật tracking
- **Doing:** Theo dõi contract sync với AI team, đảm bảo CDO không bị block
- **Blocker:** Không có blocker

---

**Hà Nguyên (Techlead)**
- **Done:** Hoàn thành draft `01_requirements_analysis.md` — NFR table, pattern scope (3 build + 2 design-only), open questions với AI/trainer
- **Doing:** Draft `02_infra_design.md` — architecture diagram, safety gate design, multi-tenant flow
- **Blocker:** Chưa có tenant UUID chính thức từ AI — đang dùng placeholder, cần AI confirm trước khi freeze doc

---

**CDO-02 members**

- **Doing:** Draft `03_security_design.md`. Setup kube-prometheus-stack Helm, viết `Prometheus.md` và `M6-IaC_Observability_v1.0.md`
- **Blocker:** Alertmanager webhook sink chưa có target — đang dùng mock endpoint tạm

---

**Action items:**
- [ ] Hà Nguyên gửi draft `02_infra_design.md` để team review trước EOD T3
- [ ] Members hoàn thành `03_security_design.md` và test Alertmanager → webhook → CloudWatch log flow

---

## W11 T3 — Thứ Tư 25/06/2026

**Attendees:** Hữu Tài (PM) · Hà Nguyên (Techlead) · CDO-02 members

---

**Hữu Tài (PM)**
- **Done:** Confirm AI team đã publish contract tại commit `86b32e7` — CDO có thể sync
- **Doing:** Chuẩn bị checklist Pack #1 review, track tiến độ các docs còn lại
- **Blocker:** Mock AI endpoint chưa có URL — CDO chưa smoke test được auth flow. Đang chờ AI team, nếu không có EOD T4 sẽ ping mentor

---

**Hà Nguyên (Techlead)**
- **Done:** Sync toàn bộ docs với AI contract commit `86b32e7` — `01`, `02`, `03`, `04`, `08` aligned. Ghi `evidence/ai-coordination/AI_PENDING_QUESTIONS.md` với 12 câu hỏi còn lại. Tạo `05_cost_analysis.md`
- **Doing:** Final review tất cả docs trước Pack #1, coordinate open questions với AI team
- **Blocker:** Không có blocker

---

**CDO-02 members**
- **Done:** `03_security_design.md` hoàn chỉnh. `07_test_eval_report_v1.0_Duc.md` hoàn chỉnh — TC-01 → TC-17, SLO table, audit trail spec, inject scripts, 4h timeline. Prometheus + Alertmanager chạy thật trong cluster, fake alert rule test được E2E flow
- **Doing:** `04_deployment_design.md`. Wire Alertmanager → CDO executor webhook, viết PrometheusRule cho known patterns
- **Blocker:** Mock AI endpoint chưa có URL — không test được SigV4 auth flow end-to-end. **Ngày 1 chờ** — nếu EOD T4 vẫn chưa có → escalate mentor

---

**Action items:**
- [ ] Hữu Tài: theo dõi mock endpoint URL từ AI — deadline EOD T4, nếu miss ping mentor ngay
- [ ] Hà Nguyên: finalize tất cả docs trước T6 sẵn sàng Pack #1
- [ ] Members: hoàn thành `04_deployment_design.md` trước EOD T4, đóng EKS public endpoint

---

<!-- Append standup tiếp theo ở đây -->
