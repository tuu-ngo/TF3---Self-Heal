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

# kyverno + argocd + monitoring dùng helm provider — apply sau khi EKS tồn tại (phase 2).
# Bật: (1) thay providers.tf bằng providers_phase2.tf (provider trỏ cluster thật),
#      (2) bỏ comment 3 module dưới, (3) terraform init && apply.
# module "kyverno" {
#   source = "../../modules/kyverno"
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
