output "secret_arn" {
  description = "ARN của Bedrock secret (AI Engine đọc qua IRSA)"
  value       = aws_secretsmanager_secret.bedrock.arn
}

output "secret_name" {
  value = aws_secretsmanager_secret.bedrock.name
}
