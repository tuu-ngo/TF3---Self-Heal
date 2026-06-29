# Build Guide — T6 W11 (cập nhật W12: S3 remote state)

Thứ tự chạy chính xác. Đừng skip bước nào — mỗi bước depend vào bước trước.

---

## [W12 — B1 Infra Lead chạy 1 lần] Bước 0 — Bootstrap S3 state bucket

> **Chỉ B1 chạy bước này.** Sau khi bucket tồn tại, team còn lại bỏ qua bước 0 và chạy thẳng từ "Bước 0b".
> Bucket name: `cdo-tf-state-938145531618-dev` (account ID gắn vào để tránh conflict global).

```bash
cd infra/bootstrap
terraform init
terraform apply    # tạo S3 bucket + versioning + encryption + bucket policy
terraform output   # xác nhận tfstate_bucket_name
```

Expected output:
```
tfstate_bucket_name = "cdo-tf-state-938145531618-dev"
```

Sau đó migrate local state (nếu đã có `terraform.tfstate`) lên S3:

```bash
cd infra/envs/dev

# Nếu đã từng apply với local state, migrate state lên S3
terraform init -migrate-state
# Terraform hỏi "Do you want to copy existing state?" → nhập "yes"
```

Nếu chưa có local state (fresh start):

```bash
cd infra/envs/dev
terraform init   # tự dùng S3 backend ngay, không cần migrate
```

Kiểm tra state đã lên S3:

```bash
aws s3 ls s3://cdo-tf-state-938145531618-dev/envs/dev/
# phải thấy terraform.tfstate
```

---

## [W12 — Mọi thành viên còn lại] Bước 0b — Kết nối vào S3 remote state

> Chạy lệnh này **thay vì** bước 0. B1 đã tạo bucket rồi, bạn chỉ cần init.

```bash
# Đảm bảo AWS credentials đúng (cùng account 938145531618)
aws sts get-caller-identity

cd infra/envs/dev
terraform init    # tự nhận backend S3, không cần migrate
terraform plan    # xác nhận đọc được state chung
```

> **Quy tắc 1-apply-1-người (WORK_RULE §IV):** `terraform apply` chỉ 1 người chạy 1 lúc.
> S3 `use_lockfile = true` sẽ block apply thứ hai nếu đang có apply chạy.
> Không cần thêm DynamoDB lock vì Terraform >= 1.10 dùng S3 conditional writes.

---

## Trước khi bắt đầu

```bash
# Xác nhận AWS credentials
aws sts get-caller-identity

# Xác nhận cluster đang ACTIVE
aws eks describe-cluster --name cdo-eks-cluster-dev --query "cluster.status"

# Update kubeconfig
aws eks update-kubeconfig --name cdo-eks-cluster-dev --region us-east-1
kubectl get nodes
```

---

## Bước 1 — terraform init (bắt buộc vì thêm helm + kubernetes provider)

```bash
cd infra/envs/dev
terraform init
```

Expected: download hashicorp/helm ~2.0 và hashicorp/kubernetes ~2.0.

---

## Bước 2 — Apply namespaces trước (kubectl, không phải Terraform)

Kyverno và ArgoCD cần namespace tồn tại trước khi Helm deploy.

```bash
kubectl apply -f ../../manifests/namespaces/self-heal-system.yaml
kubectl apply -f ../../manifests/namespaces/argocd.yaml
kubectl apply -f ../../manifests/namespaces/kyverno.yaml
kubectl apply -f ../../manifests/namespaces/platform.yaml
kubectl apply -f ../../manifests/namespaces/tenant-a.yaml
kubectl apply -f ../../manifests/namespaces/tenant-b.yaml

# Xác nhận
kubectl get namespaces
```

---

## Bước 3 — terraform plan

```bash
terraform plan -out=tfplan-t6.out
```

Review plan — expected changes:
- `module.audit`: S3 bucket + DynamoDB + SQS (NEW)
- `module.iam`: IAM role + policy (NEW)
- `module.kyverno`: Helm release kyverno (NEW)
- `module.argocd`: Helm release argo-cd (NEW)
- `module.observability`: thêm log groups + alarms (UPDATE)
- `module.eks`: thêm enable_irsa + cluster_addons (UPDATE — sẽ không recreate cluster)

---

## Bước 4 — terraform apply

```bash
terraform apply tfplan-t6.out
```

Mất khoảng 10-15 phút (Helm releases chậm nhất).

---

## Bước 5 — Verify Kyverno và ArgoCD

```bash
# Kyverno pods RUNNING
kubectl get pods -n kyverno

# ArgoCD pods RUNNING
kubectl get pods -n argocd

# Lấy ArgoCD initial admin password
kubectl get secret argocd-initial-admin-secret -n argocd \
  -o jsonpath="{.data.password}" | base64 -d && echo

# Port-forward ArgoCD UI (optional)
kubectl port-forward svc/argocd-server -n argocd 8080:443
```

---

## Bước 6 — Apply Kyverno ClusterPolicies

```bash
kubectl apply -f ../../manifests/kyverno/policies/restrict-replicas.yaml
kubectl apply -f ../../manifests/kyverno/policies/restrict-memory-limit.yaml
kubectl apply -f ../../manifests/kyverno/policies/restrict-executor-namespace.yaml

# Xác nhận policies READY
kubectl get clusterpolicies
```

---

## Bước 7 — Test Kyverno policies (smoke test)

```bash
# Test 1: replicas > 10 bị deny
kubectl create deployment kyverno-test --image=nginx --replicas=11 -n tenant-a
# Expected: Error from server: admission webhook denied

# Test 2: deploy vào namespace không được phép bị deny
kubectl create deployment kyverno-test --image=nginx -n default
# Expected: Error from server: admission webhook denied

# Test 3: deploy hợp lệ vào tenant-a pass
kubectl apply -f ../../manifests/workloads/tenant-a-sample-app.yaml
kubectl apply -f ../../manifests/workloads/tenant-b-sample-app.yaml
```

---

## Bước 8 — Apply ArgoCD AppProjects và Applications

```bash
kubectl apply -f ../../manifests/argocd/appproject-tenant-a.yaml
kubectl apply -f ../../manifests/argocd/appproject-tenant-b.yaml

# TODO: cập nhật repoURL trong application manifests trước khi apply
# kubectl apply -f ../../manifests/argocd/application-tenant-a.yaml
# kubectl apply -f ../../manifests/argocd/application-tenant-b.yaml
```

---

## Bước 9 — Apply NetworkPolicy

```bash
kubectl apply -f ../../manifests/networkpolicies/allow-executor-to-ai.yaml

# Xác nhận
kubectl get networkpolicies -n self-heal-system
```

---

## Bước 10 — Verify audit resources

```bash
# S3 bucket tồn tại và có Object Lock
aws s3api get-object-lock-configuration \
  --bucket cdo-audit-cdo-eks-cluster-dev-dev

# DynamoDB table tồn tại
aws dynamodb describe-table --table-name cdo-idempotency-dev \
  --query "Table.{Status:TableStatus,BillingMode:BillingModeSummary.BillingMode}"

# SQS queues
aws sqs list-queues --queue-name-prefix cdo-telemetry
```

---

## Bước 11 — Lấy IRSA role ARN cho executor

```bash
terraform output executor_role_arn
# Copy ARN này vào ServiceAccount annotation của CDO executor pod
# kubernetes.io/aws-iam-role-arn: <ARN>
```

---

## Checklist cuối ngày

- [ ] S3 state bucket `cdo-tf-state-938145531618-dev` tồn tại, versioning ON, public access blocked
- [ ] `aws s3 ls s3://cdo-tf-state-938145531618-dev/envs/dev/` thấy `terraform.tfstate`
- [ ] Tất cả thành viên `terraform init` thành công, không còn local state
- [ ] `terraform apply` thành công, 0 errors
- [ ] Kyverno pods RUNNING, 3 ClusterPolicies READY
- [ ] Kyverno test: replicas=11 bị deny, namespace=default bị deny, tenant-a pass
- [ ] ArgoCD pods RUNNING, UI accessible qua port-forward
- [ ] S3 audit bucket tồn tại + Object Lock GOVERNANCE
- [ ] DynamoDB idempotency table ACTIVE
- [ ] SQS telemetry queue + DLQ tồn tại
- [ ] NetworkPolicy allow-executor-to-ai applied
- [ ] `terraform output` in ra đủ values
- [ ] Git commit toàn bộ với message "feat: T6 W11 build — Kyverno + ArgoCD + audit infra"
