module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.30"

  vpc_id                   = var.vpc_id
  subnet_ids               = var.subnet_ids
  control_plane_subnet_ids = var.subnet_ids

  # Public endpoint giới hạn theo IP workstation để kubectl được từ laptop (sandbox).
  # Pods/nodes vẫn dùng private endpoint. Đổi CIDR nếu IP thay đổi.
  cluster_endpoint_public_access       = true
  cluster_endpoint_public_access_cidrs = var.public_access_cidrs
  cluster_endpoint_private_access      = true

  # Required for IRSA (IAM Roles for Service Accounts)
  enable_irsa = true

  cluster_addons = {
    coredns    = { most_recent = true }
    kube-proxy = { most_recent = true }
    vpc-cni    = { most_recent = true }
  }

  eks_managed_node_groups = {
    default_node_group = {
      min_size     = 2
      max_size     = 5
      desired_size = 3 # 2→3: fix "too many pods" (t3.medium max 17 pod/node) + chỗ cho AI engine

      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
    }
  }

  tags = {
    Project     = "tf3-cdo-02"
    Environment = "dev"
  }
}
