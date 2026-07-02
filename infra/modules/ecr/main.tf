# ECR private repo cho image CDO executor (build từ executor/Dockerfile).
# Node group EKS đã có quyền AmazonEC2ContainerRegistryReadOnly → pod tự pull, không cần imagePullSecret.
resource "aws_ecr_repository" "executor" {
  name                 = "cdo-executor"
  image_tag_mutability = "IMMUTABLE" # ép tag theo commit-sha, không cho đè :latest

  image_scanning_configuration {
    scan_on_push = true # quét lỗ hổng mỗi lần push
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  force_delete = true # sandbox: cho phép xoá repo còn image khi teardown
}

# Giữ tối đa 10 image gần nhất, dọn untagged để tiết kiệm
resource "aws_ecr_lifecycle_policy" "executor" {
  repository = aws_ecr_repository.executor.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Giữ 10 image mới nhất"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ECR repo cho Alert Forwarder (build từ forwarder/Dockerfile).
resource "aws_ecr_repository" "forwarder" {
  name                 = "cdo-forwarder"
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  force_delete = true
}

resource "aws_ecr_lifecycle_policy" "forwarder" {
  repository = aws_ecr_repository.forwarder.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Giữ 10 image mới nhất"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}

# ECR repo cho AI Engine (image do AI team bàn giao, CDO deploy — xem 04_deployment_design §8).
# LƯU Ý: repo này đã tồn tại live (tạo tay trước khi đưa vào IaC) → adopt bằng import,
# KHÔNG apply thẳng (tránh ResourceAlreadyExistsException):
#   terraform import module.ecr.aws_ecr_repository.ai_engine ai-engine
resource "aws_ecr_repository" "ai_engine" {
  name = "ai-engine"
  # MUTABLE: AI team đẩy lại cùng tag (v3/v4/v5) khi vá engine trong lúc capstone.
  image_tag_mutability = "MUTABLE"

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  force_delete = true
}

resource "aws_ecr_lifecycle_policy" "ai_engine" {
  repository = aws_ecr_repository.ai_engine.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Giữ 10 image mới nhất"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 10
      }
      action = { type = "expire" }
    }]
  })
}
