# final-build — IaC + Manifests Integrated (CDO-02)

> Deliverable "final-build" = toàn bộ hạ tầng + manifest tích hợp đang chạy LIVE trên EKS.
> Để KHÔNG phá đường dẫn (CI, runbook, IaC state), build tích hợp **giữ nguyên vị trí gốc** trong repo; file này là bản đồ trỏ tới từng thành phần + cách dựng lại.

## Thành phần build tích hợp (đang LIVE)

| Lớp | Vị trí | Nội dung |
|---|---|---|
| **IaC (Terraform, phase-1)** | [`infra/envs/dev/`](../infra/envs/dev) + [`infra/modules/`](../infra/modules) | VPC, EKS (4× t3.medium, K8s 1.30), IAM/IRSA (executor/ai-engine/forwarder), S3 Object Lock audit, DynamoDB idempotency, SQS+DLQ, ECR (executor/forwarder/ai-engine), CloudWatch log/alarm, Secrets |
| **IaC (Helm, phase-2)** | [`infra/modules/kyverno`](../infra/modules/kyverno), [`argocd`](../infra/modules/argocd), [`monitoring`](../infra/modules/monitoring) | commented trong `main.tf`, bật sau khi cluster ACTIVE — xem [04 §1.4](../docs/04_deployment_design.md) |
| **App manifests** | [`k8s/`](../k8s) (executor, workloads, rbac, namespaces) · [`manifests/`](../manifests) (ai-engine, forwarder, kyverno policies, monitoring, networkpolicies) | Deployment executor `cdo-executor:v8`, ai-engine `ai-engine:v5`, forwarder `cdo-forwarder:v4`, Kyverno 4 ClusterPolicy |
| **Executor source** | [`executor/`](../executor) | self-heal loop, safety_gate, prom_source (dense-window), sqs_source, ai_client, scenarios |
| **Forwarder source** | [`forwarder/`](../forwarder) | Alertmanager→SQS, PII-scrub (regex + key-name) |

## Dựng lại từ số 0 (3 bước — chi tiết trong runbook)
1. **Phase-1 IaC:** `cd infra/envs/dev && terraform apply` (VPC/EKS/audit/IAM/ECR…). Lưu ý import ECR ai-engine nếu đã tồn tại (xem `infra/modules/ecr/main.tf`).
2. **Phase-2 Helm:** bật module kyverno/argocd/monitoring trong `main.tf` → `terraform apply` (xem hướng dẫn trong file).
3. **App + policies:** theo [`docs/09_deploy_runbook_live.md`](../docs/09_deploy_runbook_live.md) (Phase 4–6): namespaces, RBAC, workloads, ai-engine v5, executor, forwarder, Kyverno policies.

## Demo
Kịch bản + lệnh đầy đủ: [`docs/11_demo_guide.md`](../docs/11_demo_guide.md).

## Trạng thái & scorecard
[`docs/10_w12_status_and_demo.md`](../docs/10_w12_status_and_demo.md).
