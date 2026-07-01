# Cost Analysis - Task Force 3 Self-Heal Engine - CDO-02

**Doc owner:** CDO-02  
**Trạng thái:** W12 — §8 đã điền **measured actual** từ Cost Explorer  
**Cập nhật lần cuối:** 2026-07-02  

---

## 1. Mục tiêu tài liệu

Tài liệu này ước tính chi phí vận hành platform CDO-02 trong môi trường sandbox capstone (W11-W12) và dự báo chi phí nếu scale lên production với 2 tenant thật. Mọi con số W11 là **forecast** dựa trên thiết kế; cột "Actual" (§8) đã được **đo thực tế** từ AWS Cost Explorer ở W12 (2026-07-02).

Scope cost CDO-02 bao gồm: VPC/networking, EKS cluster, observability stack, audit/storage, messaging buffer và các AWS managed services. **Không bao gồm** chi phí AI inference (Bedrock) vì đó là responsibility của AI team.

---

## 2. Giả định và tham số tính toán

| Tham số | Giá trị | Ghi chú |
|---|---|---|
| Region | `us-east-1` | Theo client brief |
| Môi trường | Sandbox (1 environment) | Capstone scope |
| Số tenant | 2 (`tenant-a`, `tenant-b`) | Hard requirement TF3 |
| Thời gian chạy sandbox | ~10 ngày (W11 T6 → W12 T5) | Từ khi build chính thức đến code freeze |
| Node group EKS | `t3.medium` × **desired 4**, min 2, max 5 | Scale 2→3→4 để chứa Online Boutique (11 svc) + engine (W12) |
| Simulation window test | ≥ 4 giờ | Theo test eval requirement |
| Đơn vị giá | USD, on-demand pricing us-east-1 | Không dùng Reserved/Savings Plans cho sandbox |

---

## 3. Breakdown Chi Phí Theo Thành Phần

### 3.1 Amazon EKS

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| EKS Cluster fee | 1 cluster | $0.10/h | $2.40 | **$24.00** |
| EC2 Node: t3.medium × **4** | 2 vCPU, 4 GB RAM mỗi node | $0.0416/h/node | $4.00 | **$40.00** |
| EBS gp3 root volume × 4 nodes | 20 GB/node | $0.08/GB/month | $0.20 | **$2.00** |
| **Subtotal EKS** | | | **~$6.60/ngày** | **~$66.00** |

> **Cập nhật W12**: scale lên **4 node** (từ 2) để chứa Online Boutique (11 microservice làm workload thật cho AI) + loadgen + engine. Chi phí EC2 node ~×2. Nếu chỉ demo self-heal (không cần OB), có thể về 3 node.

### 3.2 Amazon VPC & Networking

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| NAT Gateway | 1 single NAT (demo/cost choice) | $0.045/h + $0.045/GB | $1.08 | **$10.80** |
| NAT Gateway data processed | ~4 GB/ngày (image pull + internet traffic) | $0.045/GB | $0.18 | **$1.80** |
| VPC Gateway Endpoint — S3 | Gateway type, traffic AWS không qua NAT | **FREE** | $0.00 | **$0.00** |
| VPC Gateway Endpoint — DynamoDB | Gateway type, traffic AWS không qua NAT | **FREE** | $0.00 | **$0.00** |
| Data transfer inter-AZ | ~1 GB/ngày | $0.01/GB | $0.01 | **$0.10** |
| **Subtotal VPC** | | | **$1.27/ngày** | **~$12.70** |

> Ghi chú: Dùng **Single NAT Gateway** để tối ưu cost cho demo. S3 và DynamoDB dùng **Gateway Endpoint** (miễn phí hoàn toàn — không tính giờ, không tính data) — traffic audit S3 write, TF state, và DynamoDB idempotency lock không đi qua NAT. ECR image pull (Docker Hub/ghcr.io) vẫn đi qua NAT vì không có Gateway Endpoint cho ECR. Production sẽ cần NAT per-AZ cho HA.

### 3.3 Amazon S3 - Audit & State

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| S3 Object Lock audit bucket | ~500 MB audit logs (10 ngày) | $0.023/GB/month | $0.004 | **$0.04** |
| S3 PUT requests (audit writes) | ~10,000 objects/ngày | $0.005/1,000 | $0.05 | **$0.50** |
| CloudWatch Logs Insights (audit query) | ~1,000 queries | scan-based, dưới free-tier | $0.001 | **$0.01** |
| S3 Terraform remote state | ~1 MB | negligible | - | **< $0.01** |
| S3 Object Lock storage overhead | WORM governance mode | included in storage | - | - |
| **Subtotal S3** | | | **~$0.06/ngày** | **~$0.55** |

### 3.4 Amazon DynamoDB - Idempotency Lock

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| DynamoDB On-Demand (Write) | ~5,000 WCU/ngày (1 WCU = 1KB write) | $1.25/million WCU | $0.006 | **$0.06** |
| DynamoDB On-Demand (Read) | ~10,000 RCU/ngày | $0.25/million RCU | $0.003 | **$0.03** |
| DynamoDB storage | < 1 GB (TTL auto-delete sau 24 giờ) | $0.25/GB/month | negligible | **< $0.01** |
| **Subtotal DynamoDB** | | | **~$0.01/ngày** | **~$0.10** |

### 3.5 Amazon SQS - Telemetry Buffer & DLQ

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| SQS Standard Queue (telemetry buffer) | ~100,000 messages/ngày | Free tier: 1M/month | $0.00 | **$0.00** |
| SQS DLQ (malformed telemetry) | < 1,000 messages/ngày | Included trong free tier | $0.00 | **$0.00** |
| **Subtotal SQS** | | | **$0.00/ngày** | **~$0.00** |

> Ghi chú: SQS Free Tier 1 triệu requests/tháng đủ cho sandbox capstone. Cost thực tế = $0.

### 3.6 Amazon CloudWatch - Logs & Metrics

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| CloudWatch Logs Ingestion | executor boto3 PutLogEvents trực tiếp (không có FluentBit/CWAgent) — nằm trong free tier 5GB/tháng | $0.50/GB (sau free tier) | ~$0.00 | **~$0.00** |
| CloudWatch Logs Storage | 5 log groups: 4 × 7 ngày retention, 1 × 7 ngày retention (audit — đã giảm từ 30) | $0.03/GB/month | negligible | **~$0.01** |
| CloudWatch Alarms | 3 alarms (executor error, Kyverno deny, DLQ rate) | $0.10/alarm/month | $0.01 | **$0.10** |
| **Subtotal CloudWatch** | | | **~$0.01/ngày** | **~$0.11** |

> Ghi chú: Không có FluentBit DaemonSet hay CloudWatch Agent trong Terraform — log ingestion chỉ từ executor code gọi `boto3 PutLogEvents` trực tiếp. Volume thực tế nằm trong free tier 5GB/tháng. Tổng 3 alarms trong Terraform (không phải 10 như forecast ban đầu). Audit log group đã giảm retention từ 30 → 7 ngày; S3 Object Lock (90 ngày) là source of truth theo contract.

### 3.7 Amazon ECR - Container Images

> **Ghi chú:** ECR chỉ phát sinh cost từ **W12** khi CDO-02 build và push image thật (executor, collector). W11 chỉ có Terraform skeleton + manifests, chưa có image nào được build/push.

| Item | Spec | Đơn giá | Ước tính W11 | Ước tính W12 (6 ngày) |
|---|---|---|---|---|
| ECR Storage (CDO runtime images) | ~2 GB (executor + collector images) | $0.10/GB/month | $0.00 | **$0.07** |
| ECR Data Transfer (pull to EKS) | ~500 MB/deploy × ~5 deploys | $0.09/GB (after 1GB free) | $0.00 | **$0.22** |
| **Subtotal ECR** | | | **$0.00** | **~$0.29** |

### 3.8 CloudWatch Logs Insights - Audit Query (thay Athena)

> **Cập nhật W12**: chọn **CloudWatch Logs Insights** (group `/cdo/dev/audit`) làm lớp query audit thay vì Glue+Athena — rẻ + đơn giản hơn, không cần crawler/catalog. S3 Object Lock vẫn là source-of-truth tamper-evident (ADR-010).

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| Logs Insights query (audit by correlation_id) | ~20 queries/ngày × ~50MB scanned | $0.005/GB scanned | ~$0.005 | **~$0.05** |
| **Subtotal Audit query** | | | **~$0.005/ngày** | **~$0.05** |

### 3.9 AWS IAM / Secrets Manager

| Item | Spec | Đơn giá | Ước tính/ngày | Ước tính 10 ngày |
|---|---|---|---|---|
| Secrets Manager (AI auth, webhook key) | 2 secrets | $0.40/secret/month | $0.03 | **$0.27** |
| API calls (GetSecretValue) | ~1,000/ngày | $0.05/10,000 | negligible | **< $0.01** |
| **Subtotal Secrets Manager** | | | **~$0.03/ngày** | **~$0.28** |

### 3.10 Observability Stack (In-Cluster)

Components chạy trong EKS cluster (Prometheus, Alertmanager, Grafana, OTel Collector) không phát sinh chi phí AWS riêng - cost đã gộp vào EC2 node của EKS ở mục 3.1.

| Component | Tài nguyên ước tính | Cost phát sinh |
|---|---|---|
| Prometheus + Alertmanager | ~500m CPU, ~512MB RAM | Included trong EKS nodes |
| Grafana | ~100m CPU, ~128MB RAM | Included trong EKS nodes |
| OTel Collector | ~200m CPU, ~256MB RAM | Included trong EKS nodes |
| kube-state-metrics + node-exporter | ~50m CPU, ~64MB RAM | Included trong EKS nodes |

---

## 4. Tổng Hợp Chi Phí Sandbox (10 ngày)

| Thành phần | Ước tính 10 ngày | % tổng |
|---|---:|---:|
| Amazon EKS (cluster + nodes) | $50.00 | 50.0% |
| VPC & Networking (NAT + VPC Endpoints + ECR endpoints) | $25.15 | 23.5% |
| CloudWatch (logs + metrics + alarms) | $15.53 | 15.5% |
| Amazon ECR | $0.29 | 0.3% |
| Amazon S3 (audit + state) | $0.55 | 0.5% |
| Amazon DynamoDB | $0.10 | 0.1% |
| Amazon SQS | $0.00 | 0.0% |
| CloudWatch Logs Insights (audit query) | $0.10 | 0.1% |
| Secrets Manager | $0.28 | 0.3% |
| **Tổng CDO-02 platform** | **~$92.00** | **100%** |

> **Không bao gồm**: AI inference cost (Bedrock) - thuộc budget AI team, capped $50/tenant/ngày theo AI contract.

---

## 5. Phân Tích Cost Driver

**Top 3 cost drivers:**

1. **EKS nodes (50%)** - t3.medium × 2 nodes chạy liên tục là cost lớn nhất. Có thể giảm bằng cách tắt cluster ngoài giờ test, nhưng cho sandbox liên tục thì đây là mức baseline.

2. **NAT Gateway (20%)** - Single NAT cho demo nhưng vẫn tốn $0.045/h. Có thể loại bỏ nếu dùng VPC Endpoints cho tất cả traffic AWS (S3, CloudWatch, DynamoDB, ECR đều đã có endpoint), nhưng cần verify traffic path không còn ra internet.

3. **CloudWatch (15%)** - Log ingestion $0.50/GB là đáng kể khi có nhiều workload log. Tối ưu bằng cách set retention 3-7 ngày cho sandbox thay vì default.

---

## 6. Cost Optimization Đã Áp Dụng

| Optimization | Tác động | Ghi chú |
|---|---|---|
| Single NAT Gateway thay vì per-AZ | Tiết kiệm ~$32/10 ngày | Chấp nhận single point of failure cho demo |
| SQS Free Tier | Tiết kiệm ~$4/10 ngày | Sandbox volume nằm trong free tier |
| DynamoDB On-Demand (không provisioned) | Tiết kiệm ~$5/10 ngày | On-demand thích hợp cho traffic không đều |
| CloudWatch Logs Insights thay vì OpenSearch | Tiết kiệm ~$30/10 ngày | Query by correlation_id đủ dùng Logs Insights (ADR-004/010), không cần Glue+Athena/OpenSearch |
| In-cluster Prometheus thay vì Amazon Managed Prometheus | Tiết kiệm ~$20/10 ngày | Sandbox không cần managed service |
| EKS node desired=2 (không over-provision) | Baseline cost thấp | Scale up chỉ khi load test |
| **VPC Gateway Endpoint S3 + DynamoDB** (W12) | Giảm NAT data charge cho S3/DynamoDB traffic; endpoint bản thân FREE | Implemented trong `infra/modules/vpc/main.tf` — traffic audit write + TF state + idempotency không qua NAT |
| **CloudWatch audit log retention 30→7 ngày** (W12) | Giảm log storage cost; S3 Object Lock 90 ngày là source of truth | Implemented trong `infra/modules/observability/main.tf`; không ảnh hưởng compliance rubric |

---

## 7. Dự Báo Chi Phí Production (2 Tenant, 1 Tháng)

Nếu scale từ sandbox lên production thật với 2 tenant chạy liên tục:

| Thành phần | Sandbox 10 ngày | Production/tháng | Ghi chú |
|---|---:|---:|---|
| EKS cluster + nodes (×3 HA) | $50 | ~$450 | Multi-AZ, min 3 nodes t3.large |
| NAT Gateway (×3 AZ cho HA) | $20 | ~$100 | Per-AZ NAT cho production |
| CloudWatch | $15 | ~$80 | Volume cao hơn, retention 30 ngày |
| S3 Object Lock (90 ngày retention) | $1 | ~$15 | Audit grows over time |
| DynamoDB | $0.10 | ~$5 | Higher throughput |
| RDS/Aurora (nếu cần persistent state) | - | ~$50 | Optional, not in sandbox |
| Total CDO platform (không AI) | **~$87** | **~$700/tháng** | |
| Per tenant/tháng | - | **~$350/tenant** | |

---

## 8. Bảng So Sánh: Actual vs Forecast (MEASURED W12 — 2026-07-02)

**Nguồn số liệu:** AWS Cost Explorer (`aws ce get-cost-and-usage`), account `012619468490`, cửa sổ **30 ngày gần nhất** (2026-06-02 → 2026-07-02), metric `UnblendedCost` (gross, pre-credit), lọc `RECORD_TYPE=Usage` để loại các dòng credit/tax.

| Thành phần | Forecast (W11, 10 ngày) | **Actual gross (đo, 30 ngày)** | Ghi chú |
|---|---:|---:|---|
| EKS cluster + nodes | $50.00 | **$16.20** | EKS control plane $14.10 + EC2-Compute node $2.10 |
| VPC & Networking | $25.15 | **$2.55** | EC2-Other (NAT/EBS/endpoint) $2.25 + VPC $0.15 + ELB $0.15 |
| CloudWatch | $15.53 | **$0.00** | Nằm trong free-tier (logs/metrics dưới ngưỡng) |
| KMS (EKS secret encryption) | — | **$0.43** | Không có trong forecast W11 |
| Secrets Manager + ECR | $0.57 | **$0.015** | Secrets $0.014 + ECR $0.0005 |
| S3 + DynamoDB + SQS | $0.75 | **$0.005** | S3 $0.005; DynamoDB/SQS $0 (free-tier) |
| RDS + Cost Explorer API | — | **$0.07** | RDS leftover $0.05 + CE API query $0.02 (chi phí tạo doc này) |
| **Total gross (list price)** | **~$92.00** | **~$19.28** | |
| **Net billed (sau AWS Credits)** | — | **≈ $0.00** | Credit −$19.28 offset 100% Usage → out-of-pocket ≈ 0 |

**Giải thích chênh lệch (gross $19.28 đo < $92 forecast):**
1. **Cluster chỉ chạy một phần cửa sổ 30 ngày** — deploy live gần đây (không phải cả tháng); EKS control plane $14.10 cho thấy cluster chạy ~6 ngày, không phải 30.
2. **CloudWatch/DynamoDB/SQS nằm trong free-tier** — forecast tính list price, thực tế = $0.
3. **VPC endpoint + single-NAT** đã tối ưu (xem §6) → networking $2.55 thay vì $25 forecast.
4. **100% chi phí được AWS Credits che** → out-of-pocket thực tế của account = **$0.00** (net billed).

> Đối chiếu apples-to-apples không hoàn hảo (forecast 10 ngày vs đo 30 ngày, cluster chạy partial) — nhưng **hướng đúng: chi phí thực thấp hơn forecast bảo thủ, và net billed = $0 nhờ credits**. Reproduce: `aws ce get-cost-and-usage --time-period Start=2026-06-02,End=2026-07-02 --granularity MONTHLY --metrics UnblendedCost --filter '{"Dimensions":{"Key":"RECORD_TYPE","Values":["Usage"]}}' --group-by Type=DIMENSION,Key=SERVICE`.

---

## 9. Cost Guardrails

Để tránh runaway cost trong capstone:

| Guardrail | Cơ chế | Threshold |
|---|---|---|
| AWS Budget Alert | CloudWatch Alarm + SNS | Alert khi spend > $80 (warning) |
| AWS Budget Hard Cap | AWS Budgets action | Stop EC2 nếu spend > $120 |
| EKS node scale cap | Managed node group max | max 5 nodes × t3.medium |
| CloudWatch log retention | Log group retention policy | 7 ngày cho sandbox |
| S3 lifecycle policy | Transition to Glacier | Sau 30 ngày cho audit non-critical |

---

## Tài Liệu Liên Quan

- [`02_infra_design.md`](02_infra_design.md) - Component list và architecture
- [`04_deployment_design.md`](04_deployment_design.md) - IaC và deployment strategy
- [`07_test_eval_report.md`](07_test_eval_report.md) - SLO evidence và test window (measured W12)
- AI team `docs/template/03_ai_engine_spec.md` §8 - AI inference cost (Bedrock, thuộc AI budget)
