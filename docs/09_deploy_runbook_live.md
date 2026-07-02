# 09 — Deploy Runbook (Live) · TF3 Self-Heal + Observability

**Mục tiêu:** deploy đầy đủ hôm nay. AI Engine nhận mai → chỉ swap image vào slot đã sẵn.
**Account/Region:** `012619468490` / `us-east-1`. Cluster `cdo-eks-cluster-dev`.
**Thứ tự bắt buộc** — mỗi bước phụ thuộc bước trước.

---

## Phase 0 — Bootstrap state bucket (1 lần)

```bash
cd infra/bootstrap
terraform init
terraform apply -auto-approve     # tạo cdo-tf-state-012619468490-dev (us-east-1)
```

## Phase 1 — Hạ tầng AWS (VPC · EKS · IAM · audit · observability · ECR · secrets)

```bash
cd ../envs/dev
terraform init                    # backend S3 (đã cấu hình)
terraform apply -auto-approve     # ~15 phút (EKS lâu nhất)
terraform output                  # LƯU LẠI: cluster_name, audit_bucket_name, sqs_queue_url,
                                  #   executor_role_arn, forwarder_role_arn,
                                  #   ecr_executor_url, ecr_forwarder_url, ai_engine_role_arn
```

## Phase 2 — Bật Helm stack (kyverno · argocd · monitoring)

```bash
cd infra/envs/dev
mv providers.tf providers_phase1.tf.bak
mv providers_phase2.tf.disabled providers.tf     # provider trỏ cluster thật
# Bỏ comment module "kyverno" / "argocd" / "monitoring" trong main.tf
terraform init -reconfigure
terraform apply -auto-approve                     # cài kube-prometheus-stack + kyverno + argocd
```

## Phase 3 — Kết nối cluster + build/push image

```bash
aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1
kubectl get nodes

# Executor image
ECR_EXEC=$(terraform -chdir=infra/envs/dev output -raw ecr_executor_url)
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin "${ECR_EXEC%/*}"
docker build -t "$ECR_EXEC:v1" executor/ && docker push "$ECR_EXEC:v1"

# Forwarder image
ECR_FWD=$(terraform -chdir=infra/envs/dev output -raw ecr_forwarder_url)
docker build -t "$ECR_FWD:v1" forwarder/ && docker push "$ECR_FWD:v1"
```

## Phase 4 — Deploy K8s base (namespaces · RBAC · workloads · AI engine · executor)

```bash
kubectl apply -f k8s/00-namespaces.yaml
kubectl apply -f manifests/namespaces/monitoring.yaml
kubectl apply -f k8s/01-rbac.yaml          # điền REPLACE_WITH_EXECUTOR_ROLE_ARN trước
kubectl apply -f k8s/04-workloads.yaml      # podinfo tenant-a/b
# AI Engine THẬT (ai-engine:v5, image AI team bàn giao) — KHÔNG còn dùng mock:
kubectl apply -f manifests/rbac/ai-engine-serviceaccount.yaml   # điền ai_engine_role_arn
kubectl apply -f manifests/ai-engine/deployment.yaml            # image ai-engine:v5, API_PORT=8080
kubectl apply -f k8s/03-executor.yaml       # điền ECR_EXEC, audit bucket, sqs_queue_url
kubectl -n self-heal-system rollout status deploy/ai-engine deploy/cdo-executor
```

**Placeholder cần thay (từ `terraform output`):**
| Placeholder | Lấy từ |
|---|---|
| `REPLACE_WITH_EXECUTOR_ROLE_ARN` | `executor_role_arn` |
| `ai_engine_role_arn` (SA ai-engine) | `ai_engine_role_arn` |
| `REPLACE_WITH_ECR_URL` (executor) | `ecr_executor_url` |
| `REPLACE_WITH_AUDIT_BUCKET` | `audit_bucket_name` |
| `REPLACE_WITH_SQS_QUEUE_URL` | `sqs_queue_url` |

## Phase 5 — Observability pipeline (Prometheus → Alertmanager → Forwarder → SQS → Executor)

```bash
# Forwarder (điền forwarder_role_arn, ecr_forwarder_url, sqs_queue_url trong manifests/forwarder/forwarder.yaml)
kubectl apply -f manifests/forwarder/forwarder.yaml
kubectl apply -f manifests/networkpolicies/allow-alertmanager-to-forwarder.yaml
# Alert rules + scrape + dashboard
kubectl apply -f manifests/monitoring/prometheus-rules.yaml
kubectl apply -f manifests/monitoring/podmonitor.yaml
kubectl apply -f manifests/monitoring/grafana-dashboard-selfheal.yaml
```

## Phase 6 — Kyverno policies + NetworkPolicy self-heal

```bash
kubectl apply -f manifests/kyverno/policies/
kubectl apply -f manifests/networkpolicies/allow-executor-to-ai.yaml
```

## Phase 7 — Verify E2E

```bash
kubectl -n monitoring get pods                       # prometheus/alertmanager/grafana/ksm/node-exporter Ready
kubectl -n monitoring get deploy cdo-telemetry-forwarder
kubectl -n self-heal-system get deploy cdo-executor ai-engine
# Trigger OOM thật:
kubectl run oom-test -n tenant-a --image=polinux/stress --restart=Never -- --vm 1 --vm-bytes 200M --vm-hang 0
# Quan sát chuỗi:
#  Prometheus alert PodOOMKilled Firing → Alertmanager → forwarder log "sqs_sent" →
#  executor log alert_received→...→auto_resolved → S3 audit object theo correlation_id
kubectl -n monitoring logs deploy/cdo-telemetry-forwarder
kubectl -n self-heal-system logs deploy/cdo-executor
```

---

## Ghi chú "không sai sót"
- **Telemetry**: forwarder + SQS hoạt động; executor đọc SQS là nguồn chính, poll K8s 30s là fallback (tự bật nếu `CDO_TELEMETRY_QUEUE_URL` rỗng).
- **AI Engine THẬT** (`ai-engine:v5`, BOCPD/BARO) map đúng runbook (OOM→PATCH_MEMORY_LIMIT, bad-deploy→ROLLOUT_UNDO…). Executor trỏ `AI_BASE_URL=http://ai-engine.self-heal-system.svc.cluster.local:8080` — pipeline tự chạy với AI thật. (Mock `mock_ai_server.py` chỉ còn dùng cho offline scenario sim, KHÔNG deploy live.)
- **Kyverno** đảm bảo zero-unsafe ở cluster-level kể cả khi AI/executor sai.
- **expr PromQL** latency/error (HighLatencyP95/HighErrorRate) phụ thuộc metric podinfo — tinh chỉnh threshold theo dữ liệu thật nếu cần; 4 alert hạ tầng (OOM/crashloop/imagepull/memory) chạy từ kube-state-metrics + kubelet, không cần tinh chỉnh.
