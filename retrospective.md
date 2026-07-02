# Retrospective — TF3 CDO-02 (Phase 2 Capstone)

> Nhìn lại 2 tuần build. Trung thực về trade-off > tô hồng. Điền phần _TODO_.

## 1. Kết quả đạt được (số liệu)
- ✅ Deploy **LIVE** trên EKS thật (account 012619468490 / us-east-1), E2E `auto_resolved` proven.
- ✅ Auto-resolve **71.4%** (106330/148862 incidents, 10633 rounds, 4h offline sim) — target ≥60%.
- ✅ AI Engine thật V5 (BOCPD/BARO) tích hợp: detect ~2.2s, decide <0.1s, verify không rubber-stamp.
- ✅ 3 lớp an toàn: Safety Gate 6-check + RBAC per-tenant + **Kyverno 4 ClusterPolicy**.
- ✅ Audit tamper-evident: S3 Object Lock GOVERNANCE 90d + CloudWatch Logs Insights.
- ✅ Cost đo thật: gross $19.28/30d, net ~$0 (AWS credits).
- ✅ 11 ADR, 8/8 hard-requirement (scorecard [docs/10](docs/10_w12_status_and_demo.md)).

## 2. Cái gì làm TỐT (keep)
- _<TODO>_ (vd: quyết định dense-window Prometheus giải đúng bài telemetry cho ML)
- _<TODO>_ (vd: tách AI decide / CDO execute — an toàn, dễ audit)

## 3. Cái gì CHƯA tốt / khó khăn (improve)
- Deferred path (SCALE/ROTATE) mới là **stub** — chưa auto Git-ops (có chủ đích, nhưng là gap).
- Nhiều add-on cài tay ngoài Terraform (LB controller, Kyverno policies, app manifests) → `terraform apply` không dựng lại full cụm (đã tài liệu hóa [04 §1.4](docs/04_deployment_design.md)).
- Cold-start AI engine lần đầu >15s → phải pre-warm trước demo.
- _<TODO: thêm>_

## 4. Bài học (lessons)
- _<TODO>_ (vd: engine detect phụ thuộc data thật — data phẳng ra no_anomaly, cần inject fault để demo heal)
- _<TODO>_ (vd: file evidence 431MB không push được GitHub → tách summary)

## 5. Nếu làm lại (next time)
- _<TODO>_ (vd: S3 backend cho Terraform state ngay từ đầu; đưa toàn bộ add-on vào IaC/ArgoCD)

## 6. Phân công & phối hợp
- _<TODO: team làm việc thế nào, điều gì cải thiện>_
