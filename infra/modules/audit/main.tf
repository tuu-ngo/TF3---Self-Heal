# -------------------------------------------------------------------
# S3 Audit Bucket — Object Lock GOVERNANCE Mode, 90-day retention
# Admin có thể unlock với s3:BypassGovernanceRetention khi cần
# -------------------------------------------------------------------

resource "aws_s3_bucket" "audit" {
  bucket        = "cdo-audit-${var.cluster_name}-${var.environment}"
  force_destroy = false

  object_lock_enabled = true
}

resource "aws_s3_bucket_versioning" "audit" {
  bucket = aws_s3_bucket.audit.id
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id

  rule {
    default_retention {
      mode = "GOVERNANCE"
      days = 90
    }
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "audit" {
  bucket = aws_s3_bucket.audit.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "audit" {
  bucket                  = aws_s3_bucket.audit.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# -------------------------------------------------------------------
# DynamoDB — Idempotency Lock
# TTL 24h tự xoá, conditional write chặn duplicate execute
# -------------------------------------------------------------------

resource "aws_dynamodb_table" "idempotency" {
  name         = "cdo-idempotency-${var.environment}"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "idempotency_key"

  attribute {
    name = "idempotency_key"
    type = "S"
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  tags = {
    Project     = "tf3-cdo-02"
    Environment = var.environment
  }
}

# -------------------------------------------------------------------
# SQS — Telemetry Buffer + Dead-Letter Queue
# DLQ nhận message bị AI reject (400) sau 3 lần thử
# -------------------------------------------------------------------

resource "aws_sqs_queue" "telemetry_dlq" {
  name                      = "cdo-telemetry-dlq-${var.environment}"
  message_retention_seconds = 86400

  tags = {
    Project     = "tf3-cdo-02"
    Environment = var.environment
  }
}

resource "aws_sqs_queue" "telemetry" {
  name                       = "cdo-telemetry-${var.environment}"
  message_retention_seconds  = 3600
  visibility_timeout_seconds = 30

  redrive_policy = jsonencode({
    deadLetterTargetArn = aws_sqs_queue.telemetry_dlq.arn
    maxReceiveCount     = 3
  })

  tags = {
    Project     = "tf3-cdo-02"
    Environment = var.environment
  }
}
