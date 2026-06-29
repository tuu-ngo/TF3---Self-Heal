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
