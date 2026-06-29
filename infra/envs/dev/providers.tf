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

  backend "s3" {
    bucket       = "cdo-tf-state-012619468490-arthur"
    key          = "envs/dev/terraform.tfstate"
    region       = "ap-southeast-1"
    use_lockfile = true
    encrypt      = true
  }
}

provider "aws" {
  region = "ap-southeast-1"

  default_tags {
    tags = {
      Project     = "tf3-cdo-02"
      Environment = var.environment
      ManagedBy   = "terraform"
    }
  }
}

# kubernetes + helm provider cấu hình sau khi EKS tồn tại (phase 2)
# Xem: infra/envs/dev/providers_phase2.tf.disabled
provider "kubernetes" {
  host = "https://localhost"
}

provider "helm" {
  kubernetes {
    host = "https://localhost"
  }
}
