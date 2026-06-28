output "cluster_endpoint" {
  description = "EKS API server endpoint"
  value       = module.eks.cluster_endpoint
}

output "cluster_name" {
  description = "EKS cluster name"
  value       = module.eks.cluster_name
}

output "audit_bucket_name" {
  description = "S3 Object Lock audit bucket"
  value       = module.audit.audit_bucket_name
}

output "dynamodb_table_name" {
  description = "DynamoDB idempotency lock table"
  value       = module.audit.dynamodb_table_name
}

output "sqs_queue_url" {
  description = "SQS telemetry buffer queue URL"
  value       = module.audit.sqs_queue_url
}

output "sqs_dlq_url" {
  description = "SQS dead-letter queue URL"
  value       = module.audit.sqs_dlq_url
}

output "executor_role_arn" {
  description = "IRSA role ARN for CDO executor pod"
  value       = module.iam.executor_role_arn
}

output "ai_engine_role_arn" {
  description = "IRSA role ARN for AI Engine pod (annotate vào SA ai-engine)"
  value       = module.iam.ai_engine_role_arn
}

output "ecr_executor_url" {
  description = "ECR repo URL cho image executor"
  value       = module.ecr.repository_url
}

output "ai_engine_secret_arn" {
  description = "ARN Secrets Manager tf-3/ai-engine/bedrock"
  value       = module.secrets.secret_arn
}
