# CI owns container images: the EKS Python image is built and pushed on every
# CodeCommit push, so the repository must exist before the EKS stacks are applied.
resource "aws_ecr_repository" "python_time" {
  name                 = var.python_ecr_repository_name
  image_tag_mutability = "MUTABLE"
  # Disposable assessment images; teardown must not hang on a non-empty repository.
  force_delete = true

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "AES256"
  }
}

resource "aws_ecr_lifecycle_policy" "python_time" {
  repository = aws_ecr_repository.python_time.name
  policy = jsonencode({
    rules = [{
      rulePriority = 1
      description  = "Keep the 20 most recent images"
      selection = {
        tagStatus   = "any"
        countType   = "imageCountMoreThan"
        countNumber = 20
      }
      action = { type = "expire" }
    }]
  })
}

# Live environment only: the repository was created with the AWS CLI before this stack owned it.
import {
  for_each = var.adopt_existing_resources ? toset([var.python_ecr_repository_name]) : toset([])
  to       = aws_ecr_repository.python_time
  id       = each.value
}

output "python_ecr_repository_url" {
  value = aws_ecr_repository.python_time.repository_url
}

output "python_ecr_repository_name" {
  value = aws_ecr_repository.python_time.name
}
