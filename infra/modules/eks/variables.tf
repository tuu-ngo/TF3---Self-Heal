variable "cluster_name" {}
variable "vpc_id" {}
variable "subnet_ids" { type = list(string) }
# CIDR được phép gọi public EKS API (kubectl). Sandbox: 0.0.0.0/0 (user đồng ý) vì IP ISP động;
# EKS API VẪN yêu cầu IAM auth + RBAC → không phải mở truy cập, chỉ mở network reachability.
# Production: siết về IP/VPN cố định.
variable "public_access_cidrs" {
  type    = list(string)
  default = ["0.0.0.0/0"]
}
