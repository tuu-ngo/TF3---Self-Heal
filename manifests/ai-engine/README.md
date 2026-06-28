# manifests/ai-engine/ — AI Engine deploy wrapper (chờ image AI team)

AI Engine là sản phẩm của **AI team**. CDO-02 chỉ **deploy** (wrapper) theo deployment-contract §2 — không sửa logic bên trong.

## Trạng thái
- `deployment.yaml.template` — **DISABLED** (đuôi `.template` → `kubectl apply -f` bỏ qua). Deployment + Service + HPA đã viết sẵn theo contract §2/§7.

## Đã dựng sẵn để cắm vào (không phải làm lại)
| Thành phần | Ở đâu |
|---|---|
| ServiceAccount `ai-engine` (IRSA) | [../rbac/ai-engine-serviceaccount.yaml](../rbac/ai-engine-serviceaccount.yaml) |
| IAM role (Bedrock/S3/DDB/SecretsManager) | `infra/modules/iam` (trust `self-heal-system:ai-engine`) |
| Secret `tf-3/ai-engine/bedrock` | `infra/modules/secrets` (AI team set value) |
| NetworkPolicy ingress (executor→8080) | [../networkpolicies/allow-executor-to-ai.yaml](../networkpolicies/allow-executor-to-ai.yaml) |

## Kích hoạt (W12 khi nhận image)
```bash
cd manifests/ai-engine
cp deployment.yaml.template deployment.yaml
# sửa <AI_ENGINE_IMAGE> = image AI bàn giao (ECR URI + tag)
kubectl apply -f deployment.yaml
kubectl -n self-heal-system rollout status deploy/ai-engine
kubectl -n self-heal-system exec deploy/ai-engine -- curl -s localhost:8080/ready
```

## Còn thiếu (coordinate với AI team)
- **Egress NetworkPolicy §5.B** (chặn AI gọi K8s API server, chỉ cho 443 ra AWS): cần `ipBlock` loại trừ API server CIDR theo môi trường — chốt với AI team rồi thêm vào `../networkpolicies/`.
