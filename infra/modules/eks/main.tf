module "eks" {
  source  = "terraform-aws-modules/eks/aws"
  version = "~> 19.0"

  cluster_name    = var.cluster_name
  cluster_version = "1.30"

  vpc_id                   = var.vpc_id
  subnet_ids               = var.subnet_ids
  control_plane_subnet_ids = var.subnet_ids

  # Public endpoint MỞ 0.0.0.0/0 (sandbox, user đồng ý — IP ISP động) qua var.public_access_cidrs.
  # EKS API vẫn yêu cầu IAM auth + RBAC → chỉ mở network reachability, không mở quyền.
  # Pods/nodes vẫn dùng private endpoint. Production: siết var.public_access_cidrs về IP/VPN cố định.
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
      desired_size = 4 # 4 node: chứa Online Boutique (11 svc) + AI engine + executor + forwarder + kube-prometheus-stack (t3.medium ~17 pod/node)

      instance_types = ["t3.medium"]
      capacity_type  = "ON_DEMAND"
    }
  }

  tags = {
    Project     = "tf3-cdo-02"
    Environment = "dev"
  }
}
