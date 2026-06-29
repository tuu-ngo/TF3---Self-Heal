output "vpc_id" { value = module.vpc.vpc_id }
output "private_subnets" { value = module.vpc.private_subnets }

output "s3_endpoint_id" {
  description = "ID của VPC Gateway Endpoint cho S3 (dùng để verify endpoint active)"
  value       = aws_vpc_endpoint.s3.id
}

output "dynamodb_endpoint_id" {
  description = "ID của VPC Gateway Endpoint cho DynamoDB (dùng để verify endpoint active)"
  value       = aws_vpc_endpoint.dynamodb.id
}
