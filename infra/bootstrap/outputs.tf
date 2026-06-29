output "tfstate_bucket_name" {
  description = "Tên S3 bucket lưu Terraform remote state. Dùng giá trị này trong backend config của infra/envs/dev/providers.tf"
  value       = aws_s3_bucket.tfstate.id
}

output "tfstate_bucket_arn" {
  description = "ARN của S3 state bucket"
  value       = aws_s3_bucket.tfstate.arn
}
