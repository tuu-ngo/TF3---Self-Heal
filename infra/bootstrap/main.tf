terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }

  # Bootstrap giữ local state có chủ đích — bucket này LÀ nơi lưu state chính,
  # không thể tự lưu state của nó vào chính nó (chicken-and-egg).
  # Chỉ B1 (Infra Lead) chạy 1 lần. Sau đó team còn lại chỉ cần terraform init.
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "tf3-cdo-02"
      Environment = "dev"
      ManagedBy   = "terraform-bootstrap"
    }
  }
}

# Bucket name gắn account ID để tránh conflict tên global S3
locals {
  bucket_name = "cdo-tf-state-938145531618-dev"
}

resource "aws_s3_bucket" "tfstate" {
  bucket = local.bucket_name

  lifecycle {
    prevent_destroy = true
  }
}

# Versioning bắt buộc — cho phép roll back state bị hỏng
resource "aws_s3_bucket_versioning" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id
  versioning_configuration {
    status = "Enabled"
  }
}

# AES256 encryption at rest
resource "aws_s3_bucket_server_side_encryption_configuration" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
    bucket_key_enabled = true
  }
}

# Chặn toàn bộ public access
resource "aws_s3_bucket_public_access_block" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Bucket policy: chỉ account 938145531618 có quyền đọc/ghi state
resource "aws_s3_bucket_policy" "tfstate" {
  bucket = aws_s3_bucket.tfstate.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "AllowTerraformStateAccess"
        Effect    = "Allow"
        Principal = { AWS = "arn:aws:iam::938145531618:root" }
        Action = [
          "s3:GetObject",
          "s3:PutObject",
          "s3:DeleteObject",
          "s3:ListBucket"
        ]
        Resource = [
          "arn:aws:s3:::${local.bucket_name}",
          "arn:aws:s3:::${local.bucket_name}/*"
        ]
      },
      {
        Sid       = "DenyNonSSL"
        Effect    = "Deny"
        Principal = "*"
        Action    = "s3:*"
        Resource = [
          "arn:aws:s3:::${local.bucket_name}",
          "arn:aws:s3:::${local.bucket_name}/*"
        ]
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })

  depends_on = [aws_s3_bucket_public_access_block.tfstate]
}
