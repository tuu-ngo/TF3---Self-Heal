output "repository_url" {
  description = "ECR repo URL cho image executor (dùng trong manifests/executor/deployment.yaml)"
  value       = aws_ecr_repository.executor.repository_url
}

output "repository_name" {
  value = aws_ecr_repository.executor.name
}
