module "vpc" {
  source       = "../../modules/vpc"
  environment  = var.environment
  cluster_name = var.cluster_name
}

module "eks" {
  source       = "../../modules/eks"
  cluster_name = var.cluster_name
  vpc_id       = module.vpc.vpc_id
  subnet_ids   = module.vpc.private_subnets
}

module "audit" {
  source         = "../../modules/audit"
  cluster_name   = var.cluster_name
  environment    = var.environment
  aws_account_id = var.aws_account_id
}

module "iam" {
  source             = "../../modules/iam"
  cluster_name       = var.cluster_name
  oidc_provider_arn  = module.eks.oidc_provider_arn
  oidc_issuer_url    = module.eks.cluster_oidc_issuer_url
  aws_account_id     = var.aws_account_id
  audit_bucket_name  = module.audit.audit_bucket_name
  dynamodb_table_arn = module.audit.dynamodb_table_arn
  sqs_queue_arn      = module.audit.sqs_queue_arn

  depends_on = [module.eks, module.audit]
}

module "observability" {
  source         = "../../modules/observability"
  cluster_name   = module.eks.cluster_name
  environment    = var.environment
  sqs_queue_name = module.audit.sqs_queue_name
  dlq_queue_name = module.audit.sqs_dlq_name

  depends_on = [module.audit]
}

module "ecr" {
  source = "../../modules/ecr"
}

module "secrets" {
  source = "../../modules/secrets"
}

# =============================================================================
# PHASE 2 — Helm releases (kyverno + argocd + kube-prometheus-stack)
# =============================================================================
# Helm cần provider trỏ vào EKS THẬT → tách phase-2 (không gộp 1 apply với việc
# tạo cluster vì provider không thể phụ thuộc resource tạo cùng lúc).
#
# ⚠ ADD-ONS NGOÀI TERRAFORM (có chủ đích — xem 04_deployment_design §1.4):
#   Ngoài 3 module Helm dưới, các thành phần sau hiện cài TAY (helm/kubectl),
#   KHÔNG do Terraform quản (nên `terraform apply` đơn thuần KHÔNG dựng lại full cụm):
#     - aws-load-balancer-controller (Helm; IRSA role cdo-aws-lb-controller-* do IaM/EKS tạo)
#     - Kyverno 4 ClusterPolicy: kubectl apply -f manifests/kyverno/policies/
#     - App Deployments: executor (k8s/03-executor.yaml), ai-engine + forwarder
#       (manifests/ai-engine, manifests/forwarder) — apply theo 09_deploy_runbook_live.md
#   Reproduce cụm = phase-1 apply → phase-2 apply → chạy runbook 09 (Phase 4-6).
#
# QUY TRÌNH bật phase-2 (chạy SAU khi phase-1 apply xong, cluster ACTIVE):
#   cd infra/envs/dev
#   mv providers.tf providers_phase1.tf.bak
#   mv providers_phase2.tf.disabled providers.tf      # provider trỏ cluster thật
#   # bỏ comment 3 module dưới
#   terraform init -reconfigure
#
#   # (CHỈ KHI cluster đã có release cài tay qua helm CLI) — import để adopt, tránh
#   #  lỗi "cannot re-use a name that is still in use". Cluster MỚI thì bỏ qua bước import:
#   terraform import module.kyverno.helm_release.kyverno              kyverno/kyverno
#   terraform import module.argocd.helm_release.argocd                argocd/argocd
#   terraform import module.monitoring.helm_release.kube_prometheus_stack monitoring/kube-prometheus-stack
#
#   terraform apply       # cluster mới: tạo cả 3; cluster đang chạy: reconcile (gần no-op)
# =============================================================================
# module "kyverno" {
#   source     = "../../modules/kyverno"
#   depends_on = [module.eks]
# }
#
# module "argocd" {
#   source      = "../../modules/argocd"
#   environment = var.environment
#   depends_on  = [module.eks]
# }
#
# module "monitoring" {
#   source                = "../../modules/monitoring"
#   forwarder_webhook_url = "http://cdo-telemetry-forwarder.monitoring.svc.cluster.local:8080/alerts"
#   depends_on            = [module.eks]
# }
