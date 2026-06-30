terraform {
  required_version = ">= 1.10"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    kubernetes = {
      source  = "hashicorp/kubernetes"
      version = "~> 2.0"
    }
    helm = {
      source  = "hashicorp/helm"
      version = "~> 2.0"
    }
  }

  # State bucket nằm ở ap-southeast-1 (tạo từ trước); resource deploy ở us-east-1.
  # State region độc lập với resource region — hợp lệ.
  backend "s3" {
    bucket       = "cdo-tf-state-012619468490-dev"
    key          = "envs/dev/terraform.tfstate"
    region       = "ap-southeast-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      Project     = "tf3-cdo-02"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# PHASE 1: cluster chưa tồn tại → kubernetes/helm provider để dummy (localhost).
# Không có module nào dùng 2 provider này ở phase-1 (kyverno/argocd/monitoring đang comment).
# PHASE 2 (sau khi EKS ACTIVE): thay file này bằng providers_phase2.tf.disabled (provider trỏ cluster thật).
provider "kubernetes" {
  host = "https://localhost"
}

provider "helm" {
  kubernetes {
    host = "https://localhost"
  }
}
