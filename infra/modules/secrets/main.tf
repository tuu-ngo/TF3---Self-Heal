# AWS Secrets Manager — Bedrock credentials cho AI Engine (deployment-contract §3.B).
# CDO cấp "vỏ" secret + quyền IRSA (module iam/ đã grant GetSecretValue path tf-3/ai-engine/bedrock*).
# AI team điền VALUE thật — lifecycle ignore_changes giữ value AI set, Terraform không revert.
resource "aws_secretsmanager_secret" "bedrock" {
  name                    = "tf-3/ai-engine/bedrock-arthur"
  description             = "Bedrock API credentials cho AI Engine (AI team set value thật)"
  recovery_window_in_days = 0 # sandbox: xoá ngay khi teardown, không giữ 30 ngày
}

resource "aws_secretsmanager_secret_version" "bedrock" {
  secret_id = aws_secretsmanager_secret.bedrock.id
  secret_string = jsonencode({
    placeholder = "AI team set real Bedrock credentials here"
  })

  lifecycle {
    ignore_changes = [secret_string] # không ghi đè value AI team đã set
  }
}
